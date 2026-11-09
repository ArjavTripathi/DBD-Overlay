"""Background loop: find window -> capture -> run detectors -> publish events.

Runs on its own thread so slow OCR never freezes the UI. Polling is adaptive:
slow when the game isn't visible, normal (~1 fps) while idle, fast while a
title card is being read (it's only on screen a few seconds).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from ..core.events import EventBus, GameWindowChanged
from ..platform.base import ScreenCapture, WindowInfo, WindowLocator
from .map_detector import CardReading, TitleCardReader, TitleCardTracker

log = logging.getLogger(__name__)

NO_WINDOW_SECONDS = 5.0
HIDDEN_SECONDS = 2.0
FAST_SECONDS = 0.3


class DetectionService:
    def __init__(
        self,
        locator: WindowLocator,
        capture: ScreenCapture,
        reader: TitleCardReader,
        bus: EventBus,
        poll_seconds: float,
        debug_dir: Path | None = None,
    ) -> None:
        self.locator, self.capture, self.reader, self.bus = locator, capture, reader, bus
        self.poll_seconds = poll_seconds
        self.debug_dir = debug_dir
        self.tracker = TitleCardTracker()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="detection", daemon=True)
        self._window_state: str | None = None
        self._first_report = True
        self._last_debug_save = 0.0
        self._canvas: np.ndarray | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        delay = 0.0
        while not self._stop.wait(delay):  # wait() doubles as an interruptible sleep
            try:
                delay = self._tick()
            except Exception:
                log.exception("detection tick failed")
                delay = NO_WINDOW_SECONDS

    def _tick(self) -> float:
        win = self.locator.find_game_window()
        self._log_window(win)
        if win is None:
            return NO_WINDOW_SECONDS
        if not win.visible:
            return HIDDEN_SECONDS
        frame = self._grab(win)
        if frame is None:
            return HIDDEN_SECONDS
        reading = self.reader.read(frame)
        if reading.present:
            log.debug("card: map=%r realm=%r -> %s", reading.map_text, reading.realm_text, reading.match)
            self._maybe_save_debug(frame, reading)
        for event in self.tracker.update(reading, time.monotonic()):
            self.bus.publish(event)
        return FAST_SECONDS if self.tracker.pending else self.poll_seconds

    def _grab(self, win: WindowInfo) -> np.ndarray | None:
        """Capture only the region detectors need, pasted into a full-size frame.

        Detectors (and replay) keep working with ordinary full frames; the
        rest of the canvas just stays black. The canvas is reused per size.
        """
        region = self.reader.CAPTURE.rect(win.width, win.height)
        part = self.capture.grab(win, region)
        if part is None:
            return None
        if self._canvas is None or self._canvas.shape[:2] != (win.height, win.width):
            self._canvas = np.zeros((win.height, win.width, 3), np.uint8)
        l, t, r, b = region
        h, w = min(part.shape[0], b - t), min(part.shape[1], r - l)  # guard against off-by-one sizes
        self._canvas[t:t + h, l:l + w] = part[:h, :w]
        return self._canvas

    def _log_window(self, win: WindowInfo | None) -> None:
        state = "missing" if win is None else ("visible" if win.visible else "hidden")
        if state != self._window_state:
            log.info("game window: %s%s", state, f" ({win.width}x{win.height})" if win else "")
            was_visible = self._window_state == "visible"
            self._window_state = state
            if (state == "visible") != was_visible or self._first_report:
                self.bus.publish(GameWindowChanged(state == "visible"))
            self._first_report = False

    def _maybe_save_debug(self, frame, reading: CardReading) -> None:
        """Save teal-separator frames that didn't resolve to a map, to improve detection."""
        if self.debug_dir is None or not reading.teal or (reading.match and reading.match.confident):
            return
        now = time.monotonic()
        if now - self._last_debug_save < 2:
            return
        self._last_debug_save = now
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        stem = self.debug_dir / time.strftime("card-%Y%m%d-%H%M%S")
        cv2.imwrite(f"{stem}.png", frame)
        Path(f"{stem}.txt").write_text(
            f"map_text={reading.map_text!r}\nrealm_text={reading.realm_text!r}\nmatch={reading.match}\n"
        )
        log.info("saved unresolved title card to %s.png", stem)
