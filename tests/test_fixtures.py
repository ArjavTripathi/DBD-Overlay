"""Every fixture screenshot against tests/fixtures/screens/manifest.json."""

import json
import shutil
from pathlib import Path

import cv2
import pytest

from dbd_overlay.core.catalog import load_killers, load_maps
from dbd_overlay.detection import replay
from dbd_overlay.detection.detector import MatchDetector

FIXTURES = Path(__file__).parent / "fixtures" / "screens"
MANIFEST = FIXTURES / "manifest.json"
CASES = json.loads(MANIFEST.read_text()).items() if MANIFEST.exists() else []


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="needs tesseract")
@pytest.mark.parametrize("name, expected", CASES)
def test_fixture(name, expected):
    frame = cv2.imread(str(FIXTURES / name))
    if frame is None:
        pytest.skip(f"{name} missing")
    # Fresh detector per frame: each frame is checked on its own.
    result = MatchDetector(load_maps(), load_killers(), exhaustive=True).process(frame, 0.0)
    assert replay.check(result, expected) == [], replay.describe(result)
