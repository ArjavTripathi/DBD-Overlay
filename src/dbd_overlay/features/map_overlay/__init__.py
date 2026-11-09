"""Map overlay feature: tracks the current map, asks the user when unsure.

M3: reports the detected map via a tray notification.
M4: shows the map PNG in a click-through overlay window.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject

from ...core.catalog import MapCatalog
from ...core.commands import CommandRouter
from ...core.events import EventBus, MapDetected
from ...core.models import Map
from ...ui.picker import MapPicker
from ...ui.qt_bridge import on_main_thread

log = logging.getLogger(__name__)


class MapOverlayFeature(QObject):
    def __init__(
        self,
        bus: EventBus,
        router: CommandRouter,
        catalog: MapCatalog,
        notify: Callable[[str, str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.bus, self.catalog, self.notify = bus, catalog, notify
        self.current: Map | None = None
        self.picker = MapPicker(catalog)
        self.picker.picked.connect(self._on_picked)
        on_main_thread(bus, MapDetected, self._on_map, self)
        router.register("pick-map", self._cmd_pick_map)

    def _on_map(self, e: MapDetected) -> None:
        if e.map is None:
            # Unsure: ask. Realm known -> short list; nothing known -> full list.
            log.info("map unclear (realm=%s); opening picker", e.realm)
            self.picker.open_for(e.realm)
            return
        self.current = self.catalog.find_map(e.map)
        self.picker.hide()
        how = "picked" if e.source == "manual" else f"detected, {e.confidence:.0%}"
        self.notify(e.map, f"{e.realm} ({how})")

    def _on_picked(self, realm: str, name: str) -> None:
        self.bus.publish(MapDetected(realm, name, 1.0, source="manual"))

    def _cmd_pick_map(self) -> str:
        # Always the full list: if detection got the realm wrong, a realm-only
        # list wouldn't contain the right answer.
        self.picker.open_for(None)
        return "picker open"
