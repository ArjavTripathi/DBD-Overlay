from datetime import UTC, datetime, timedelta

import pytest

from dbd_overlay.core.config import StreakConfig
from dbd_overlay.core.models import ManualOutcome, MatchResult, Role, SurvivorOutcome as S, Verdict
from dbd_overlay.features.streaks.rules import Rules
from dbd_overlay.features.streaks.stats import compute

W, L, U = Verdict.WIN, Verdict.LOSS, Verdict.UNKNOWN
K, E, D, F, X = S.KILLED, S.ESCAPED, S.DISCONNECTED, S.SURRENDERED, S.UNKNOWN


def killer(*outs, hatch=None, manual=None):
    return MatchResult(Role.KILLER, killer="The Trapper", survivors=tuple(outs), hatch_used=hatch, manual_outcome=manual)


def surv(*outs, me=0, manual=None):
    return MatchResult(Role.SURVIVOR, survivors=tuple(outs), my_index=me, manual_outcome=manual)


def rules(killer_preset="3k_hatch", survivor_preset="i_escape", dc=True, **custom):
    return Rules.from_config(StreakConfig(killer_preset=killer_preset, survivor_preset=survivor_preset,
                                          dc_counts_as_kill=dc, **custom))


@pytest.mark.parametrize("preset, outs, hatch, expected", [
    # 4k: everyone must be removed
    ("4k", (K, K, K, K), None, W),
    ("4k", (K, K, K, E), True, L),           # hatch doesn't help
    ("4k", (K, K, F, K), None, W),           # surrender = kill
    ("4k", (K, K, K, D), None, W),           # DC counts (dc=True)
    # 3k + hatch: 4 removed, or 3 + the last one took hatch
    ("3k_hatch", (K, K, K, K), None, W),
    ("3k_hatch", (K, K, K, E), True, W),
    ("3k_hatch", (K, K, K, E), False, L),    # gate escape
    ("3k_hatch", (K, K, K, E), None, U),     # can't tell hatch from gate: ask
    ("3k_hatch", (K, K, E, E), True, L),
    ("3k_hatch", (K, K, D, E), True, W),     # DC counted, last took hatch
    # 3k any
    ("3k_any", (K, K, K, E), False, W),
    ("3k_any", (K, K, E, E), None, L),
    ("3k_any", (K, K, D, E), None, W),
    # missing facts
    ("4k", (K, K, K, X), None, U),
    ("4k", (), None, U),
])
def test_killer_presets(preset, outs, hatch, expected):
    assert rules(preset).evaluate(killer(*outs, hatch=hatch)) is expected


def test_dc_option():
    assert rules("4k", dc=False).evaluate(killer(K, K, K, D)) is L
    assert rules("3k_any", dc=False).evaluate(killer(K, K, D, D)) is L
    assert rules("3k_any", dc=False).evaluate(killer(K, K, F, D)) is W  # surrender always counts


@pytest.mark.parametrize("preset, outs, me, expected", [
    ("i_escape", (E, K, K, K), 0, W),
    ("i_escape", (K, E, E, E), 0, L),
    ("i_escape", (E, X, X, X), 0, W),        # only your own outcome is needed (result banner)
    ("i_escape", (X, E, E, E), 0, U),
    ("i_escape", (E, E, E, E), None, U),     # don't know which row is you
    ("3_out", (E, E, E, K), 1, W),
    ("3_out", (K, E, E, E), 0, W),           # you died but 3 got out
    ("3_out", (E, E, K, K), 0, L),
    ("3_out", (E, E, X, K), 0, U),           # could still be 3
    ("4_out", (E, E, E, E), 2, W),
    ("4_out", (E, E, E, D), 2, L),
])
def test_survivor_presets(preset, outs, me, expected):
    assert rules(survivor_preset=preset).evaluate(surv(*outs, me=me)) is expected


def test_custom_rules():
    r = rules("custom", "custom", custom_killer_required=2, custom_killer_count_hatch=False,
              custom_survivor_self_escape=False, custom_survivor_min_escapes=2)
    assert r.evaluate(killer(K, K, E, E)) is W
    assert r.evaluate(surv(K, E, E, K)) is W


def test_manual_outcome_wins_over_facts():
    assert rules("4k").evaluate(killer(E, E, E, E, manual=ManualOutcome.WIN)) is W
    assert rules().evaluate(surv(E, X, X, X, manual=ManualOutcome.LOSS)) is L
    assert rules().evaluate(killer(manual=ManualOutcome.WIN)) is W  # no facts at all


# -- streak numbers ---------------------------------------------------------------

T0 = datetime(2026, 11, 9, tzinfo=UTC)


def seq(*verdicts, ignored=()):
    out = []
    for i, v in enumerate(verdicts):
        out.append(MatchResult(Role.KILLER, killer="The Trapper", verdict=v, ignored=i in ignored,
                               ts=T0 + timedelta(minutes=i)))
    return out


def test_stats_basic():
    s = compute(seq(W, W, L, W, W, W))
    assert (s.current, s.best, s.attempt, s.wins, s.losses) == (3, 3, 2, 5, 1)


def test_stats_empty():
    assert compute([]) == compute(seq())
    assert compute([]).attempt == 1


def test_stats_ignored_and_pending_are_skipped():
    s = compute(seq(W, L, W, U, W, ignored={1}))
    assert (s.current, s.attempt, s.pending) == (3, 1, 1)


def test_stats_reset_keeps_best():
    ms = seq(W, W, W, W, L, W)
    s = compute(ms, reset_at=ms[4].ts)   # reset right after the loss
    assert (s.current, s.attempt, s.best, s.losses) == (1, 1, 4, 0)


def test_descriptions():
    from dbd_overlay.features.streaks.rules import describe_killer, describe_survivor
    r = rules("3k_hatch", "3_out", dc=False)
    assert describe_killer(r.killer) == ("Win if 4 survivors are killed, sacrificed or surrendered, or 3 are "
                                         "and the last one escaped through the hatch (a gate escape is a loss).")
    assert describe_survivor(r.survivor) == "Win if at least 3 survivors escape in total."
    assert describe_survivor(rules().survivor) == "Win if you escape (gate or hatch)."
    assert "(or disconnected)" in describe_killer(rules("4k", dc=True).killer)


@pytest.mark.parametrize("preset, outs, hatch, expected", [
    ("3k_any", (K, K, K, X), None, W),       # 3 kills already: the unread one can't matter
    ("3k_any", (K, E, E, X), None, L),       # at most 2 kills
    ("3k_any", (K, K, E, X), None, U),       # depends on the unread one
    ("4k", (K, K, K, X), None, U),
    ("4k", (K, K, E, X), None, L),
    ("3k_hatch", (K, K, K, X), None, U),     # unread could be a gate escape
    ("3k_hatch", (K, K, K, X), True, W),     # ...but we know it was hatch
    ("3k_hatch", (K, E, X, K), None, U),     # AJ's real match 5
    ("3k_any", (K, K, K, S.ALIVE), None, W),
])
def test_killer_with_unread_icons(preset, outs, hatch, expected):
    assert rules(preset).evaluate(killer(*outs, hatch=hatch)) is expected


def test_why_unknown():
    from dbd_overlay.features.streaks.rules import why_unknown
    r = rules("3k_hatch")
    assert why_unknown(r, killer(K, K, K, E)).startswith("Hatch or gate?")
    assert "icon not recognised" in why_unknown(r, killer(K, E, X, K))
    assert "still playing" in why_unknown(r, surv(S.ALIVE, S.ALIVE, K, S.ALIVE, me=2))
