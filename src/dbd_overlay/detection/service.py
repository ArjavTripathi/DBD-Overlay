"""Background loop: find window -> capture -> MatchDetector -> publish events.

Runs on its own thread so slow OCR never freezes the UI. Polling is adaptive:
slow when the game isn't visible, normal (~1 fps) while idle, fast while a
title card or end screen is on screen.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from ..core.events import EventBus, GameWindowChanged, MatchEnded
from ..core.models import SurvivorOutcome
from ..platform.base import Rect, ScreenCapture, WindowInfo, WindowLocator
from .detector import MatchDetector, TickResult
from .roi import Roi

log = logging.getLogger(__name__)

NO_WINDOW_SECONDS = 5.0
HIDDEN_SECONDS = 2.0
FAST_SECONDS = 0.3


class DetectionService:
    def __init__(
        self,
        locator: WindowLocator,
        capture: ScreenCapture,
        detector: MatchDetector,
        bus: EventBus,
        poll_seconds: float,
        debug_dir: Path | None = None,
    ) -> None:
        self.locator, self.capture, self.detector, self.bus = locator, capture, detector, bus
        self.poll_seconds = poll_seconds
        self.debug_dir = debug_dir
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="detection", daemon=True)
        self._window_state: str | None = None
        self._first_report = True
        self._last_debug_save = 0.0
        self._canvas: np.ndarray | None = None
        self._pasted: list[Rect] = []
        self._board_debug_saved = False

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
        now = time.monotonic()
        plan = self.detector.plan(now)
        frame = self._grab(win, plan)
        if frame is None:
            return HIDDEN_SECONDS
        result = self.detector.process(frame, now, plan)
        self._log_and_debug(frame, result)
        for event in result.events:
            self.bus.publish(event)
        return FAST_SECONDS if self.detector.busy else self.poll_seconds

    def _grab(self, win: WindowInfo, rois: list[Roi] | None) -> np.ndarray | None:
        """Full frame if rois is None, else only those regions pasted into a
        reused full-size canvas (detectors keep working with full frames)."""
        if rois is None:
            return self.capture.grab(win)
        if self._canvas is None or self._canvas.shape[:2] != (win.height, win.width):
            self._canvas = np.zeros((win.height, win.width, 3), np.uint8)
            self._pasted = []
        for l, t, r, b in self._pasted:  # clear last tick's regions: no stale pixels
            self._canvas[t:b, l:r] = 0
        self._pasted = []
        for roi in rois:
            rect = roi.rect(win.width, win.height)
            part = self.capture.grab(win, rect)
            if part is None:
                return None
            l, t, r, b = rect
            h, w = min(part.shape[0], b - t), min(part.shape[1], r - l)  # guard against off-by-one sizes
            self._canvas[t:t + h, l:l + w] = part[:h, :w]
            self._pasted.append(rect)
        return self._canvas

    def _log_window(self, win: WindowInfo | None) -> None:
        state = "missing" if win is None else ("visible" if win.visible else "hidden")
        if state != self._window_state:
            log.info("game window: %s%s", state, f" ({win.width}x{win.height})" if win else "")
            was_visible = self._window_state == "visible"
            old = self._window_state
            self._window_state = state
            # Report visibility changes, and game start/exit (hidden <-> missing) too.
            if (state == "visible") != was_visible or self._first_report or "missing" in (state, old):
                self.bus.publish(GameWindowChanged(state == "visible", running=state != "missing"))
            self._first_report = False

    def _log_and_debug(self, frame: np.ndarray, r: TickResult) -> None:
        card = r.card
        if card.present:
            log.debug("card: map=%r realm=%r -> %s", card.map_text, card.realm_text, card.match)
        if r.end is not None and r.end.kind is not None:
            log.debug("end screen: %s %r board=%s", r.end.kind, r.end.title, r.end.scoreboard)
        # Frames worth keeping to improve detection.
        if card.teal and not (card.match and card.match.confident):
            self._save_debug(frame, "card", f"map_text={card.map_text!r}\nrealm_text={card.realm_text!r}\nmatch={card.match}\n")
        if any(isinstance(e, MatchEnded) for e in r.events):
            self._board_debug_saved = False
        board = r.end.scoreboard if r.end else None
        unread = board is not None and SurvivorOutcome.UNKNOWN in board.statuses
        if board is not None and (not board.complete or unread) and not self._board_debug_saved:
            self._board_debug_saved = True  # one per match: these are full 1440p frames
            self._save_debug(frame, "scoreboard", f"{board}\n")

    def _save_debug(self, frame: np.ndarray, kind: str, text: str) -> None:
        if self.debug_dir is None:
            return
        now = time.monotonic()
        if now - self._last_debug_save < 2:
            return
        self._last_debug_save = now
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        stem = self.debug_dir / time.strftime(f"{kind}-%Y%m%d-%H%M%S")
        cv2.imwrite(f"{stem}.png", frame)
        Path(f"{stem}.txt").write_text(text)
        log.info("saved %s debug frame to %s.png", kind, stem)
