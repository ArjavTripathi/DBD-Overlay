"""Title card (bottom-left at match start) -> realm + map.

Layout, measured on 2560x1440 frames:

    THE PALE ROSE          <- map: bright white, ~0.82-0.85 h
    ──────────────────     <- separator: thin teal line at ~0.861 h
    BACKWATER SWAMP        <- realm: dim grey, ~0.867-0.886 h

The separator is the cheap "is a title card on screen?" test (no OCR). Text
crops are taken relative to wherever the separator was found. Other UI also
has long horizontal lines there (friends list borders), so a line alone only
triggers OCR; the line being *teal* is extra evidence used when OCR fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from ..core.catalog import MapCatalog
from ..core.events import Event, MapDetected, MatchStarted
from .roi import Roi
from .text import best_match, isolate_text, ocr_line

log = logging.getLogger(__name__)

# Where to look for the separator (height units, see roi.py).
SEPARATOR_BAND = Roi(0.09, 0.845, 0.50, 0.878)
SEPARATOR_MIN_COVERAGE = 0.9   # fraction of the band width the line must span
SEPARATOR_CONTRAST = 15        # line vs. rows just above/below (grey levels)
TEAL_MIN_G_MINUS_R = 10        # real separator: G-R ~ +25; friends-list borders: ~ -11

# Text boxes relative to the separator row, height units.
TEXT_X = (0.06, 1.35)
MAP_ABOVE = (0.045, 0.003)     # from y-0.045h to y-0.003h
REALM_BELOW = (0.003, 0.035)
REALM_MAX_SATURATION = 50      # realm text is neutral grey; drop coloured background

# Matching thresholds (rapidfuzz scores, 0-100).
REALM_MIN = 80
MAP_MIN = 85            # map alone, no realm to back it up
MAP_IN_REALM_MIN = 65   # map among the few maps of an already-matched realm
MARGIN = 8              # top score must beat the runner-up by this much...
SURE = 95               # ...unless it's this good (RPD East vs West differ by one word)
CONFIDENT = 0.8         # MapMatch.confidence needed to auto-show the overlay


@dataclass(frozen=True)
class MapMatch:
    realm: str | None
    map: str | None      # None = realm known, map unclear
    confidence: float    # 0..1

    @property
    def confident(self) -> bool:
        return self.map is not None and self.confidence >= CONFIDENT


@dataclass(frozen=True)
class CardReading:
    separator_y: int | None = None
    teal: bool = False
    map_text: str = ""
    realm_text: str = ""
    match: MapMatch | None = None

    @property
    def present(self) -> bool:
        return self.separator_y is not None


def _decisive(top: float, runner: float, minimum: float) -> bool:
    return top >= minimum and (top >= SURE or top - runner >= MARGIN)


def resolve(map_text: str, realm_text: str, catalog: MapCatalog) -> MapMatch | None:
    """Turn the two OCR'd lines into a MapMatch. Pure function: easy to test."""
    realm, rs, rrun = best_match(realm_text, catalog.realms, lambda r: (r.name, *r.aliases))
    if not _decisive(rs, rrun, REALM_MIN):
        realm = None

    if realm is not None:
        m, ms, mrun = best_match(map_text, realm.maps, lambda m: (m.name, *m.aliases))
        if m is not None and _decisive(ms, mrun, MAP_IN_REALM_MIN):
            return MapMatch(realm.name, m.name, (ms + rs) / 200)
        if len(realm.maps) == 1:  # one-map realm: the realm line alone is enough
            return MapMatch(realm.name, realm.maps[0].name, 0.9 * rs / 100)
        return MapMatch(realm.name, None, rs / 100)

    m, ms, mrun = best_match(map_text, catalog.maps, lambda m: (m.name, *m.aliases))
    if m is not None and _decisive(ms, mrun, MAP_MIN):
        return MapMatch(m.realm, m.name, 0.9 * ms / 100)  # no realm confirmation: slight discount
    return None


class TitleCardReader:
    # Everything read() can touch: separator band +/- the text boxes around it.
    CAPTURE = Roi(0.0, SEPARATOR_BAND.y0 - MAP_ABOVE[0] - 0.01, TEXT_X[1],
                  SEPARATOR_BAND.y1 + REALM_BELOW[1] + 0.01)

    def __init__(self, catalog: MapCatalog) -> None:
        self.catalog = catalog

    def find_separator(self, frame: np.ndarray) -> tuple[int, bool] | None:
        """(row, is_teal) of a long thin horizontal line in the band, or None."""
        h, w = frame.shape[:2]
        l, t, r, b = SEPARATOR_BAND.rect(w, h)
        d = max(2, round(0.0028 * h))  # "just above/below" distance, ~4 px at 1440p
        gray = frame[max(0, t - d):b + d, l:r].astype(np.int16).mean(axis=2)
        rows = gray[d:-d]
        contrast = rows - np.maximum(gray[:-2 * d], gray[2 * d:])
        coverage = (contrast > SEPARATOR_CONTRAST).mean(axis=1)
        i = int(coverage.argmax())
        if coverage[i] < SEPARATOR_MIN_COVERAGE:
            return None
        y = t + i
        line = frame[y:y + 2, l:r].reshape(-1, 3).astype(np.int16)
        b_, g_, r_ = line.mean(axis=0)
        return y, bool(g_ - r_ >= TEAL_MIN_G_MINUS_R)

    def read(self, frame: np.ndarray) -> CardReading:
        sep = self.find_separator(frame)
        if sep is None:
            return CardReading()
        y, teal = sep
        h = frame.shape[0]
        y_rel = y / h
        map_roi = Roi(TEXT_X[0], y_rel - MAP_ABOVE[0], TEXT_X[1], y_rel - MAP_ABOVE[1])
        realm_roi = Roi(TEXT_X[0], y_rel + REALM_BELOW[0], TEXT_X[1], y_rel + REALM_BELOW[1])
        kernel = max(5, round(0.0105 * h) | 1)  # odd, > stroke width, scales with resolution
        map_text = ocr_line(isolate_text(map_roi.crop(frame), kernel=kernel))
        realm_text = ocr_line(isolate_text(realm_roi.crop(frame), REALM_MAX_SATURATION, kernel))
        match = resolve(map_text, realm_text, self.catalog)
        return CardReading(y, teal, map_text, realm_text, match)


class TitleCardTracker:
    """Combines per-frame readings into ONE MapDetected per match.

    The card is visible for a few seconds. Publish as soon as one frame is
    confident; otherwise keep the best partial result and publish it when the
    card disappears or `give_up` seconds pass. Then stay quiet for `cooldown`
    seconds so the same card isn't reported twice.
    """

    def __init__(self, cooldown: float = 90.0, give_up: float = 6.0, gone_after: float = 2.0) -> None:
        self.cooldown, self.give_up, self.gone_after = cooldown, give_up, gone_after
        self._quiet_until = float("-inf")
        self._reset()

    def _reset(self) -> None:
        self._since: float | None = None
        self._last_seen = 0.0
        self._best: MapMatch | None = None
        self._teal_frames = 0

    @property
    def pending(self) -> bool:
        """A card is being read; the caller should poll faster."""
        return self._since is not None

    def update(self, r: CardReading, now: float) -> list[Event]:
        if now < self._quiet_until:
            return []
        if r.present:
            if self._since is None:
                self._since = now
            self._last_seen = now
            self._teal_frames += r.teal
            if r.match and (self._best is None or _rank(r.match) > _rank(self._best)):
                self._best = r.match
            if (self._best and self._best.confident) or now - self._since >= self.give_up:
                return self._finish(now)
        elif self._since is not None and now - self._last_seen > self.gone_after:
            return self._finish(now)
        return []

    def _finish(self, now: float) -> list[Event]:
        best, teal = self._best, self._teal_frames
        self._reset()
        if best is None and teal < 2:
            # A line but no readable text and not teal: other UI (friends list).
            self._quiet_until = now + 10  # don't re-OCR it every frame
            return []
        self._quiet_until = now + self.cooldown
        if best is None:
            log.info("title card seen but unreadable")
            return [MatchStarted(), MapDetected(None, None, 0.0)]
        log.info("title card: %s / %s (%.2f)", best.realm, best.map, best.confidence)
        return [MatchStarted(), MapDetected(best.realm, best.map, best.confidence)]


def _rank(m: MapMatch) -> tuple[bool, float]:
    return (m.map is not None, m.confidence)
