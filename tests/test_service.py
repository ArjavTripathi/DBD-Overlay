import shutil
from pathlib import Path

import cv2
import pytest

from dbd_overlay.core.catalog import load_maps
from dbd_overlay.core.events import EventBus, MapDetected, MatchStarted
from dbd_overlay.detection.map_detector import TitleCardReader
from dbd_overlay.detection.service import FAST_SECONDS, NO_WINDOW_SECONDS, DetectionService
from dbd_overlay.platform.base import WindowInfo

FRAME = Path(__file__).parent / "fixtures" / "screens" / "225200.png"


class FakeLocator:
    def __init__(self, win):
        self.win = win

    def find_game_window(self):
        return self.win


class FakeCapture:
    """Serves crops of a saved frame, like grim -g would."""

    def __init__(self, frame):
        self.frame, self.regions = frame, []

    def grab(self, window, region=None):
        self.regions.append(region)
        l, t, r, b = region or (0, 0, window.width, window.height)
        return self.frame[t:b, l:r].copy()


def make_service(win, capture):
    bus, events = EventBus(), []
    bus.subscribe(MapDetected, events.append)
    bus.subscribe(MatchStarted, events.append)
    svc = DetectionService(FakeLocator(win), capture, TitleCardReader(load_maps()), bus, poll_seconds=1.0)
    return svc, events


def test_no_window_polls_slowly():
    svc, events = make_service(None, FakeCapture(None))
    assert svc._tick() == NO_WINDOW_SECONDS and events == []


def test_hidden_window_is_not_captured():
    cap = FakeCapture(None)
    svc, _ = make_service(WindowInfo(0, 0, 2560, 1440, visible=False), cap)
    svc._tick()
    assert cap.regions == []


@pytest.mark.skipif(shutil.which("tesseract") is None or not FRAME.exists(), reason="needs tesseract + fixture")
def test_region_capture_detects_map_and_publishes():
    frame = cv2.imread(str(FRAME))
    cap = FakeCapture(frame)
    svc, events = make_service(WindowInfo(0, 0, 2560, 1440, visible=True), cap)
    svc._tick()
    # Only a strip was captured, not the full frame.
    l, t, r, b = cap.regions[0]
    assert (r - l) * (b - t) < 0.25 * 2560 * 1440
    assert events == [MatchStarted(), MapDetected("Backwater Swamp", "The Pale Rose", 1.0)]
    # Cooldown: card still visible next tick, nothing new published.
    assert svc._tick() in (1.0, FAST_SECONDS)
    assert len(events) == 2
