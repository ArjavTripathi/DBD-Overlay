"""End-of-match screens: result banner, bloodpoints, scoreboard.

All three show a big red title top-left (measured at 2560x1440):
    'BRUTAL KILLER'       (result banner, y ~0.24-0.28 h)
    'BLOODPOINTS EARNED'  (y ~0.126-0.151 h)
    'SCOREBOARD'          (y ~0.126-0.151 h)
Gameplay frames have ~0 pure-red pixels there, so counting them is a free
gate; OCR only runs when the gate opens.

The scoreboard has 4 survivor rows + the killer row (always red-highlighted,
for everyone). Each row's top line is 'CHARACTER NAME  player name'. Your own
player name is shown top-right under the currencies, so:
    killer   = the row whose character name is a killer
    your row = the row containing your player name
    role     = killer if your row is the killer row, else survivor
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np
import pytesseract

from ..core.models import Killer, Role, SurvivorOutcome
from .roi import Roi
from .status_icons import classify, icon_roi
from .text import best_match, match_score, norm, ocr_line

log = logging.getLogger(__name__)

# Includes the small white 'MATCH' / 'MATCH RESULT' label above each title.
TITLE = Roi(0.06, 0.09, 0.55, 0.29)
# Real titles cover 3-10% of the box. Gameplay is ~0%, but red walls/panels
# in some maps cover 20%+: reject those before spending any OCR.
TITLE_MIN_RED_FRACTION = 0.015
TITLE_MAX_RED_FRACTION = 0.15

OWN_NAME = Roi(0.18, 0.075, 0.42, 0.105, anchor="right")
ROW_FIRST_Y = 0.247              # centre of row 1's name line
ROW_PITCH = 0.1115
ROW_HALF_HEIGHT = 0.016
ROW_X = (0.17, 0.72)
ROW_COUNT = 5

KILLER_MIN = 85
OWN_NAME_MIN = 80
OWN_NAME_MARGIN = 10


class EndKind(StrEnum):
    RESULT = "result"            # 'BRUTAL KILLER', 'ESCAPED', ...
    BLOODPOINTS = "bloodpoints"
    SCOREBOARD = "scoreboard"


def row_roi(i: int) -> Roi:
    y = ROW_FIRST_Y + i * ROW_PITCH
    return Roi(ROW_X[0], y - ROW_HALF_HEIGHT, ROW_X[1], y + ROW_HALF_HEIGHT)


SCOREBOARD_ROIS = (OWN_NAME, *(row_roi(i) for i in range(ROW_COUNT)))


@dataclass(frozen=True)
class ScoreboardReading:
    rows: tuple[str, ...]
    own_name: str
    killer: str | None
    killer_row: int | None
    my_row: int | None
    statuses: tuple[SurvivorOutcome, ...] = ()  # survivor rows only, top to bottom

    @property
    def role(self) -> Role | None:
        if self.my_row is None or self.killer_row is None:
            return None
        return Role.KILLER if self.my_row == self.killer_row else Role.SURVIVOR

    @property
    def complete(self) -> bool:
        return self.killer is not None and self.role is not None

    @property
    def score(self) -> int:
        """How much was recognised; used to keep the best of several frames."""
        known = sum(st is not SurvivorOutcome.UNKNOWN for st in self.statuses)
        return 10 * ((self.killer is not None) + (self.my_row is not None) + (self.role is not None)) + known


@dataclass(frozen=True)
class EndReading:
    kind: EndKind | None = None   # None = no end screen
    title: str = ""
    scoreboard: ScoreboardReading | None = None


def strip_edge_junk(text: str) -> str:
    """'N SPEEDY' -> 'SPEEDY': drop 1-character tokens at either end
    (OCR'd specks from the crop border). Inner tokens are kept."""
    tokens = text.split()
    while tokens and len(tokens[0]) == 1:
        tokens.pop(0)
    while tokens and len(tokens[-1]) == 1:
        tokens.pop()
    return " ".join(tokens)


def looks_like_title(text: str) -> bool:
    """Real titles contain a proper word (SCOREBOARD, BRUTAL KILLER, ESCAPED...).
    Red auras seen through walls OCR as specks like '1 AL M I E 4'."""
    return any(len(w) >= 5 and w.isalpha() for w in text.split())


def _red_mask(crop: np.ndarray) -> np.ndarray:
    b, g, r = (crop[..., i].astype(np.int16) for i in range(3))
    return (r > 150) & (g < 80) & (b < 80)


def _grey_text(crop: np.ndarray, height: int, max_saturation: int = 70) -> np.ndarray:
    """Light, neutral-coloured text (white names AND dimmer grey player names).

    Like text.isolate_text but with a fixed threshold: Otsu would split the
    bright character name from the dim player name and drop the latter.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    k = max(9, round(0.0215 * height) | 1)  # 31 px at 1440p
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    th[cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1] > max_saturation] = 0
    th = cv2.resize(th, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return 255 - cv2.threshold(th, 25, 255, cv2.THRESH_BINARY)[1]


class EndScreenReader:
    def __init__(self, killers: tuple[Killer, ...]) -> None:
        self.killers = killers

    def title_present(self, frame: np.ndarray) -> bool:
        """Cheap gate: the right amount of pure red in the title box."""
        return TITLE_MIN_RED_FRACTION <= float(_red_mask(TITLE.crop(frame)).mean()) <= TITLE_MAX_RED_FRACTION

    def read(self, frame: np.ndarray, parse_scoreboard: bool = True) -> EndReading:
        if not self.title_present(frame):
            return EndReading()
        crop = TITLE.crop(frame)
        # Structural check: every end screen has a small white 'MATCH' label
        # above the red title. Red auras and painted walls don't.
        label = norm(pytesseract.image_to_string(_grey_text(crop, frame.shape[0], 60), config="--psm 6"))
        if "MATCH" not in label.split():
            return EndReading()
        mask = cv2.resize(_red_mask(crop).astype(np.uint8) * 255, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        title = norm(pytesseract.image_to_string(255 - mask, config="--psm 6"))
        if not looks_like_title(title):
            return EndReading()  # red but not text: killer auras, blood
        if match_score("SCOREBOARD", title) >= 80:
            kind = EndKind.SCOREBOARD
        elif match_score("BLOODPOINTS", title) >= 80:
            kind = EndKind.BLOODPOINTS
        elif title:
            kind = EndKind.RESULT
        else:
            return EndReading()
        board = self.read_scoreboard(frame) if kind is EndKind.SCOREBOARD and parse_scoreboard else None
        return EndReading(kind, title, board)

    def read_scoreboard(self, frame: np.ndarray) -> ScoreboardReading:
        h = frame.shape[0]
        own = strip_edge_junk(norm(ocr_line(_grey_text(OWN_NAME.crop(frame), h))))
        rows = tuple(norm(ocr_line(_grey_text(row_roi(i).crop(frame), h))) for i in range(ROW_COUNT))

        killer, killer_row, best = None, None, 0.0
        for i, text in enumerate(rows):
            k, score, _ = best_match(text, self.killers, lambda k: (k.name, *k.aliases))
            if k is not None and score >= KILLER_MIN and score > best:
                killer, killer_row, best = k.name, i, score

        my_row = None
        if own:
            scores = sorted(((match_score(own, t), i) for i, t in enumerate(rows)), reverse=True)
            top, i = scores[0]
            runner = scores[1][0] if len(scores) > 1 else 0
            if top >= OWN_NAME_MIN and top - runner >= OWN_NAME_MARGIN:
                my_row = i

        # Survivor rows = every row but the killer's (the last one if unknown).
        survivor_rows = [i for i in range(ROW_COUNT) if i != (killer_row if killer_row is not None else ROW_COUNT - 1)]
        statuses = tuple(classify(icon_roi(ROW_FIRST_Y + i * ROW_PITCH).crop(frame))[0] for i in survivor_rows)
        return ScoreboardReading(rows, own, killer, killer_row, my_row, statuses)


# -- lobby -------------------------------------------------------------------

# Only the label part of the button: the claw logo on its right confuses Tesseract.
LOBBY_BUTTON = Roi(0.30, 0.87, 0.49, 0.94, anchor="right")
LOBBY_WORDS = ("PLAY", "READY", "UNREADY", "CANCEL")


def lobby_button_visible(frame: np.ndarray) -> bool:
    """The big PLAY / READY / CANCEL button bottom-right exists only in lobbies.
    (Scoreboard says CONTINUE, the in-match menu says QUIT.)"""
    h = frame.shape[0]
    words = norm(ocr_line(_grey_text(LOBBY_BUTTON.crop(frame), h, max_saturation=90))).split()
    # Allow a couple of junk letters glued on ('PLAYL').
    return any(w.startswith(lw) and len(w) <= len(lw) + 2 for w in words for lw in LOBBY_WORDS)
