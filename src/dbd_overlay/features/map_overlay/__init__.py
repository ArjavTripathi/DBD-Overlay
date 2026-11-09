"""Map overlay feature: current map -> image in a click-through overlay window.

Listens to: MapDetected (show, or ask via picker), MatchEnded (hide),
GameWindowChanged (hide while the user is on another workspace).
Commands: toggle-overlay, pick-map, edit-hud.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QSize

from ...core.catalog import MapCatalog
from ...core.commands import CommandRouter
from ...core.events import EventBus, GameWindowChanged, MapDetected, MatchEnded
from ...core.models import Map
from ...detection.text import best_match
from ...ui.overlay import OverlayWindow, load_image
from ...ui.picker import MapPicker
from ...ui.qt_bridge import on_main_thread
from .assets import MapImages
from .state import OverlayState

log = logging.getLogger(__name__)

Geometry = tuple[int, int, int, int]
SET_MAP_MIN_SCORE = 70  # typed names are partial ('pale rose'), not OCR noise


class MapOverlayFeature(QObject):
    def __init__(
        self,
        bus: EventBus,
        router: CommandRouter,
        catalog: MapCatalog,
        window: OverlayWindow,
        assets_dir: Path,
        auto_show: bool,
        notify: Callable[[str, str], None],
        save_geometry: Callable[[Geometry], None],
        game_visible: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.bus, self.catalog, self.window = bus, catalog, window
        self.images = MapImages(assets_dir, catalog)
        self.auto_show, self.notify, self.save_geometry = auto_show, notify, save_geometry
        self.state = OverlayState(game_visible=game_visible)
        self.current: Map | None = None

        self.picker = MapPicker(catalog)
        self.picker.picked.connect(self._on_picked)
        window.edit_done.connect(lambda: self._set_editing(False))

        on_main_thread(bus, MapDetected, self._on_map, self)
        on_main_thread(bus, MatchEnded, self._on_match_ended, self)
        on_main_thread(bus, GameWindowChanged, self._on_game_window, self)
        router.register("pick-map", self._cmd_pick_map)
        router.register("set-map", self._cmd_set_map, takes_arg=True)
        router.register("toggle-overlay", self._cmd_toggle)
        router.register("edit-hud", self._cmd_edit)

        missing, _ = self.images.report()
        log.info("map images: %d of %d found in %s", len(catalog.maps) - len(missing), len(catalog.maps), assets_dir)

    # -- events ------------------------------------------------------------

    def _on_map(self, e: MapDetected) -> None:
        if e.map is None:
            # Unsure: ask. Realm known -> short list; nothing known -> full list.
            log.info("map unclear (realm=%s); opening picker", e.realm)
            self.picker.open_for(e.realm)
            return
        self.picker.hide()
        self.current = self.catalog.find_map(e.map)
        if self.current is None:
            log.warning("unknown map %r", e.map)
            return
        self._load_current_image()
        self.state.wanted = self.auto_show or e.source == "manual"
        if not self.state.has_image:
            self.notify(e.map, f"No image found. Expected {self.images.root / 'maps' / e.realm} / {e.map}.png")
        self._apply()

    def _on_match_ended(self, _: MatchEnded) -> None:
        self.state.wanted = False
        self._apply()

    def _on_game_window(self, e: GameWindowChanged) -> None:
        self.state.game_visible = e.visible
        self._apply()

    def _on_picked(self, realm: str, name: str) -> None:
        self.bus.publish(MapDetected(realm, name, 1.0, source="manual"))

    # -- commands ----------------------------------------------------------

    def _cmd_pick_map(self) -> str:
        # Always the full list: if detection got the realm wrong, a realm-only
        # list wouldn't contain the right answer.
        self.picker.open_for(None)
        return "picker open"

    def _cmd_set_map(self, text: str) -> str:
        m, score, _ = best_match(text, self.catalog.maps, lambda m: (m.name, *m.aliases))
        if m is None or score < SET_MAP_MIN_SCORE:
            raise ValueError(f"no map matches {text!r}")
        self.bus.publish(MapDetected(m.realm, m.name, 1.0, source="manual"))
        return m.name

    def _cmd_toggle(self) -> str:
        if self.current is None:
            return "no map yet (use pick-map)"
        self.state.wanted = not self.state.wanted
        self._apply()
        return "shown" if self.state.wanted else "hidden"

    def _cmd_edit(self) -> str:
        self._set_editing(not self.state.editing)
        return "editing" if self.state.editing else "locked"

    # -- helpers -----------------------------------------------------------

    def _set_editing(self, editing: bool) -> None:
        if editing == self.state.editing:
            return
        self.state.editing = editing
        self.window.set_edit_mode(editing)
        if not editing:
            self.save_geometry(self.window.geometry())
            self._load_current_image()  # re-fit to the new size
        self._apply()

    def _load_current_image(self) -> None:
        self.images.rescan()  # pick up files added while running
        path = self.images.find(self.current) if self.current else None
        size = self.window.size()
        # Decode at up to 2x the box size: sharp on HiDPI, small in memory.
        image = load_image(path, QSize(size.width() * 2, size.height() * 2)) if path else None
        self.state.has_image = image is not None
        self.window.set_image(image)
        self.window.set_placeholder(self.current.name if self.current else "Map overlay")

    def _apply(self) -> None:
        self.window.set_shown(self.state.shown)
