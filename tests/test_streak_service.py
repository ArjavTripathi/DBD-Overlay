from datetime import UTC, datetime, timedelta

import pytest

from dbd_overlay.core.config import StreakConfig
from dbd_overlay.core.events import ScoreboardRead
from dbd_overlay.core.models import ManualOutcome, Role, SurvivorOutcome as S, Verdict
from dbd_overlay.features.streaks.rules import Rules
from dbd_overlay.features.streaks.service import StreakService, banner_outcome
from dbd_overlay.storage.db import Database

WIN, LOSS = ManualOutcome.WIN, ManualOutcome.LOSS
ROWS = ("A", "B", "C", "D", "THE TRAPPER ME")


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 9, 20, 0, tzinfo=UTC)

    def __call__(self):
        return self.t

    def advance(self, minutes):
        self.t += timedelta(minutes=minutes)


@pytest.fixture
def svc():
    """Service with the streaks used below switched ON (new streaks default to off)."""
    clock = Clock()
    s = StreakService(Database(":memory:"), Rules.from_config(StreakConfig()), now=clock)
    for cat in ("survivor", "killer:The Trapper", "killer:The Hag"):
        s.db.set_streak_active(cat, True)
    s.clock = clock
    return s


def board(role, killer="The Trapper", my_row=4, result=""):
    return ScoreboardRead(killer, role, my_row, 4, "ME", ROWS, result)


def test_banner_outcome():
    assert banner_outcome("ESCAPED") is S.ESCAPED
    assert banner_outcome("SACRIFICED") is S.KILLED
    assert banner_outcome("BRUTAL KILLER") is S.UNKNOWN


def test_survivor_auto_verdict_from_banner(svc):
    m = svc.record(svc.match_from_board(board(Role.SURVIVOR, my_row=1, result="ESCAPED"), None, "Toba Landing", "Dvarka Deepwood"))
    assert m.category == "survivor" and m.my_index == 1 and m.survivors[1] is S.ESCAPED
    assert m.killer == "The Trapper"            # the opponent, kept as a raw fact
    assert m.verdict is Verdict.WIN             # i_escape decided automatically
    svc.clock.advance(15)
    svc.record(svc.match_from_board(board(Role.SURVIVOR, my_row=0, result="SACRIFICED"), None, None, None))
    assert svc.stats("survivor").attempt == 2


def test_killer_match_waits_for_hotkey(svc):
    m = svc.record(svc.match_from_board(board(Role.KILLER), "The Trapper", None, None))
    assert m.category == "killer:The Trapper" and m.verdict is Verdict.UNKNOWN
    assert svc.stats(m.category).pending == 1
    assert "last match" in svc.win_or_loss(WIN, Role.KILLER, "The Trapper")
    st = svc.stats(m.category)
    assert (st.current, st.pending) == (1, 0)


def test_hotkey_long_after_creates_new_match(svc):
    svc.record(svc.match_from_board(board(Role.KILLER), "The Trapper", None, None))
    svc.win_or_loss(WIN, Role.KILLER, "The Trapper")
    svc.clock.advance(30)
    assert "new match" in svc.win_or_loss(WIN, Role.KILLER, "The Trapper")
    assert svc.stats("killer:The Trapper").current == 2


def test_hotkey_corrects_an_auto_verdict(svc):
    m = svc.record(svc.match_from_board(board(Role.SURVIVOR, my_row=0, result="SACRIFICED"), None, None, None))
    assert m.verdict is Verdict.LOSS
    svc.win_or_loss(WIN, Role.SURVIVOR, None)
    assert svc.stats("survivor").current == 1


def test_manual_needs_role_and_killer(svc):
    with pytest.raises(ValueError, match="role unknown"):
        svc.win_or_loss(WIN, None, None)
    with pytest.raises(ValueError, match="which killer"):
        svc.win_or_loss(WIN, Role.KILLER, None)


def test_undo_each_action(svc):
    svc.win_or_loss(WIN, Role.KILLER, "The Hag")
    svc.clock.advance(20)
    svc.win_or_loss(WIN, Role.KILLER, "The Hag")
    cat = "killer:The Hag"
    assert svc.stats(cat).current == 2
    svc.ignore_last()
    assert svc.stats(cat).current == 1
    svc.undo()                                  # un-ignore
    assert svc.stats(cat).current == 2
    svc.reset(cat)
    assert svc.stats(cat).current == 0
    svc.undo()                                  # un-reset
    assert svc.stats(cat).current == 2
    svc.undo()                                  # remove 2nd match
    svc.undo()                                  # remove 1st match
    assert svc.stats(cat) == svc.stats("killer:nobody")
    with pytest.raises(ValueError):
        svc.undo()


def test_amend_then_undo_restores_unknown(svc):
    svc.record(svc.match_from_board(board(Role.KILLER), "The Trapper", None, None))
    svc.win_or_loss(LOSS, Role.KILLER, "The Trapper")
    svc.undo()
    assert svc.stats("killer:The Trapper").pending == 1


def test_recompute_applies_new_rules_to_history(svc):
    m = svc.record(svc.match_from_board(board(Role.SURVIVOR, my_row=0, result="SACRIFICED"), None, None, None))
    assert m.verdict is Verdict.LOSS
    # Switch to "3 out": with only your own outcome known, it's now undecidable.
    svc.rules = Rules.from_config(StreakConfig(survivor_preset="3_out"))
    assert svc.stats("survivor").losses == 1     # "from now on": history untouched
    assert svc.recompute_all() == 1
    assert svc.stats("survivor").pending == 1
    svc.undo()
    assert svc.stats("survivor").losses == 1


def test_two_manual_presses_are_two_matches(svc):
    """Without detection, quick consecutive matches must not amend each other."""
    svc.win_or_loss(WIN, Role.KILLER, "The Hag")
    svc.clock.advance(4)
    assert "new match" in svc.win_or_loss(WIN, Role.KILLER, "The Hag")
    assert svc.stats("killer:The Hag").current == 2


def test_auto_match_amended_only_once(svc):
    svc.record(svc.match_from_board(board(Role.KILLER), "The Trapper", None, None))
    assert "last match" in svc.win_or_loss(WIN, Role.KILLER, "The Trapper")
    assert "new match" in svc.win_or_loss(WIN, Role.KILLER, "The Trapper")


# -- streaks on/off ------------------------------------------------------------------

@pytest.fixture
def fresh():
    clock = Clock()
    s = StreakService(Database(":memory:"), Rules.from_config(StreakConfig()), now=clock)
    s.clock = clock
    return s


def test_new_streaks_start_off(fresh):
    m = fresh.record(fresh.match_from_board(board(Role.SURVIVOR, my_row=1, result="ESCAPED"), None, None, None))
    assert m.verdict is Verdict.WIN and not m.counted          # judged and saved, but not counted
    assert fresh.stats("survivor").current == 0
    assert "not counted" in (fresh.clock.advance(20) or fresh.win_or_loss(WIN, Role.SURVIVOR, None))


def test_toggle_right_after_match_counts_it(fresh):
    fresh.record(fresh.match_from_board(board(Role.SURVIVOR, my_row=1, result="ESCAPED"), None, None, None))
    fresh.clock.advance(3)
    assert "counting the match you just played" in fresh.toggle("survivor")
    assert fresh.stats("survivor").current == 1
    fresh.undo()                                                # back off, match uncounted again
    assert not fresh.is_active("survivor") and fresh.stats("survivor").current == 0


def test_toggle_long_after_does_not_count_old_match(fresh):
    fresh.record(fresh.match_from_board(board(Role.SURVIVOR, my_row=1, result="ESCAPED"), None, None, None))
    fresh.clock.advance(30)
    assert fresh.toggle("survivor") == "survivor streak on"
    assert fresh.stats("survivor").current == 0


def test_pause_keeps_streak_and_resumes(fresh):
    fresh.toggle("killer:The Hag")
    for _ in range(3):
        fresh.clock.advance(15)
        fresh.win_or_loss(WIN, Role.KILLER, "The Hag")
    fresh.toggle("killer:The Hag")                              # pause
    fresh.clock.advance(15)
    fresh.win_or_loss(LOSS, Role.KILLER, "The Hag")              # casual game: doesn't break it
    fresh.clock.advance(15)
    fresh.toggle("killer:The Hag")                              # resume (30 min later: no late count)
    fresh.clock.advance(15)
    fresh.win_or_loss(WIN, Role.KILLER, "The Hag")
    st = fresh.stats("killer:The Hag")
    assert (st.current, st.attempt) == (4, 1)


def test_streak_list(fresh):
    fresh.toggle("killer:The Hag")
    fresh.record(fresh.match_from_board(board(Role.SURVIVOR, my_row=1, result="ESCAPED"), None, None, None))
    assert [(c, on) for c, on, _ in fresh.streaks()] == [("survivor", False), ("killer:The Hag", True)]
