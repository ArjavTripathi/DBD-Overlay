"""Win conditions. Pure functions over the raw match facts.

Killer: a win needs `required` survivors *removed*. Killed/sacrificed and
surrendered always count; DCs count if `count_dc`; a hatch escape counts if
`count_hatch`. So the presets are:
    4k        required=4
    3k_hatch  required=4, count_hatch   (3 kills + the last one took hatch = win; gate = loss)
    3k_any    required=3                (the 4th may escape any way)

Survivor: `self_escape` (you must escape) and `min_escapes` (survivors out
in total, including you):
    i_escape  self_escape, min 1
    3_out     min 3  (SWF: three of you got out, whoever)
    4_out     min 4

Anything not knowable from the facts gives Verdict.UNKNOWN; never a guess.
A manual win/loss always wins over the facts.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.config import StreakConfig
from ...core.models import ManualOutcome, MatchResult, Role, SurvivorOutcome as S, Verdict


def _manual(m: MatchResult) -> Verdict | None:
    if m.manual_outcome is ManualOutcome.WIN:
        return Verdict.WIN
    if m.manual_outcome is ManualOutcome.LOSS:
        return Verdict.LOSS
    return None


@dataclass(frozen=True)
class KillerRule:
    required: int = 4
    count_hatch: bool = False
    count_dc: bool = True

    def _verdict(self, outs: tuple[S, ...], hatch: bool | None) -> Verdict:
        """Verdict when every outcome is known."""
        removed = sum(o in (S.KILLED, S.SURRENDERED) or (o is S.DISCONNECTED and self.count_dc) for o in outs)
        if removed >= self.required:
            return Verdict.WIN
        escaped = outs.count(S.ESCAPED)
        # One survivor short, and that one escaped: it's down to how they left.
        if self.count_hatch and escaped == 1 and removed + 1 >= self.required:
            if hatch is None:
                return Verdict.UNKNOWN  # hatch and gate look the same on the scoreboard
            return Verdict.WIN if hatch else Verdict.LOSS
        return Verdict.LOSS

    def evaluate(self, m: MatchResult) -> Verdict:
        if (v := _manual(m)) is not None:
            return v
        outs = m.survivors
        if not outs:
            return Verdict.UNKNOWN
        unknown = [i for i, o in enumerate(outs) if o in (S.UNKNOWN, S.ALIVE)]
        if not unknown:
            return self._verdict(outs, m.hatch_used)
        # Some icons unread: decide anyway if the answer is the same whatever
        # they were (best case: all killed; worst case: all escaped).
        best = tuple(S.KILLED if i in unknown else o for i, o in enumerate(outs))
        worst = tuple(S.ESCAPED if i in unknown else o for i, o in enumerate(outs))
        vb, vw = self._verdict(best, m.hatch_used), self._verdict(worst, m.hatch_used)
        return vb if vb is vw and vb is not Verdict.UNKNOWN else Verdict.UNKNOWN


@dataclass(frozen=True)
class SurvivorRule:
    self_escape: bool = True
    min_escapes: int = 1

    def evaluate(self, m: MatchResult) -> Verdict:
        if (v := _manual(m)) is not None:
            return v
        outs = m.survivors
        if self.self_escape:
            if m.my_index is None or m.my_index >= len(outs) or outs[m.my_index] in (S.UNKNOWN, S.ALIVE):
                return Verdict.UNKNOWN
            if outs[m.my_index] is not S.ESCAPED:
                return Verdict.LOSS
        escaped, unknown = outs.count(S.ESCAPED), outs.count(S.UNKNOWN) + outs.count(S.ALIVE)
        if escaped >= self.min_escapes:
            return Verdict.WIN
        if escaped + unknown >= self.min_escapes:
            return Verdict.UNKNOWN  # could still be a win depending on the unknowns
        return Verdict.LOSS


KILLER_PRESETS = {
    "4k": lambda dc: KillerRule(4, count_hatch=False, count_dc=dc),
    "3k_hatch": lambda dc: KillerRule(4, count_hatch=True, count_dc=dc),
    "3k_any": lambda dc: KillerRule(3, count_hatch=False, count_dc=dc),
}
SURVIVOR_PRESETS = {
    "i_escape": SurvivorRule(self_escape=True, min_escapes=1),
    "3_out": SurvivorRule(self_escape=False, min_escapes=3),
    "4_out": SurvivorRule(self_escape=False, min_escapes=4),
}


@dataclass(frozen=True)
class Rules:
    killer: KillerRule
    survivor: SurvivorRule

    def evaluate(self, m: MatchResult) -> Verdict:
        return (self.killer if m.role is Role.KILLER else self.survivor).evaluate(m)

    @staticmethod
    def from_config(c: StreakConfig) -> Rules:
        if c.killer_preset == "custom":
            killer = KillerRule(c.custom_killer_required, c.custom_killer_count_hatch, c.dc_counts_as_kill)
        else:
            killer = KILLER_PRESETS[c.killer_preset](c.dc_counts_as_kill)
        if c.survivor_preset == "custom":
            survivor = SurvivorRule(c.custom_survivor_self_escape, c.custom_survivor_min_escapes)
        else:
            survivor = SURVIVOR_PRESETS[c.survivor_preset]
        return Rules(killer, survivor)


# -- plain-English descriptions (settings window, README) ---------------------------

def describe_killer(r: KillerRule) -> str:
    removed = "killed, sacrificed or surrendered" + (" (or disconnected)" if r.count_dc else "")
    if r.required == 0:
        return "Every killer match counts as a win."
    text = f"Win if {r.required} survivor{'s' if r.required != 1 else ''} {'are' if r.required != 1 else 'is'} {removed}"
    if r.count_hatch:
        text += f", or {r.required - 1} are and the last one escaped through the hatch (a gate escape is a loss)"
    return text + "."


def describe_survivor(r: SurvivorRule) -> str:
    parts = []
    if r.self_escape:
        parts.append("you escape (gate or hatch)")
    if r.min_escapes > (1 if r.self_escape else 0):
        parts.append(f"at least {r.min_escapes} survivors escape in total")
    return "Win if " + " and ".join(parts) + "." if parts else "Every survivor match counts as a win."


def why_unknown(rules: Rules, m: MatchResult) -> str:
    """Short reason a match couldn't be decided, for the HUD prompt."""
    unread = sum(o in (S.UNKNOWN, S.ALIVE) for o in m.survivors)
    if not m.survivors:
        return "Win or loss?"
    if unread:
        left = sum(o is S.ALIVE for o in m.survivors)
        what = "still playing when you left" if left == unread else "icon not recognised"
        return f"Win or loss? ({unread} survivor{'s' if unread > 1 else ''}: {what})"
    if m.role is Role.KILLER and rules.killer.count_hatch:
        return "Hatch or gate?  streak-win = hatch · streak-loss = gate"
    return "Win or loss?"
