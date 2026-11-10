"""Minimal Discord Rich Presence client (local IPC, no dependencies).

The Discord desktop app listens on a local socket (Linux/macOS:
$XDG_RUNTIME_DIR/discord-ipc-0, Windows: the named pipe \\\\.\\pipe\\discord-ipc-0).
Every message is a frame:

    uint32 opcode (little-endian) | uint32 length | `length` bytes of JSON

Opcodes: 0 HANDSHAKE, 1 FRAME (commands and replies), 2 CLOSE.
Flow: send HANDSHAKE {v: 1, client_id}, receive the READY reply, then send
SET_ACTIVITY commands (each gets a reply we read and check).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import sys
import uuid
from pathlib import Path
from typing import Any, BinaryIO

log = logging.getLogger(__name__)

OP_HANDSHAKE, OP_FRAME, OP_CLOSE = 0, 1, 2
TIMEOUT = 5.0


class DiscordError(Exception):
    """Discord isn't running, refused us, or the connection broke."""


def socket_candidates() -> list[str]:
    if sys.platform == "win32":
        return [rf"\\.\pipe\discord-ipc-{i}" for i in range(10)]
    bases = [os.environ.get(v) for v in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP")] + ["/tmp"]
    # Flatpak/Snap Discord and Vesktop put the socket in a sub-folder.
    subdirs = ["", "app/com.discordapp.Discord", "snap.discord", ".flatpak/dev.vencord.Vesktop/xdg-run"]
    return [str(Path(b, s, f"discord-ipc-{i}")) for b in dict.fromkeys(filter(None, bases))
            for s in subdirs for i in range(10)]


class DiscordIpc:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self._sock: socket.socket | None = None
        self._pipe: BinaryIO | None = None  # Windows

    @property
    def connected(self) -> bool:
        return self._sock is not None or self._pipe is not None

    def connect(self) -> None:
        for path in socket_candidates():
            try:
                self._open(path)
            except OSError:
                continue
            try:
                self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
                op, reply = self._recv()
            except DiscordError:
                self.close()
                raise
            if op == OP_CLOSE or reply.get("evt") != "READY":
                self.close()
                # e.g. {'code': 4000, 'message': 'Invalid Client ID'}
                raise DiscordError(f"handshake refused: {reply.get('message', reply)}")
            user = reply.get("data", {}).get("user", {}).get("username", "?")
            log.info("discord: connected via %s as %s", path, user)
            return
        raise DiscordError("Discord isn't running (no IPC socket found)")

    def set_activity(self, activity: dict[str, Any] | None) -> None:
        """None clears the status."""
        cmd = {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": activity}, "nonce": str(uuid.uuid4())}
        self._send(OP_FRAME, cmd)
        op, reply = self._recv()
        if op == OP_CLOSE:
            self.close()
            raise DiscordError(f"closed by Discord: {reply}")
        if reply.get("evt") == "ERROR":
            # Bad payload (e.g. a field too long): not a connection problem.
            log.warning("discord rejected activity: %s", reply.get("data"))

    def close(self) -> None:
        for f in (self._sock, self._pipe):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
        self._sock = self._pipe = None

    # -- framing ---------------------------------------------------------------

    def _open(self, path: str) -> None:
        if sys.platform == "win32":
            self._pipe = open(path, "r+b", buffering=0)  # noqa: SIM115 (kept open)
            return
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        try:
            s.connect(path)
        except OSError:
            s.close()
            raise
        self._sock = s

    def _send(self, op: int, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        frame = struct.pack("<II", op, len(data)) + data
        try:
            if self._sock is not None:
                self._sock.sendall(frame)
            elif self._pipe is not None:
                self._pipe.write(frame)
            else:
                raise DiscordError("not connected")
        except OSError as e:
            self.close()
            raise DiscordError(f"send failed: {e}") from e

    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            try:
                chunk = self._sock.recv(n - len(buf)) if self._sock else self._pipe.read(n - len(buf))  # type: ignore[union-attr]
            except OSError as e:
                self.close()
                raise DiscordError(f"receive failed: {e}") from e
            if not chunk:
                self.close()
                raise DiscordError("connection closed")
            buf += chunk
        return buf

    def _recv(self) -> tuple[int, dict]:
        op, length = struct.unpack("<II", self._read(8))
        try:
            return op, json.loads(self._read(length))
        except json.JSONDecodeError as e:
            raise DiscordError(f"bad reply: {e}") from e
