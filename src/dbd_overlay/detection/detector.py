"""All frame readers + trackers behind one call. No capture, no threads, so
the live service and offline replay run exactly the same logic.

Capture planning: most ticks only need a few small strips (see plan()); the
full frame is grabbed only while an end screen is up (scoreboard parsing).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.catalog import MapCatalog
from ..core.events import Event, MatchStarted
from ..core.models import Killer
from . import egc
from .end_screen import LOBBY_BUTTON, TITLE, EndReading, EndScreenReader, lobby_button_visible
from .map_detector import CardReading, TitleCardReader, TitleCardTracker
from .match_tracker import MatchTracker, Observation, Phase
from .roi import Roi

# Lobby OCR (~70 ms) only matters for matches that end without end screens.
LOBBY_CHECK_SECONDS = 10.0


@dataclass
class TickResult:
    events: list[Event] = field(default_factory=list)
    card: CardReading = field(default_factory=CardReading)
    end: EndReading | None = None
    lobby: bool | None = None
    egc: bool | None = None


class MatchDetector:
    def __init__(self, catalog: MapCatalog, killers: tuple[Killer, ...], exhaustive: bool = False) -> None:
        """exhaustive: read everything on every frame (replay checks); live
        mode skips work the trackers no longer need."""
        self.exhaustive = exhaustive
        self.cards = TitleCardReader(catalog)
        self.card_tracker = TitleCardTracker()
        self.ends = EndScreenReader(killers)
        self.tracker = MatchTracker()
        self._end_visible = False
        self._last_lobby_check = float("-inf")

    @property
    def busy(self) -> bool:
        """Something is on screen that should be polled quickly."""
        return self.card_tracker.pending or self._end_visible

    def plan(self, now: float) -> list[Roi] | None:
        """Regions to capture this tick; None = the full frame."""
        if self._end_visible and self.tracker.wants_scoreboard:
            return None
        rois = [TITLE]
        if self.tracker.phase is not Phase.ENDED:
            rois.append(TitleCardReader.CAPTURE)
        if self.tracker.phase is Phase.MATCH:
            rois.append(egc.CAPTURE)
        if self.tracker.phase is not Phase.IDLE and now - self._last_lobby_check >= LOBBY_CHECK_SECONDS:
            rois.append(LOBBY_BUTTON)
        return rois

    def process(self, frame: np.ndarray, now: float, captured: list[Roi] | None = None) -> TickResult:
        """Run the readers whose regions were captured (None = everything)."""
        full = captured is None
        r = TickResult()

        if full or TitleCardReader.CAPTURE in captured:
            r.card = self.cards.read(frame)
            r.events += self.card_tracker.update(r.card, now)

        r.end = self.ends.read(frame, parse_scoreboard=full and (self.exhaustive or self.tracker.wants_scoreboard))
        self._end_visible = r.end.kind is not None

        if full or LOBBY_BUTTON in captured:
            self._last_lobby_check = now
            r.lobby = lobby_button_visible(frame)

        if full or egc.CAPTURE in captured:
            r.egc = egc.egc_visible(frame)

        started = any(isinstance(e, MatchStarted) for e in r.events)
        r.events += self.tracker.update(Observation(started, r.end, r.lobby, r.egc), now)
        return r
