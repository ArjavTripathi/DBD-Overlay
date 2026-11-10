"""Discord Rich Presence: show lobby / match / character / map as your status.

Optional (off by default, `[discord] enabled`). Listens to detection events
on the bus, renders them with PresenceState, and a background thread sends
the result to Discord. The thread exists because socket I/O can block
(Discord starting up, hung) and must never stall detection or the UI.

Commands: toggle-discord.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from ...core.commands import CommandRouter
from ...core.config import DiscordConfig
from ...core.events import Event, EventBus
from ...core.session import Session
from .ipc import DiscordError, DiscordIpc
from .state import RELEVANT, PresenceState

log = logging.getLogger(__name__)

# Discord allows ~5 activity updates per 20 s; stay well under it. Changes
# made in between are not lost: the newest one is sent when the gap is over.
MIN_GAP = 4.0
RETRY_SECONDS = 15.0   # Discord not running yet / connection lost

Activity = dict[str, Any] | None
_UNSENT = object()


class Pusher:
    """Sends the newest wanted activity to Discord, rate-limited, reconnecting."""

    def __init__(self, connect: Callable[[], DiscordIpc]) -> None:
        self._connect = connect
        self._cond = threading.Condition()
        self._wanted: object = _UNSENT  # nothing to send until the first submit
        self._sent: object = _UNSENT
        self._stop = False
        self._ipc: DiscordIpc | None = None
        self._thread = threading.Thread(target=self._run, name="discord", daemon=True)
        self._thread.start()

    def submit(self, activity: Activity) -> None:
        with self._cond:
            self._wanted = activity
            self._cond.notify()

    def stop(self) -> None:
        """Clear the status and disconnect (waits up to a few seconds)."""
        with self._cond:
            self._stop = True
            self._cond.notify()
        self._thread.join(timeout=6)

    def _run(self) -> None:
        last = float("-inf")
        while True:
            with self._cond:
                # Sleep until there's something new to send (or we're stopping).
                self._cond.wait_for(lambda: self._stop or self._wanted != self._sent)
                if self._stop:
                    break
                wait = last + MIN_GAP - time.monotonic()
                if wait > 0:
                    self._cond.wait(wait)  # newer submits during the wait just replace _wanted
                    continue
                wanted = self._wanted
            last = time.monotonic()
            try:
                if self._ipc is None or not self._ipc.connected:
                    self._ipc = self._connect()
                self._ipc.set_activity(wanted)
                self._sent = wanted
                log.debug("discord: activity %s", wanted)
            except DiscordError as e:
                log.info("discord: %s; retrying in %.0f s", e, RETRY_SECONDS)
                self._sent = _UNSENT
                last = time.monotonic() + RETRY_SECONDS - MIN_GAP
        if self._ipc is not None and self._ipc.connected:
            try:
                self._ipc.set_activity(None)
            except DiscordError:
                pass
            self._ipc.close()


def _connect_to(client_id: str) -> Callable[[], DiscordIpc]:
    def connect() -> DiscordIpc:
        ipc = DiscordIpc(client_id)
        ipc.connect()
        return ipc
    return connect


class DiscordPresenceFeature:
    def __init__(
        self,
        bus: EventBus,
        router: CommandRouter,
        session: Session,
        cfg: DiscordConfig,
        save_enabled: Callable[[bool], None],
    ) -> None:
        self.session, self.save_enabled = session, save_enabled
        self._lock = threading.Lock()
        self.state = PresenceState(session)
        self.cfg = cfg
        self.pusher: Pusher | None = None
        for etype in RELEVANT:
            bus.subscribe(etype, self._on_event)
        router.register("toggle-discord", self._cmd_toggle)
        self.apply(cfg)

    def apply(self, cfg: DiscordConfig) -> str:
        """(Re)start or stop with new settings."""
        self.stop()  # outside the lock: joining the old thread can take a moment
        with self._lock:
            self.cfg = cfg
            self.state.large_image, self.state.show_map = cfg.large_image.strip(), cfg.show_map
            if not cfg.enabled:
                log.info("discord status: off")
                return "Discord status off"
            if not cfg.client_id.strip():
                log.warning("discord status is on but [discord] client_id is empty")
                return "Discord status needs a client ID (Settings > Discord)"
            self.pusher = Pusher(_connect_to(cfg.client_id.strip()))
            self.pusher.submit(self.state.activity())
            log.info("discord status: on")
            return "Discord status on"

    def stop(self) -> None:
        with self._lock:
            pusher, self.pusher = self.pusher, None
        if pusher is not None:
            pusher.stop()

    def _on_event(self, e: Event) -> None:
        # Called on the detection thread; the session already handled `e`
        # (it subscribed first), so role/killer/map are current.
        with self._lock:
            self.state.update(e)
            if self.pusher is not None:
                self.pusher.submit(self.state.activity())

    def _cmd_toggle(self) -> str:
        cfg = dataclasses.replace(self.cfg, enabled=not self.cfg.enabled)
        if cfg.enabled and not cfg.client_id.strip():
            raise ValueError("set your Discord client ID first (Settings > Discord)")
        msg = self.apply(cfg)
        self.save_enabled(cfg.enabled)
        return msg
