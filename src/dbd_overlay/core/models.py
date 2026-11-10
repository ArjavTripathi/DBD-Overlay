"""Plain data types shared by every layer. No I/O, no Qt."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Role(StrEnum):
    SURVIVOR = "survivor"
    KILLER = "killer"


class SurvivorOutcome(StrEnum):
    """What the scoreboard says about one survivor.

    Hatch and gate escapes share the same scoreboard icon, so the escape
    *method* is stored separately (MatchResult.hatch_used).
    """

    ESCAPED = "escaped"
    KILLED = "killed"            # sacrificed, mori'd, bled out: all the same skull icon
    SURRENDERED = "surrendered"  # flag icon; always counts as a kill
    DISCONNECTED = "disconnected"
    # Person silhouette: still playing when YOU left the trial (you died and
    # left early), so their final outcome is not known. Rules treat it as unknown.
    ALIVE = "alive"
    UNKNOWN = "unknown"          # detector wasn't sure


class ManualOutcome(StrEnum):
    """A win/loss the user recorded by hotkey without per-survivor facts."""

    WIN = "win"
    LOSS = "loss"


class Verdict(StrEnum):
    """A match judged by the win rules. UNKNOWN = facts missing (ask the user)."""

    WIN = "win"
    LOSS = "loss"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Map:
    realm: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Killer:
    name: str  # canonical, e.g. "The Trapper"
    aliases: tuple[str, ...] = ()


SURVIVOR_CATEGORY = "survivor"


def killer_category(killer: str | None) -> str:
    return f"killer:{killer or 'unknown'}"


@dataclass
class MatchResult:
    """Raw facts about one match. Streaks are *derived* from these plus the
    current win rules, so changing a rule never loses information."""

    role: Role
    killer: str | None = None
    realm: str | None = None
    map: str | None = None
    # One entry per survivor row on the scoreboard (normally 4).
    survivors: tuple[SurvivorOutcome, ...] = ()
    # Survivor role only: which entry in `survivors` is you.
    my_index: int | None = None
    hatch_used: bool | None = None  # None = unknown
    manual_outcome: ManualOutcome | None = None
    source: str = "auto"  # "auto" | "manual"
    ignored: bool = False
    notes: str = ""
    # Verdict under the rules active when it was recorded (or recomputed).
    verdict: Verdict = Verdict.UNKNOWN
    # Was this streak switched on when the match was played? Off = kept in the
    # history but doesn't affect the streak (like a pause).
    counted: bool = True
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None

    @property
    def category(self) -> str:
        """Which streak this match belongs to."""
        return SURVIVOR_CATEGORY if self.role is Role.SURVIVOR else killer_category(self.killer)
