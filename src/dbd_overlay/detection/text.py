"""OCR + fuzzy-matching helpers shared by all detectors."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

import cv2
import numpy as np
import pytesseract
from rapidfuzz import fuzz


def norm(s: str) -> str:
    """Uppercase, strip accents, unify apostrophes, keep only letters/digits/'/space.

    'Léry’s Memorial' -> "LERY'S MEMORIAL"; OCR junk like '|' or '~' disappears.
    """
    # Apostrophes first: the ASCII step below would silently drop ’ and ‘.
    s = re.sub(r"[’‘`´]", "'", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_score(candidate: str, text: str) -> float:
    """0-100: how well `candidate` appears inside noisy OCR `text`.

    partial_ratio finds the best-aligned substring, so trailing junk from the
    background ('BACKWATER SWAMP BN A') doesn't hurt. Short names must match
    almost exactly, otherwise 'THE GAME' would hit random fragments.
    """
    c, t = norm(candidate), norm(text)
    if not c or not t:
        return 0.0
    score = fuzz.partial_ratio(c, t)
    if len(c) <= 9 and score < 95:
        return 0.0
    # A long candidate can't be "inside" much shorter text: partial_ratio would
    # otherwise align the text inside the candidate instead.
    if len(t) < 0.7 * len(c):
        score = min(score, fuzz.ratio(c, t))
    return score


def best_match[T](text: str, items: Iterable[T], names) -> tuple[T | None, float, float]:
    """Best item for `text`. `names(item)` yields the strings to compare
    (canonical name + aliases). Returns (item, score, runner_up_score).
    Ties prefer the longer name ('...EAST WING' beats '...POLICE STATION')."""
    scored = []
    for item in items:
        best = max(((match_score(n, text), len(n)) for n in names(item)), default=(0.0, 0))
        scored.append((best, item))
    if not scored:
        return None, 0.0, 0.0
    scored.sort(key=lambda s: s[0], reverse=True)
    (top, _), item = scored[0]
    runner = scored[1][0][0] if len(scored) > 1 else 0.0
    return (item if top > 0 else None), top, runner


def ocr_line(binary: np.ndarray) -> str:
    """OCR a single line of dark text on white."""
    return pytesseract.image_to_string(binary, config="--psm 7").strip()


def isolate_text(crop: np.ndarray, max_saturation: int | None = None, kernel: int = 15) -> np.ndarray:
    """Make a clean black-on-white image of light UI text over a 3D scene.

    1. top-hat: keep only things brighter than their local surroundings (text
       strokes), which flattens uneven backgrounds;
    2. optionally zero out coloured pixels: DBD's UI text is neutral grey/white,
       grass, fire and sky are not;
    3. upscale 2x (Tesseract likes ~30px+ letters), Otsu threshold, invert.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel, kernel))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
    if max_saturation is not None:
        sat = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1]
        th[sat > max_saturation] = 0
    th = cv2.resize(th, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    bw = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return 255 - bw


def isolate_desaturated_text(crop: np.ndarray, kernel: int = 15) -> np.ndarray:
    """Semi-transparent grey text over a saturated background (the realm line
    over Trickster's red walls): not brighter than its surroundings, but less
    saturated. Combines 'brighter + neutral' with 'less saturated than nearby'."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel, kernel))
    bright = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
    bright[sat > 50] = 0
    desat = cv2.morphologyEx(sat, cv2.MORPH_BLACKHAT, k)  # dips in saturation
    score = cv2.resize(np.maximum(bright, desat), None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return 255 - cv2.threshold(score, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
