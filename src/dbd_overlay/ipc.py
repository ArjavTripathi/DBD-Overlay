"""Control channel between `dbd-overlay ctl <cmd>` and the running app.

Protocol: client sends one line (the command name), server replies with one
line ('ok...' or 'error: ...') and closes. Transport is QLocalServer/Socket:
a Unix socket on Linux, a named pipe on Windows, same code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

TIMEOUT_MS = 2000
MAX_LINE = 256


def send_command(name: str, server: str, timeout_ms: int = TIMEOUT_MS) -> str | None:
    """Send one command; returns the reply, or None if no instance is listening.

    Uses Qt's blocking wait* calls, which work without a running event loop,
    so the CLI stays a short-lived process.
    """
    sock = QLocalSocket()
    sock.connectToServer(server)
    if not sock.waitForConnected(timeout_ms):
        return None
    sock.write(name.encode() + b"\n")
    sock.waitForBytesWritten(timeout_ms)
    buf = b""
    while b"\n" not in buf:
        if not sock.waitForReadyRead(timeout_ms):
            break
        buf += bytes(sock.readAll().data())
    sock.disconnectFromServer()
    return buf.decode(errors="replace").strip() or "error: empty reply"


class ControlServer(QObject):
    def __init__(self, name: str, dispatch: Callable[[str], str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._dispatch = dispatch
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)

    def start(self) -> bool:
        """Listen. Returns False if another instance already owns the socket."""
        if send_command("ping", self._name, timeout_ms=300) is not None:
            return False
        # Nobody answered, so any socket file left over is stale (crash): remove it.
        QLocalServer.removeServer(self._name)
        # Only the current user may connect.
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self._server.listen(self._name):
            raise RuntimeError(f"cannot listen on {self._name}: {self._server.errorString()}")
        log.info("control socket: %s", self._server.fullServerName())
        return True

    def stop(self) -> None:
        self._server.close()

    def _on_connection(self) -> None:
        while (sock := self._server.nextPendingConnection()) is not None:
            buf = bytearray()

            def on_ready(sock: QLocalSocket = sock, buf: bytearray = buf) -> None:
                buf.extend(bytes(sock.readAll().data()))
                if len(buf) > MAX_LINE:
                    sock.abort()
                    return
                if b"\n" not in buf:
                    return  # partial line, wait for more
                cmd = buf.split(b"\n", 1)[0].decode(errors="replace")
                reply = self._dispatch(cmd)
                sock.write(reply.encode() + b"\n")
                sock.flush()
                sock.disconnectFromServer()

            sock.readyRead.connect(on_ready)
            sock.disconnected.connect(sock.deleteLater)
