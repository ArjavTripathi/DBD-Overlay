"""End Game Collapse bar (top centre), used to infer hatch escapes.

The bar: a red teardrop cap at the left end + a long thin bar (grey, or
orange at times) across the top. Detected as BOTH:
  - a thin line brighter than the rows just above/below it, across most of
    the centre strip, at y ~0.031-0.036 h, and
  - red pixels where the cap sits.
Measured on ~2200 in-match frames from AJ's recordings: all 3 real EGC
periods found, no false positives (line >= 0.43 / cap 10-20% red on real
bars; world geometry on Trickster's/Toba fails one or the other).

Why it matters: a gate escape needs an opened gate, and opening a gate always
starts the EGC. So if the whole match was watched and the EGC never
appeared, any escape was through the hatch.
"""

from __future__ import annotations

import cv2
import numpy as np

from .roi import Roi

BODY = Roi(-0.5, 0.022, 0.5, 0.045, anchor="center")
CAP = Roi(-0.585, 0.024, -0.535, 0.044, anchor="center")
CAPTURE = Roi(-0.585, 0.022, 0.5, 0.045, anchor="center")  # BODY + CAP in one grab

LINE_ROWS = (0.030, 0.0365)
LINE_CONTRAST = 20
MIN_LINE = 0.30
MIN_CAP_RED = 0.08


def egc_visible(frame: np.ndarray) -> bool:
    h = frame.shape[0]
    gray = cv2.cvtColor(BODY.crop(frame), cv2.COLOR_BGR2GRAY).astype(np.int16)
    d = max(3, round(8 / 1440 * h))
    top = round(BODY.y0 * h)
    line = 0.0
    for y in range(int(LINE_ROWS[0] * h) - top, int(LINE_ROWS[1] * h) - top + 1):
        if d <= y < gray.shape[0] - d:
            row, around = gray[y], np.maximum(gray[y - d], gray[y + d])
            line = max(line, float(((row - around) > LINE_CONTRAST).mean()))
    if line < MIN_LINE:
        return False
    cap = CAP.crop(frame).astype(np.int16)
    b, g, r = cap[..., 0], cap[..., 1], cap[..., 2]
    return float(((r > 150) & (g < 70) & (b < 70)).mean()) >= MIN_CAP_RED
