"""Typed publish/subscribe event bus.

Features never call each other directly: detectors publish events, features
subscribe to the event types they care about. Adding a feature = adding a
subscriber; nothing existing changes.

Delivery is synchronous, on the publisher's thread. Detection runs on a worker
thread, so UI code must not subscribe directly; it uses
`ui.qt_bridge.on_main_thread`, which hops the event onto the Qt main thread.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from .models import ManualOutcome, MatchResult, Role

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    """Base class. Subscribing to Event receives everything (handy for logging)."""


@dataclass(frozen=True)
class MatchStarted(Event):
    pass


@dataclass(frozen=True)
class MatchEnded(Event):
    """Left the trial (scoreboard or back to lobby)."""


@dataclass(frozen=True)
class MapDetected(Event):
    realm: str | None
    map: str | None  # None = realm known but map unclear -> show picker
    confidence: float
    source: str = "auto"


@dataclass(frozen=True)
class RoleDetected(Event):
    role: Role
    source: str = "auto"


@dataclass(frozen=True)
class KillerDetected(Event):
    killer: str
    confidence: float
    source: str = "auto"


@dataclass(frozen=True)
class ResultDetected(Event):
    """End screen parsed; may still need user confirmation before recording."""

    result: MatchResult
    confident: bool


@dataclass(frozen=True)
class ResultRecorded(Event):
    """A match was written to the database (or a manual win/loss logged)."""

    match_id: int
    category: str
    manual: ManualOutcome | None = None


@dataclass(frozen=True)
class ResultsChanged(Event):
    """Undo / ignore / rule change: streak numbers must be recomputed."""


Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[type[Event], list[Handler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe[E: Event](self, etype: type[E], handler: Callable[[E], None]) -> Callable[[], None]:
        """Register handler for etype (and its subclasses). Returns an unsubscribe function."""
        with self._lock:
            self._subs[etype].append(handler)  # type: ignore[arg-type]

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._subs[etype]:
                    self._subs[etype].remove(handler)  # type: ignore[arg-type]

        return unsubscribe

    def publish(self, event: Event) -> None:
        # Walk the MRO so a subscriber to a base class sees subclass events.
        with self._lock:
            handlers = [h for t in type(event).__mro__ for h in self._subs.get(t, ())]
        log.debug("event %s -> %d handler(s)", event, len(handlers))
        for h in handlers:
            try:
                h(event)
            except Exception:
                # One broken feature must not take down detection or other features.
                log.exception("handler %r failed on %s", h, event)
