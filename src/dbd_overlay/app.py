"""Wire everything together and run the Qt event loop."""

from __future__ import annotations

import logging
import logging.handlers
import signal
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import platform
from .core import config as config_mod
from .core import paths
from .core.catalog import load_killers, load_maps
from .core.commands import CommandRouter
from .core.events import Event, EventBus
from .core.session import Session
from .detection.detector import MatchDetector
from .detection.service import DetectionService
from .features.killer_select import KillerSelectFeature
from .features.map_overlay import MapOverlayFeature
from .features.streaks import StreakFeature
from .features.streaks.icons import Icons
from .features.streaks.rules import Rules
from .features.streaks.service import StreakService
from .ipc import ControlServer
from .storage.db import Database
from .ui.overlay import HudWindow, OverlayWindow, create_engine, platform_variant
from .ui.settings import SettingsWindow
from .ui.tray import Tray

log = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    paths.log_file().parent.mkdir(parents=True, exist_ok=True)
    file = logging.handlers.RotatingFileHandler(paths.log_file(), maxBytes=1_000_000, backupCount=2)
    file.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers[:] = [console, file]
    root.setLevel(level)


class App:
    def __init__(self, config_path: Path, debug: bool) -> None:
        self.config_path = config_path
        self.cfg = config_mod.load(config_path)
        setup_logging("DEBUG" if debug else self.cfg.general.log_level)

        self.qt = QApplication.instance() or QApplication([])
        self.qt.setApplicationName("dbd-overlay")
        self.qt.setDesktopFileName("dbd-overlay")  # Wayland app_id = Hyprland window class
        self.qt.setQuitOnLastWindowClosed(False)  # closing a picker must not exit the app

        self.bus = EventBus()
        self.bus.subscribe(Event, lambda e: log.debug("bus: %s", e))
        self.db = Database(paths.db_file())
        self.router = CommandRouter()
        self.router.register("ping", lambda: "running")
        self.router.register("quit", self._quit)

        self.control = ControlServer(paths.control_socket_name(), self.router.dispatch)
        self.tray = Tray(self.router.dispatch)

        catalog, killers = load_maps(), load_killers()
        self.session = Session(self.bus, paths.state_file())
        self.killer_select = KillerSelectFeature(self.bus, self.router, killers, self.session, self.tray.notify)

        self.detection: DetectionService | None = None
        try:
            locator, capture = platform.create(self.cfg.capture.window_class)
        except RuntimeError as e:
            log.error("detection disabled: %s", e)  # app still works with manual commands
        else:
            debug_dir = paths.data_dir() / "debug" if self.cfg.general.save_failed_frames else None
            self.detection = DetectionService(
                locator, capture, MatchDetector(catalog, killers), self.bus, self.cfg.capture.poll_seconds, debug_dir
            )

        self.qml, self.images = create_engine(platform_variant())
        o = self.cfg.overlay
        self.map_feature: MapOverlayFeature | None = None
        try:
            window = OverlayWindow(self.qml, self.images, (o.x, o.y, o.width, o.height), o.opacity)
        except RuntimeError as e:
            log.error("map overlay disabled: %s", e)
        else:
            self.map_feature = MapOverlayFeature(
                self.bus, self.router, catalog, window,
                assets_dir=paths.assets_dir(o.assets_dir),
                auto_show=o.auto_show,
                notify=self.tray.notify,
                save_geometry=self._save_overlay_geometry,
                # Without detection we can't know where the game is: assume visible.
                game_visible=self.detection is None,
            )

        h = self.cfg.hud
        self.streaks: StreakFeature | None = None
        try:
            hud = HudWindow(self.qml, self.images, (h.x, h.y), h.opacity, h.scale)
        except RuntimeError as e:
            log.error("streak HUD disabled: %s", e)
        else:
            self.streaks = StreakFeature(
                self.bus, self.router, StreakService(self.db, Rules.from_config(self.cfg.streaks)),
                self.session, hud, Icons(paths.assets_dir(o.assets_dir)),
                show_mode=h.show, notify=self.tray.notify, save_position=self._save_hud_position,
                game_visible=self.detection is None,
            )
        self.router.register("edit-hud", self._cmd_edit)

        self.settings = SettingsWindow()
        self.settings.saved.connect(self._on_settings_saved)
        self.router.register("settings", self._cmd_settings)

    def _cmd_settings(self) -> str:
        self.settings.open(self.cfg.streaks, self.cfg.hud, self.streaks.streak_list() if self.streaks else [])
        return "settings open"

    def _on_settings_saved(self, streaks, hud_mode: str, history: bool, active: dict) -> None:
        self.cfg.streaks, self.cfg.hud.show = streaks, hud_mode
        config_mod.save(self.cfg, self.config_path)
        if self.streaks is not None:
            msg = self.streaks.apply_settings(Rules.from_config(streaks), hud_mode, history, active)
            self.tray.notify("Settings", msg)

    def _cmd_edit(self) -> str:
        """One hotkey edits every movable window (overlay + HUD) together."""
        parts = [f for f in (self.map_feature, self.streaks) if f is not None]
        if not parts:
            raise ValueError("no overlay windows")
        editing = not any(f.editing for f in parts)
        for f in parts:
            f.set_editing(editing)
        return "editing" if editing else "locked"

    def _save_hud_position(self, pos: tuple[int, int]) -> None:
        self.cfg.hud.x, self.cfg.hud.y = pos
        config_mod.save(self.cfg, self.config_path)
        log.info("HUD position saved: %s", pos)

    def _save_overlay_geometry(self, geometry: tuple[int, int, int, int]) -> None:
        o = self.cfg.overlay
        o.x, o.y, o.width, o.height = geometry
        config_mod.save(self.cfg, self.config_path)
        log.info("overlay geometry saved: %s", geometry)

    def _quit(self) -> str:
        # Reply to the caller first, then quit once control returns to the loop.
        QTimer.singleShot(0, self.qt.quit)
        return "bye"

    def run(self) -> int:
        if not self.control.start():
            log.error("dbd-overlay is already running")
            return 1
        self.tray.show()
        if self.detection:
            self.detection.start()

        # Qt's C++ loop doesn't let Python run signal handlers; a no-op timer
        # hands control back to Python regularly so Ctrl+C / SIGTERM work.
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.qt.quit())
        tick = QTimer()
        tick.start(250)
        tick.timeout.connect(lambda: None)

        log.info("dbd-overlay running (config %s, db %s)", self.config_path, paths.db_file())
        try:
            return self.qt.exec()
        finally:
            if self.detection:
                self.detection.stop()
            self.control.stop()
            self.db.close()
            log.info("stopped")
