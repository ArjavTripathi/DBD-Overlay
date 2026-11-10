"""End to end without Qt: real frames -> detector -> bus -> session -> streak service."""

import shutil
from pathlib import Path

import cv2
import pytest

from dbd_overlay.core.catalog import load_killers, load_maps
from dbd_overlay.core.config import StreakConfig
from dbd_overlay.core.events import EventBus, ScoreboardRead
from dbd_overlay.core.models import Verdict
from dbd_overlay.core.session import Session
from dbd_overlay.detection.detector import MatchDetector
from dbd_overlay.features.streaks.rules import Rules
from dbd_overlay.features.streaks.service import StreakService
from dbd_overlay.storage.db import Database

FIX = Path(__file__).parent / "fixtures" / "screens"


@pytest.mark.skipif(shutil.which("tesseract") is None or not (FIX / "162411.webp").exists(),
                    reason="needs tesseract + fixtures")
@pytest.mark.parametrize("frames, category, verdict", [
    (["162411.webp", "162429.webp"], "survivor", Verdict.WIN),                  # ESCAPED vs The Pig
    (["163428.webp", "163432.webp"], "survivor", Verdict.LOSS),                 # SACRIFICED vs The Nightmare
    (["164734.webp", "164740.webp"], "killer:The Hillbilly", Verdict.UNKNOWN),  # kills unread until M7
])
def test_end_screens_become_a_recorded_match(tmp_path, frames, category, verdict):
    bus = EventBus()
    session = Session(bus, tmp_path / "state.json")
    svc = StreakService(Database(":memory:"), Rules.from_config(StreakConfig()))
    svc.db.set_streak_active(category, True)
    recorded = []
    bus.subscribe(ScoreboardRead, lambda e: recorded.append(
        svc.record(svc.match_from_board(e, session.my_killer, session.map, session.realm))))

    det = MatchDetector(load_maps(), load_killers())
    for i, name in enumerate(frames):
        for e in det.process(cv2.imread(str(FIX / name)), float(i)).events:
            bus.publish(e)

    (m,) = recorded
    assert (m.category, m.verdict) == (category, verdict)
    assert session.category == category
