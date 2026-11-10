"""Per-survivor status icon on the scoreboard (left of each name).

    exit door  -> escaped (gate and hatch look the same)
    skull      -> killed / sacrificed
    white flag -> surrendered
    silhouette -> still in the trial when you left (outcome unknown)

Classification by SHAPE: the icon's bright pixels are cropped to their
bounding box, padded square and shrunk to a 16x16 bitmap (a 'signature'),
then compared to reference signatures with Jaccard similarity (overlap /
union). Scale-independent, so it works at any resolution. The references in
data/status_icons.json are these tiny bitmaps, not game art.

Measured on AJ's scoreboards: same class 0.98-1.00, other classes <= 0.43.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

import cv2
import numpy as np

from ..core.models import SurvivorOutcome
from .roi import Roi

SIZE = 16
FOREGROUND = 150      # icons are near-white on a dark row
MIN_PIXELS = 20       # fewer bright pixels than this = no icon
MIN_SCORE = 0.75
MIN_MARGIN = 0.2      # best class must beat every other class by this much


def icon_roi(row_y: float) -> Roi:
    """Icon box for a scoreboard row whose name line is centred at row_y (height units)."""
    return Roi(0.150, row_y - 0.017, 0.184, row_y + 0.019)


def signature(crop: np.ndarray) -> np.ndarray | None:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    fg = (gray > FOREGROUND).astype(np.float32)
    ys, xs = np.nonzero(fg)
    if len(ys) < MIN_PIXELS:
        return None
    box = fg[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = box.shape
    s = max(h, w)
    square = np.zeros((s, s), np.float32)  # keep aspect ratio: it's part of the shape
    square[(s - h) // 2:(s - h) // 2 + h, (s - w) // 2:(s - w) // 2 + w] = box
    return cv2.resize(square, (SIZE, SIZE), interpolation=cv2.INTER_AREA) > 0.3


def to_hex(sig: np.ndarray) -> str:
    return np.packbits(sig.flatten()).tobytes().hex()


def from_hex(text: str) -> np.ndarray:
    return np.unpackbits(np.frombuffer(bytes.fromhex(text), np.uint8))[: SIZE * SIZE].reshape(SIZE, SIZE).astype(bool)


def jaccard(a: np.ndarray, b: np.ndarray) -> float:
    return float((a & b).sum()) / max(1, int((a | b).sum()))


@cache
def references() -> tuple[tuple[SurvivorOutcome, np.ndarray], ...]:
    data = json.loads(resources.files("dbd_overlay.data").joinpath("status_icons.json").read_text())
    return tuple((SurvivorOutcome(k), from_hex(h)) for k, hexes in data["icons"].items() for h in hexes)


def classify(crop: np.ndarray) -> tuple[SurvivorOutcome, float]:
    """(outcome, score). UNKNOWN if no icon, or nothing matches clearly (e.g. an
    icon we have no reference for yet, like a disconnect)."""
    sig = signature(crop)
    if sig is None:
        return SurvivorOutcome.UNKNOWN, 0.0
    best: dict[SurvivorOutcome, float] = {}
    for outcome, ref in references():
        best[outcome] = max(best.get(outcome, 0.0), jaccard(sig, ref))
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    (top, score), runner = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
    if score >= MIN_SCORE and score - runner >= MIN_MARGIN:
        return top, score
    return SurvivorOutcome.UNKNOWN, score
