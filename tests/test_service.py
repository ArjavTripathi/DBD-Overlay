import shutil
from pathlib import Path

import cv2
import pytest

from dbd_overlay.core.catalog import load_killers, load_maps
from dbd_overlay.core.events import Event, EventBus, MapDetected, MatchEnded, MatchStarted
from dbd_overlay.detection.detector import MatchDetector
from dbd_overlay.detection.service import NO_WINDOW_SECONDS, DetectionService
from dbd_overlay.platform.base import WindowInfo

FIX = Path(__file__).parent / "fixtures" / "screens"
WIN = WindowInfo(0, 0, 2560, 1440, visible=True)


class FakeLocator:
    def __init__(self, win):
        self.win = win

    def find_game_window(self):
        return self.win


class FakeCapture:
    """Serves crops of a saved frame, like grim -g would."""

    def __init__(self, frame=None):
        self.frame, self.regions = frame, []

    def grab(self, window, region=None):
        self.regions.append(region)
        l, t, r, b = region or (0, 0, window.width, window.height)
        return self.frame[t:b, l:r].copy()


def make_service(win, capture):
    bus, events = EventBus(), []
    bus.subscribe(Event, events.append)
    svc = DetectionService(FakeLocator(win), capture, MatchDetector(load_maps(), load_killers()), bus, poll_seconds=1.0)
    return svc, events


def game_events(events):
    return [e for e in events if not type(e).__name__ == "GameWindowChanged"]


def test_no_window_polls_slowly():
    svc, events = make_service(None, FakeCapture())
    assert svc._tick() == NO_WINDOW_SECONDS and game_events(events) == []


def test_hidden_window_is_not_captured():
    cap = FakeCapture()
    svc, _ = make_service(WindowInfo(0, 0, 2560, 1440, visible=False), cap)
    svc._tick()
    assert cap.regions == []


needs = pytest.mark.skipif(
    shutil.which("tesseract") is None or not (FIX / "230226.png").exists(), reason="needs tesseract + fixtures"
)


@needs
def test_title_card_with_small_regions_only():
    cap = FakeCapture(cv2.imread(str(FIX / "225200.png")))
    svc, events = make_service(WIN, cap)
    svc._tick()
    assert all(r is not None for r in cap.regions), "idle ticks must not grab the full frame"
    assert sum((r - l) * (b - t) for l, t, r, b in cap.regions) < 0.3 * 2560 * 1440
    assert game_events(events) == [MatchStarted(), MapDetected("Backwater Swamp", "The Pale Rose", 1.0)]


@needs
def test_end_screen_then_full_frame_scoreboard():
    cap = FakeCapture(cv2.imread(str(FIX / "230226.png")))
    svc, events = make_service(WIN, cap)
    svc._tick()                 # small regions: sees the red title -> MatchEnded
    assert MatchEnded() in events
    svc._tick()                 # now grabs the full frame and reads the scoreboard
    assert cap.regions[-1] is None
    names = [type(e).__name__ for e in game_events(events)]
    assert names == ["MatchEnded", "ScoreboardRead", "KillerDetected", "RoleDetected"]


@needs
def test_stale_regions_are_cleared():
    """A region captured last tick but not this one must not linger in the canvas."""
    svc, _ = make_service(WIN, FakeCapture(cv2.imread(str(FIX / "233233.png"))))
    svc.detector.tracker.phase = svc.detector.tracker.phase.MATCH  # lobby checks only run in a match
    from dbd_overlay.detection.lobby import LOBBY_BUTTON
    frame = svc._grab(WIN, [LOBBY_BUTTON])
    assert frame[LOBBY_BUTTON.rect(2560, 1440)[1] + 5].any()
    frame = svc._grab(WIN, [])
    assert not frame.any()
