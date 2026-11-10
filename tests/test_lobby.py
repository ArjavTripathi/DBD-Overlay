"""Lobby role detection: tracker logic (pure) + detector events on real frames."""

import shutil
from pathlib import Path

import cv2
import pytest

from dbd_overlay.core.catalog import load_killers, load_maps
from dbd_overlay.core.events import KillerDetected, LobbyChanged, RoleDetected
from dbd_overlay.core.models import Role
from dbd_overlay.detection.detector import MatchDetector
from dbd_overlay.detection.lobby import LobbyReading, LobbyRoleTracker, LobbyVisibilityTracker

FIX = Path(__file__).parent / "fixtures" / "screens"


def test_reading_roles():
    assert LobbyReading("READY", "The Hillbilly").role is Role.KILLER
    assert LobbyReading("PLAY", "The Slasher").role is Role.KILLER       # character menu header
    assert LobbyReading("CANCEL", None, "").role is Role.SURVIVOR
    assert LobbyReading("READY", None, "' ' L '").role is Role.SURVIVOR  # specks aren't a name
    assert LobbyReading("PLAY", None, "").role is None                   # not queued: can't tell
    assert LobbyReading("READY", None, "THE HLLLBLEI").role is None      # unreadable name: don't guess
    assert LobbyReading().role is None


def test_tracker_killer_immediately_survivor_after_two():
    t = LobbyRoleTracker()
    assert t.update(LobbyReading("READY", "The Hillbilly")) == (Role.KILLER, "The Hillbilly")
    assert t.update(LobbyReading("READY", "The Hillbilly")) == (None, None)   # no change, no event
    assert t.update(LobbyReading("CANCEL")) == (None, None)                   # one survivor vote
    assert t.update(LobbyReading("PLAY")) == (None, None)                     # resets the votes
    assert t.update(LobbyReading("CANCEL")) == (None, None)
    assert t.update(LobbyReading("CANCEL")) == (Role.SURVIVOR, None)
    assert t.update(LobbyReading("READY", "The Pig")) == (Role.KILLER, "The Pig")


@pytest.mark.skipif(shutil.which("tesseract") is None or not (FIX / "163745.webp").exists(),
                    reason="needs tesseract + fixtures")
def test_detector_publishes_lobby_role():
    det = MatchDetector(load_maps(), load_killers())
    events = det.process(cv2.imread(str(FIX / "163745.webp")), 0.0).events
    assert events == [KillerDetected("The Hillbilly", 1.0, source="lobby"), RoleDetected(Role.KILLER, source="lobby"),
                      LobbyChanged(True, "READY")]
    survivor = cv2.imread(str(FIX / "162530.webp"))
    assert det.process(survivor, 5.0).events == []                    # first survivor vote, same button
    assert det.process(survivor, 9.0).events == [RoleDetected(Role.SURVIVOR, source="lobby")]


def test_lobby_checked_between_matches_but_throttled():
    from dbd_overlay.detection.lobby import LOBBY_BUTTON
    det = MatchDetector(load_maps(), load_killers())
    det._last_lobby_check = 0.0
    assert LOBBY_BUTTON not in det.plan(2.0)
    assert LOBBY_BUTTON in det.plan(4.0)        # idle: every 4 s


def test_lobby_visibility_edges():
    t = LobbyVisibilityTracker()
    assert t.update(LobbyReading()) is None                            # never seen: nothing to hide
    assert t.update(LobbyReading("PLAY")) == LobbyChanged(True, "PLAY")
    assert t.update(LobbyReading("PLAY")) is None
    assert t.update(LobbyReading("CANCEL")) == LobbyChanged(True, "CANCEL")  # button change
    assert t.update(LobbyReading()) is None                            # one miss: could be a bad read
    assert t.update(LobbyReading("CANCEL")) is None                    # back: miss count resets
    assert t.update(LobbyReading()) is None
    assert t.update(LobbyReading()) == LobbyChanged(False, "CANCEL")   # gone, remembers the last button
    assert t.update(LobbyReading()) is None
