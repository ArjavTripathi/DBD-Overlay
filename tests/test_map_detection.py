import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from dbd_overlay.core.catalog import MapCatalog, load_maps
from dbd_overlay.core.events import MapDetected, MatchStarted
from dbd_overlay.detection import replay
from dbd_overlay.detection.map_detector import (
    CardReading,
    MapMatch,
    TitleCardReader,
    TitleCardTracker,
    resolve,
)
from dbd_overlay.detection.roi import Roi
from dbd_overlay.detection.text import match_score, norm

CAT = load_maps()
FIXTURES = Path(__file__).parent / "fixtures" / "screens"


# -- catalog -------------------------------------------------------------------


def test_catalog_is_consistent():
    names = [m.name for m in CAT.maps]
    assert len(names) == len(set(names)), "duplicate map name"
    assert all(r.maps for r in CAT.realms)
    assert CAT.find_map("The Pale Rose").realm == "Backwater Swamp"


# -- text helpers --------------------------------------------------------------


def test_norm():
    assert norm("Léry’s  Memorial|Institute~") == "LERY'S MEMORIAL INSTITUTE"


def test_short_names_need_near_exact_match():
    assert match_score("The Game", "THE GAME") == 100
    assert match_score("The Game", "THE GAMF") == 0
    assert match_score("Coal Tower", "COAL TOWER") == 100


def test_long_candidate_not_matched_by_short_fragment():
    assert match_score("Raccoon City Police Station East Wing", "EAST WING") < 50


# -- resolve() -----------------------------------------------------------------


@pytest.mark.parametrize(
    "map_text, realm_text, expected",
    [
        # Real OCR output from AJ's frames: junk after the realm text.
        ("THE PALE ROSE", "BACKWATER SWAMP “ :.A‘\\\\‘ /i ,", ("Backwater Swamp", "The Pale Rose")),
        # OCR confusions on the map line, realm confirms it.
        ("THE PALE R0SE", "BACKWATER SWAMP", ("Backwater Swamp", "The Pale Rose")),
        ("GRlM PANTRY", "BACKWATER SWAMR", ("Backwater Swamp", "Grim Pantry")),
        # Realm unreadable, clear map line.
        ("FATHER CAMPBELL'S CHAPEL", "", ("Crotus Prenn Asylum", "Father Campbell's Chapel")),
        # One-map realm: realm line alone is enough.
        ("~~~", "HADDONFIELD", ("Haddonfield", "Lampkin Lane")),
        # Accents/apostrophes.
        ("TREATMENT THEATRE", "LERY'S MEMORIAL INSTITUTE", ("Léry's Memorial Institute", "Treatment Theatre")),
        # Near-identical names: one word decides.
        ("RACCOON CITY POLICE STATION EAST WING", "RACCOON CITY", ("Raccoon City", "Raccoon City Police Station East Wing")),
        ("RACCOON CITY POLICE STATION WEST WING", "RACCOON CITY", ("Raccoon City", "Raccoon City Police Station West Wing")),
    ],
)
def test_resolve_confident(map_text, realm_text, expected):
    m = resolve(map_text, realm_text, CAT)
    assert m is not None and (m.realm, m.map) == expected
    assert m.confident


def test_resolve_realm_only_when_map_unreadable():
    m = resolve("#@! ;", "BACKWATER SWAMP", CAT)
    assert m == MapMatch("Backwater Swamp", None, 1.0)
    assert not m.confident


def test_resolve_nothing_from_junk():
    # Real OCR of the friends list (false separator line).
    assert resolve("i LOBSTERANKLES ovenss I L o e e et - L RSN e", ". . L |", CAT) is None
    assert resolve("", "", CAT) is None


def test_resolve_uses_aliases():
    cat = MapCatalog.from_dict({"realms": [{"name": "R", "maps": [{"name": "Long Map Name", "aliases": ["LMN Alias"]}, "Other Map"]}]})
    assert resolve("LMN ALIAS", "R", cat).map == "Long Map Name"


# -- tracker -------------------------------------------------------------------

PALE = CardReading(1240, True, "THE PALE ROSE", "BACKWATER SWAMP", MapMatch("Backwater Swamp", "The Pale Rose", 1.0))
REALM_ONLY = CardReading(1240, True, "??", "BACKWATER SWAMP", MapMatch("Backwater Swamp", None, 1.0))
UNREADABLE_TEAL = CardReading(1240, True)
FRIENDS_LIST = CardReading(1247, False, "LOBSTER ANKLES")
NOTHING = CardReading()


def run_tracker(readings, step=1.0, tracker=None):
    t = tracker or TitleCardTracker()
    out = []
    for i, r in enumerate(readings):
        out += t.update(r, i * step)
    return out


def test_tracker_publishes_once_per_card():
    events = run_tracker([NOTHING, PALE, PALE, PALE, NOTHING, NOTHING])
    assert events == [MatchStarted(), MapDetected("Backwater Swamp", "The Pale Rose", 1.0)]


def test_tracker_realm_only_after_card_disappears():
    events = run_tracker([REALM_ONLY, REALM_ONLY, NOTHING, NOTHING, NOTHING, NOTHING])
    assert events == [MatchStarted(), MapDetected("Backwater Swamp", None, 1.0)]


def test_tracker_upgrades_partial_to_confident():
    events = run_tracker([REALM_ONLY, PALE])
    assert events[-1].map == "The Pale Rose"


def test_tracker_unreadable_teal_card_asks_user():
    events = run_tracker([UNREADABLE_TEAL] * 3 + [NOTHING] * 4)
    assert events == [MatchStarted(), MapDetected(None, None, 0.0)]


def test_tracker_ignores_friends_list():
    assert run_tracker([FRIENDS_LIST] * 30) == []


def test_tracker_cooldown_then_next_match():
    t = TitleCardTracker(cooldown=90)
    assert len(run_tracker([PALE], tracker=t)) == 2
    assert t.update(PALE, 10) == []     # same card still visible
    assert len(t.update(PALE, 200)) == 2  # next match


# -- ROI -----------------------------------------------------------------------


def test_roi_scales_with_height_and_anchors():
    r = Roi(0.1, 0.5, 0.2, 0.6)
    assert r.rect(2560, 1440) == (144, 720, 288, 864)
    assert r.rect(1920, 1080) == (108, 540, 216, 648)
    right = Roi(0.1, 0.0, 0.2, 0.1, anchor="right")
    assert right.rect(3440, 1440) == (3152, 0, 3296, 144)  # ultrawide: hugs the right edge


# -- real frames (needs tesseract + fixture images) -----------------------------

needs_frames = pytest.mark.skipif(
    shutil.which("tesseract") is None or not (FIXTURES / "manifest.json").exists(),
    reason="tesseract or fixture screenshots missing",
)


@needs_frames
@pytest.mark.parametrize("name, expected", json.loads((FIXTURES / "manifest.json").read_text()).items()
                         if (FIXTURES / "manifest.json").exists() else [])
def test_fixture_frames(name, expected):
    frame = cv2.imread(str(FIXTURES / name))
    assert frame is not None
    assert replay.check(TitleCardReader(CAT).read(frame), expected)


@needs_frames
def test_detection_survives_1080p():
    """Same frame downscaled to 1920x1080: ROIs and kernels must scale."""
    frame = cv2.imread(str(FIXTURES / "225200.png"))
    small = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
    m = TitleCardReader(CAT).read(small).match
    assert m is not None and m.map == "The Pale Rose"


def test_no_card_on_blank_frame():
    assert not TitleCardReader(CAT).read(np.zeros((1440, 2560, 3), np.uint8)).present
