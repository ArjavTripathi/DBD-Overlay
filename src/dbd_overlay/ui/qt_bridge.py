"""Deliver bus events to Qt code on the main (GUI) thread.

Qt widgets may only be touched from the thread that created them. Detection
publishes from a worker thread, so a UI subscriber goes through a Qt signal:
emitting from another thread queues the call into the main thread's event
loop (Qt's AutoConnection does this automatically across threads).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from ..core.events import Event, EventBus


class _Relay(QObject):
    fired = Signal(object)


def on_main_thread[E: Event](
    bus: EventBus, etype: type[E], callback: Callable[[E], None], parent: QObject
) -> Callable[[], None]:
    """Subscribe `callback` to `etype`; it always runs on `parent`'s thread."""
    relay = _Relay(parent)  # lives in parent's (main) thread
    relay.fired.connect(callback)
    return bus.subscribe(etype, relay.fired.emit)
