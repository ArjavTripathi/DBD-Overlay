"""Match phase state machine. Pure logic: per-tick observations in, events out.

    IDLE ──title card──> MATCH ──end screen──> ENDED ──lobby / end screens gone──> IDLE

- Any red end-screen title ends the match, even if we missed its start.
- On the scoreboard, keep the best reading over several frames and publish
  once: immediately when complete, otherwise when the end screens go away.
- Seeing the lobby while still in MATCH means the match ended without end
  screens (disconnect, crash, quit): MatchEnded anyway.

Hatch inference (see egc.py): during MATCH, watch for the End Game Collapse.
If the match was watched from the title card to the end screen without gaps
and the EGC never appeared, every escape was through the hatch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from ..core.events import Event, KillerDetected, MatchEnded, RoleDetected, ScoreboardRead
from ..core.models import SurvivorOutcome
from .end_screen import EndKind, EndReading, ScoreboardReading

log = logging.getLogger(__name__)


class Phase(StrEnum):
    IDLE = "idle"
    MATCH = "match"
    ENDED = "ended"


# After a scoreboard was published, end screens seen again (you went back to
# the scoreboard, or it was hidden for a while) are the SAME match until a new
# one starts, the lobby shows up, or this long passes (no match is shorter).
SAME_MATCH_SECONDS = 180.0
EGC_MIN_FRAMES = 3      # consecutive sightings (it lasts a minute or more)
MAX_WATCH_GAP = 30.0    # s unwatched (game hidden) before we stop trusting "no EGC seen"


@dataclass(frozen=True)
class Observation:
    match_started: bool = False
    end: EndReading | None = None   # None = not checked this tick
    lobby: bool | None = None       # None = not checked this tick
    egc: bool | None = None         # None = not checked this tick


class MatchTracker:
    def __init__(self, end_gone_after: float = 30.0) -> None:
        self.end_gone_after = end_gone_after
        self.phase = Phase.IDLE
        self._best: ScoreboardReading | None = None
        self._board_published = False
        self._end_last_seen = 0.0
        self._result = ""
        self._watched_from_start = False
        self._last_watch = 0.0
        self._watch_gap = False
        self._egc_run = 0
        self._egc_seen = False
        self._published_at: float | None = None

    @property
    def wants_scoreboard(self) -> bool:
        return self.phase is Phase.ENDED and not self._board_published

    def update(self, o: Observation, now: float) -> list[Event]:
        events: list[Event] = []
        if o.match_started:
            self._enter_match(now)
        if self.phase is Phase.MATCH and o.egc is not None:
            self._watch(o.egc, now)

        if (o.end is not None and o.end.kind is not None and self.phase is Phase.IDLE
                and self._published_at is not None and now - self._published_at < SAME_MATCH_SECONDS):
            o = Observation(o.match_started, None, o.lobby, o.egc)  # same match's screens again: ignore
        if o.end is not None and o.end.kind is not None:
            self._end_last_seen = now
            if self.phase is not Phase.ENDED:
                if self.phase is Phase.MATCH:
                    if now - self._last_watch > MAX_WATCH_GAP:
                        self._watch_gap = True  # unwatched right before the end
                else:
                    self._watched_from_start = False  # never saw this match start
                log.info("match ended (%s: %s)", o.end.kind, o.end.title)
                self.phase = Phase.ENDED
                self._best, self._board_published, self._result = None, False, ""
                events.append(MatchEnded())
            if o.end.kind is EndKind.RESULT:
                self._result = o.end.title
            board = o.end.scoreboard
            if board is not None and not self._board_published:
                if self._best is None or board.score > self._best.score:
                    self._best = board
                if self._best.complete:
                    events += self._publish_board()
        elif self.phase is Phase.ENDED and now - self._end_last_seen > self.end_gone_after:
            events += self._leave_ended()

        if o.lobby:
            self._published_at = None  # back in the lobby: the next end screen is a new match
            if self.phase is Phase.MATCH:
                log.info("lobby seen during match: ended without end screens")
                events.append(MatchEnded())
                self.phase = Phase.IDLE
            elif self.phase is Phase.ENDED:
                events += self._leave_ended()
        return events

    def _enter_match(self, now: float) -> None:
        self.phase = Phase.MATCH
        self._published_at = None
        self._best, self._board_published = None, False
        self._watched_from_start, self._last_watch, self._watch_gap = True, now, False
        self._egc_run, self._egc_seen = 0, False

    def _watch(self, egc: bool, now: float) -> None:
        if now - self._last_watch > MAX_WATCH_GAP:
            self._watch_gap = True
        self._last_watch = now
        self._egc_run = self._egc_run + 1 if egc else 0
        if self._egc_run >= EGC_MIN_FRAMES and not self._egc_seen:
            log.info("End Game Collapse seen")
            self._egc_seen = True

    def hatch_used(self, statuses: tuple[SurvivorOutcome, ...]) -> bool | None:
        """Escapes through the hatch? None = can't tell."""
        if not statuses or SurvivorOutcome.ESCAPED not in statuses:
            return None
        if not self._watched_from_start or self._watch_gap or self._egc_seen:
            return None  # didn't see everything, or gates were open (both routes possible)
        return True

    def _leave_ended(self) -> list[Event]:
        events = [] if self._board_published or self._best is None else self._publish_board()
        self.phase = Phase.IDLE
        return events

    def _publish_board(self) -> list[Event]:
        b = self._best
        assert b is not None
        self._board_published = True
        self._published_at = self._end_last_seen
        log.info("scoreboard: killer=%s role=%s (own name %r, row %s)", b.killer, b.role, b.own_name, b.my_row)
        events: list[Event] = [ScoreboardRead(b.killer, b.role, b.my_row, b.killer_row, b.own_name, b.rows,
                                                self._result, b.statuses, self.hatch_used(b.statuses))]
        if b.killer:
            events.append(KillerDetected(b.killer, 1.0, source="scoreboard"))
        if b.role:
            events.append(RoleDetected(b.role, source="scoreboard"))
        return events
