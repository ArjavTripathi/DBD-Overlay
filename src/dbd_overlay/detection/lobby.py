"""Lobby: is it on screen, and are you queueing as killer or survivor?

Measured at 2560x1440 (see tests/fixtures/screens):

  * The big button bottom-right says PLAY / READY / UNREADY / CANCEL only in
    lobbies (the scoreboard says CONTINUE, the in-match menu QUIT).
  * Killer lobbies print your killer under that button once you queue or
    ready up ('THE HILLBILLY   1:04  EST. 2:27'). Survivor lobbies show only
    the timer there.
  * Any lobby sub-page (characters, loadout...) shows the selected character
    top-left: 'THE SLASHER / CHARACTERS'. Catches killers before queueing.

So: killer name seen -> killer (+ which one). Queueing/ready with nothing
written under the button -> survivor. PLAY with nothing else -> can't tell.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from rapidfuzz import fuzz

from ..core.events import LobbyChanged
from ..core.models import Killer, Role
from .end_screen import grey_text
from .roi import Roi
from .text import best_match, norm, ocr_line

# Text part of the button only (its claw logo confuses Tesseract).
LOBBY_BUTTON = Roi(0.30, 0.880, 0.49, 0.930, anchor="right")
# Under the button; stops before the timer.
SUBTITLE = Roi(0.215, 0.938, 0.50, 0.968, anchor="right")
# Character name top-left, right of the prestige badge.
HEADER = Roi(0.345, 0.040, 0.85, 0.069)

BUTTON_WORDS = ("PLAY", "READY", "UNREADY", "CANCEL")
QUEUED_WORDS = ("READY", "UNREADY", "CANCEL")
BUTTON_MIN = 70      # per-word similarity; a highlighted CANCEL reads 'CANEH', 'SANSEL'
KILLER_MIN = 85


@dataclass(frozen=True)
class LobbyReading:
    button: str | None = None       # PLAY / READY / UNREADY / CANCEL, None = not a lobby
    killer: str | None = None       # your killer, if the lobby shows it
    subtitle: str = ""              # raw text under the button (for debugging)

    @property
    def visible(self) -> bool:
        return self.button is not None

    @property
    def role(self) -> Role | None:
        if self.killer:
            return Role.KILLER
        if self.button in QUEUED_WORDS and not _has_words(self.subtitle):
            return Role.SURVIVOR
        return None


def _has_words(text: str) -> bool:
    """Anything that looks like a name (not just the timer / 'EST.')."""
    return any(len(w) >= 3 and w.isalpha() and w != "EST" for w in text.split())


def _clean(binary: np.ndarray) -> np.ndarray:
    """Keep only letter-sized blobs that don't touch the crop border. Edge
    junk from the 3D scene makes Tesseract's single-line mode return nothing."""
    ink = (binary == 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    H, W = binary.shape
    out = np.full_like(binary, 255)
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if x == 0 or y == 0 or x + w >= W or y + h >= H or h < 0.3 * H:
            continue
        out[labels == i] = 0
    return out


def read_button(frame: np.ndarray) -> str | None:
    h = frame.shape[0]
    words = norm(ocr_line(_clean(grey_text(LOBBY_BUTTON.crop(frame), h, max_saturation=90)))).split()
    best, score = None, 0.0
    for w in words:
        if len(w) < 4:
            continue
        for bw in BUTTON_WORDS:
            s = fuzz.ratio(w, bw)
            if s > score:
                best, score = bw, s
    return best if score >= BUTTON_MIN else None


class LobbyReader:
    def __init__(self, killers: tuple[Killer, ...]) -> None:
        self.killers = killers

    def _killer(self, text: str) -> str | None:
        # Canonical names only: aliases like 'Art' would hit random text.
        k, score, _ = best_match(text, self.killers, lambda k: (k.name,))
        return k.name if k is not None and score >= KILLER_MIN else None

    def read(self, frame: np.ndarray) -> LobbyReading:
        button = read_button(frame)
        if button is None:
            return LobbyReading()
        h = frame.shape[0]
        sub = norm(ocr_line(grey_text(SUBTITLE.crop(frame), h, max_saturation=60)))
        killer = self._killer(sub)
        if killer is None:
            header = norm(ocr_line(grey_text(HEADER.crop(frame), h, max_saturation=60)))
            killer = self._killer(header)
        return LobbyReading(button, killer, sub)


class LobbyRoleTracker:
    """Turns readings into RoleDetected/KillerDetected-worthy changes.

    Killer names are unambiguous: accepted at once. 'Survivor' is inferred
    from something missing, so it needs two readings in a row."""

    SURVIVOR_VOTES = 2

    def __init__(self) -> None:
        self.role: Role | None = None
        self.killer: str | None = None
        self._survivor_votes = 0

    def update(self, r: LobbyReading) -> tuple[Role | None, str | None]:
        """Returns (new role, new killer); None for whatever didn't change."""
        role = r.role
        if role is Role.SURVIVOR:
            self._survivor_votes += 1
            if self._survivor_votes < self.SURVIVOR_VOTES:
                role = None
        else:
            self._survivor_votes = 0
        new_role = role if role is not None and role is not self.role else None
        new_killer = r.killer if r.killer and r.killer != self.killer else None
        if role is not None:
            self.role = role
        if r.killer:
            self.killer = r.killer
        return new_role, new_killer


class LobbyVisibilityTracker:
    """Edges of 'lobby on screen' as LobbyChanged events (for Discord status).

    Showing up is trusted at once (the button OCR is strict); going away needs
    HIDE_AFTER misses in a row, so one bad read doesn't flicker."""

    HIDE_AFTER = 2

    def __init__(self) -> None:
        self.visible = False
        self.button: str | None = None
        self._misses = 0

    def update(self, r: LobbyReading) -> LobbyChanged | None:
        if r.visible:
            self._misses = 0
            if self.visible and r.button == self.button:
                return None
            self.visible, self.button = True, r.button
            return LobbyChanged(True, r.button)
        if not self.visible:
            return None
        self._misses += 1
        if self._misses < self.HIDE_AFTER:
            return None
        self.visible = False
        return LobbyChanged(False, self.button)
