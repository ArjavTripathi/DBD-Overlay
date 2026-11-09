"""Regions of interest, independent of resolution.

Coordinates are in units of the window HEIGHT, measured from the left or
right edge. DBD's HUD scales with window height and hugs the screen edges, so
"0.08 heights from the left" is the same spot at 1080p, 1440p and (assumed,
unverified) on ultrawide, where width fractions would drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class Roi:
    x0: float
    y0: float
    x1: float
    y1: float
    anchor: Literal["left", "right"] = "left"

    def rect(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Pixel (left, top, right, bottom), clamped to the frame."""
        if self.anchor == "left":
            l, r = self.x0 * height, self.x1 * height
        else:
            l, r = width - self.x1 * height, width - self.x0 * height

        def clamp(v: float, hi: int) -> int:
            return max(0, min(hi, round(v)))

        return clamp(l, width), clamp(self.y0 * height, height), clamp(r, width), clamp(self.y1 * height, height)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        l, t, r, b = self.rect(w, h)
        return frame[t:b, l:r]
