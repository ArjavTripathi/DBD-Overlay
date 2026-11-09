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
from .core.catalog import load_maps
from .core.commands import CommandRouter
from .core.events import Event, EventBus
from .detection.map_detector import TitleCardReader
from .detection.service import DetectionService
from .features.map_overlay import MapOverlayFeature
from .ipc import ControlServer
from .storage.db import Database
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

        catalog = load_maps()
        self.map_feature = MapOverlayFeature(self.bus, self.router, catalog, self.tray.notify)

        self.detection: DetectionService | None = None
        try:
            locator, capture = platform.create(self.cfg.capture.window_class)
        except RuntimeError as e:
            log.error("detection disabled: %s", e)  # app still works with manual commands
        else:
            debug_dir = paths.data_dir() / "debug" if self.cfg.general.save_failed_frames else None
            self.detection = DetectionService(
                locator, capture, TitleCardReader(catalog), self.bus, self.cfg.capture.poll_seconds, debug_dir
            )

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
