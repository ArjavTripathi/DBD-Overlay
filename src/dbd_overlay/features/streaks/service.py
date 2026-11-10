"""Recording results and computing streaks. No Qt: tested with an in-memory DB."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ...core.events import ScoreboardRead
from ...core.models import ManualOutcome, MatchResult, Role, SurvivorOutcome as S, Verdict
from ...storage.db import Database
from .rules import Rules
from .stats import StreakStats, compute

log = logging.getLogger(__name__)

# A win/loss hotkey within this long after an AUTO-recorded match applies to
# that match (fill in "win or loss?" or correct the verdict), once. Otherwise
# it records a new manual match (pressing twice = two matches; undo fixes).
AMEND_WINDOW = timedelta(minutes=10)

# Survivor result banner -> your outcome. Unknown text stays UNKNOWN.
BANNER_OUTCOMES = (
    ("ESCAP", S.ESCAPED),
    ("SACRIFIC", S.KILLED),
    ("KILLED", S.KILLED),
    ("BLED", S.KILLED),
    ("DIED", S.KILLED),
    ("DISCONNECT", S.DISCONNECTED),
)


def banner_outcome(text: str) -> S:
    t = text.upper()
    return next((o for word, o in BANNER_OUTCOMES if word in t), S.UNKNOWN)


def _manual_verdict(o: ManualOutcome) -> Verdict:
    return Verdict.WIN if o is ManualOutcome.WIN else Verdict.LOSS


class StreakService:
    def __init__(self, db: Database, rules: Rules, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.db, self.rules, self._now = db, rules, now
        self._undo: list[tuple[str, Callable[[], None]]] = []

    # -- recording -------------------------------------------------------------

    def match_from_board(self, b: ScoreboardRead, my_killer: str | None,
                         map_: str | None, realm: str | None) -> MatchResult | None:
        """Raw facts from the scoreboard (+ result banner). None if the role is unknown."""
        if b.role is None:
            return None
        if b.survivors:
            survivors = list(b.survivors)
        else:
            n = len(b.rows) - (b.killer_row is not None) if b.rows else 4
            survivors = [S.UNKNOWN] * max(n, 0)
        my_index = None
        if b.role is Role.SURVIVOR and b.my_row is not None:
            # Survivor rows are the scoreboard rows minus the killer row.
            my_index = b.my_row - (b.killer_row is not None and b.my_row > b.killer_row)
            # Your own result banner is the most direct source for your outcome.
            if 0 <= my_index < len(survivors) and (own := banner_outcome(b.result)) is not S.UNKNOWN:
                survivors[my_index] = own
        killer = b.killer if b.role is Role.SURVIVOR else (b.killer or my_killer)
        return MatchResult(b.role, killer, realm, map_, tuple(survivors), my_index, hatch_used=b.hatch_used,
                           source="auto", ts=self._now(), notes=b.result)

    def record(self, m: MatchResult) -> MatchResult:
        # Counts toward the streak only if that streak is switched on right now.
        m = replace(m, verdict=self.rules.evaluate(m), counted=self.db.streak_active(m.category))
        mid = self.db.add_match(m)
        m.id = mid
        self._push(f"record {m.category}", lambda: self.db.delete_match(mid))
        log.info("recorded match %d: %s %s -> %s", mid, m.category, m.map, m.verdict)
        return m

    def win_or_loss(self, outcome: ManualOutcome, role: Role | None, my_killer: str | None) -> str:
        last = self.db.last_match()
        if (last is not None and last.source == "auto" and last.manual_outcome is None
                and not last.ignored and self._now() - last.ts < AMEND_WINDOW):
            old_verdict, old_manual = last.verdict, last.manual_outcome
            self.db.set_verdict(last.id, _manual_verdict(outcome), outcome)
            self._push(f"set {outcome} on match {last.id}",
                       lambda: self.db.set_verdict(last.id, old_verdict, old_manual))
            return f"{outcome} ({last.category.removeprefix('killer:')}, last match)"
        if role is None:
            raise ValueError("role unknown: play a match first, or `ctl set-role killer|survivor`")
        if role is Role.KILLER and not my_killer:
            raise ValueError("which killer? use `ctl set-killer <name>` first")
        m = self.record(MatchResult(role, killer=my_killer if role is Role.KILLER else None,
                                    manual_outcome=outcome, source="manual", ts=self._now()))
        off = "" if m.counted else "; streak is off, not counted (streak-toggle)"
        return f"{outcome} ({m.category.removeprefix('killer:')}, new match{off})"

    def ignore_last(self) -> str:
        last = self.db.last_match()
        if last is None:
            raise ValueError("no matches recorded yet")
        self.db.set_ignored(last.id, not last.ignored)
        self._push(f"ignore match {last.id}", lambda: self.db.set_ignored(last.id, last.ignored))
        return "ignored" if not last.ignored else "un-ignored"

    # -- streak on/off -------------------------------------------------------

    def is_active(self, category: str) -> bool:
        return self.db.streak_active(category)

    def set_active(self, category: str, active: bool) -> None:
        was = self.db.streak_active(category)
        if was == active:
            return
        self.db.set_streak_active(category, active)
        self._push(f"switch {category} {'on' if active else 'off'}",
                   lambda: self.db.set_streak_active(category, was))

    def toggle(self, category: str) -> str:
        """Switch a streak on/off. Switching ON right after a match of that
        streak (within AMEND_WINDOW) also counts that match: you forgot to
        turn it on before playing."""
        active = not self.db.streak_active(category)
        name = category.removeprefix("killer:")
        self.db.set_streak_active(category, active)
        late = None
        last = self.db.last_match()
        if (active and last is not None and last.category == category and not last.counted
                and not last.ignored and self._now() - last.ts < AMEND_WINDOW):
            late = last.id
            self.db.set_counted(late, True)

        def undo() -> None:
            self.db.set_streak_active(category, not active)
            if late is not None:
                self.db.set_counted(late, False)

        self._push(f"switch {name} {'on' if active else 'off'}", undo)
        if not active:
            return f"{name} streak off"
        return f"{name} streak on" + (" (counting the match you just played)" if late else "")

    def streaks(self) -> list[tuple[str, bool, StreakStats]]:
        """Every known streak: (category, on?, stats), survivor first, then by name."""
        states = self.db.streak_states()
        order = sorted(states, key=lambda c: (c != "survivor", c))
        return [(c, states[c], self.stats(c)) for c in order]

    def reset(self, category: str) -> str:
        self.db.add_reset(category, self._now())
        self._push(f"reset {category}", lambda: self.db.delete_last_reset(category))
        return f"reset {category.removeprefix('killer:')}"

    def recompute_all(self) -> int:
        """Apply the current rules to the whole history. Returns how many changed."""
        changed = []
        for m in self.db.matches():
            v = self.rules.evaluate(m)
            if v is not m.verdict:
                changed.append((m.id, m.verdict, m.manual_outcome))
                self.db.set_verdict(m.id, v, m.manual_outcome)

        def restore() -> None:
            for mid, v, manual in changed:
                self.db.set_verdict(mid, v, manual)

        if changed:
            self._push(f"recompute {len(changed)} matches", restore)
        return len(changed)

    def undo(self) -> str:
        if not self._undo:
            raise ValueError("nothing to undo")
        what, fn = self._undo.pop()
        fn()
        return f"undid: {what}"

    def _push(self, what: str, fn: Callable[[], None]) -> None:
        self._undo.append((what, fn))
        del self._undo[:-50]  # bounded

    # -- reading ---------------------------------------------------------------

    def stats(self, category: str) -> StreakStats:
        return compute(self.db.matches(category), self.db.last_reset(category))

    def last_match(self) -> MatchResult | None:
        return self.db.last_match()
