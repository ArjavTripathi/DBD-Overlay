"""Streak numbers, computed from the match list every time (never stored).

    current  consecutive wins at the end, counted since the last manual reset
    attempt  streamer style: "Attempt #N" = losses since reset + 1
    best     longest win run ever (resets don't erase records)

Ignored matches and matches played while the streak was switched off are
skipped entirely. UNKNOWN verdicts (waiting for the user) are skipped too,
and counted as `pending`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...core.models import MatchResult, Verdict


@dataclass(frozen=True)
class StreakStats:
    current: int = 0
    attempt: int = 1
    best: int = 0
    wins: int = 0
    losses: int = 0
    pending: int = 0


def compute(matches: list[MatchResult], reset_at: datetime | None = None) -> StreakStats:
    """`matches` must be one category, in chronological order."""
    best = run = 0
    current = wins = losses = pending = 0
    for m in matches:
        if m.ignored or not m.counted:
            continue
        after_reset = reset_at is None or m.ts > reset_at
        if m.verdict is Verdict.UNKNOWN:
            pending += after_reset
            continue
        win = m.verdict is Verdict.WIN
        run = run + 1 if win else 0
        best = max(best, run)
        if after_reset:
            current = current + 1 if win else 0
            wins += win
            losses += not win
    return StreakStats(current=current, attempt=losses + 1, best=best, wins=wins, losses=losses, pending=pending)
