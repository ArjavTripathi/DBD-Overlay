"""All frame readers + trackers behind one call. No capture, no threads, so
the live service and offline replay run exactly the same logic.

Capture planning: most ticks only need a few small strips (see plan()); the
full frame is grabbed only while an end screen is up (scoreboard parsing).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.catalog import MapCatalog
from ..core.events import Event, KillerDetected, MatchStarted, RoleDetected
from ..core.models import Killer
from . import egc
from .end_screen import TITLE, EndReading, EndScreenReader
from .lobby import (HEADER, LOBBY_BUTTON, SUBTITLE, LobbyReader, LobbyReading, LobbyRoleTracker,
                    LobbyVisibilityTracker)
from .map_detector import CardReading, TitleCardReader, TitleCardTracker
from .match_tracker import MatchTracker, Observation, Phase
from .roi import Roi

# Lobby OCR (~30 ms for the button; the rest only when it's there).
# Between matches it tells killer from survivor, so check often; during a
# match it only catches matches that end without end screens.
LOBBY_CHECK_SECONDS = 4.0
LOBBY_CHECK_SECONDS_IN_MATCH = 10.0
LOBBY_ROIS = (LOBBY_BUTTON, SUBTITLE, HEADER)


@dataclass
class TickResult:
    events: list[Event] = field(default_factory=list)
    card: CardReading = field(default_factory=CardReading)
    end: EndReading | None = None
    lobby: bool | None = None
    lobby_reading: LobbyReading | None = None
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
        self.lobbies = LobbyReader(killers)
        self.lobby_roles = LobbyRoleTracker()
        self.lobby_seen = LobbyVisibilityTracker()
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
        every = LOBBY_CHECK_SECONDS_IN_MATCH if self.tracker.phase is Phase.MATCH else LOBBY_CHECK_SECONDS
        if now - self._last_lobby_check >= every:
            rois.extend(LOBBY_ROIS)
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
            r.lobby_reading = self.lobbies.read(frame)
            r.lobby = r.lobby_reading.visible
            role, killer = self.lobby_roles.update(r.lobby_reading)
            if killer:  # killer first, so the role change already has it
                r.events.append(KillerDetected(killer, 1.0, source="lobby"))
            if role:
                r.events.append(RoleDetected(role, source="lobby"))
            if (changed := self.lobby_seen.update(r.lobby_reading)) is not None:
                r.events.append(changed)

        if full or egc.CAPTURE in captured:
            r.egc = egc.egc_visible(frame)

        started = any(isinstance(e, MatchStarted) for e in r.events)
        r.events += self.tracker.update(Observation(started, r.end, r.lobby, r.egc), now)
        return r
