from dbd_overlay.core.events import KillerDetected, MatchEnded, RoleDetected, ScoreboardRead
from dbd_overlay.core.models import Role
from dbd_overlay.detection.end_screen import EndKind, EndReading, ScoreboardReading, looks_like_title, strip_edge_junk
from dbd_overlay.detection.match_tracker import MatchTracker, Observation, Phase

ROWS = ("KATE DENSON MBOW", "JONAH VASQUEZ X", "SABLE WARD Y", "THALITA LYRA Z", "THE TRAPPER SPEEDY")
FULL = ScoreboardReading(ROWS, "SPEEDY", "The Trapper", 4, 4)
NO_NAME = ScoreboardReading(ROWS, "", "The Trapper", 4, None)
RESULT = EndReading(EndKind.RESULT, "BRUTAL KILLER")
BOARD = lambda b: EndReading(EndKind.SCOREBOARD, "SCOREBOARD", b)  # noqa: E731
NOTHING = EndReading()


def names(events):
    return [type(e).__name__ for e in events]


def test_full_match_cycle():
    t = MatchTracker()
    assert t.update(Observation(match_started=True), 0) == []
    assert t.phase is Phase.MATCH
    assert names(t.update(Observation(end=RESULT), 10)) == ["MatchEnded"]
    assert t.update(Observation(end=RESULT), 11) == []          # only once
    ev = t.update(Observation(end=BOARD(FULL)), 12)
    assert ev == [
        ScoreboardRead("The Trapper", Role.KILLER, 4, 4, "SPEEDY", ROWS, "BRUTAL KILLER"),
        KillerDetected("The Trapper", 1.0, "scoreboard"),
        RoleDetected(Role.KILLER, "scoreboard"),
    ]
    assert t.update(Observation(end=BOARD(FULL)), 13) == []      # published once
    t.update(Observation(lobby=True), 20)
    assert t.phase is Phase.IDLE


def test_end_screen_without_seen_start_still_ends_match():
    t = MatchTracker()
    assert names(t.update(Observation(end=RESULT), 0)) == ["MatchEnded"]


def test_incomplete_board_published_when_leaving():
    t = MatchTracker()
    t.update(Observation(end=BOARD(NO_NAME)), 0)
    ev = t.update(Observation(lobby=True), 5)
    assert names(ev) == ["ScoreboardRead", "KillerDetected"]   # no RoleDetected: unknown
    assert ev[0].role is None


def test_best_board_wins():
    t = MatchTracker()
    t.update(Observation(end=BOARD(NO_NAME)), 0)
    ev = t.update(Observation(end=BOARD(FULL)), 1)
    assert ev[0].role is Role.KILLER


def test_lobby_during_match_means_ended_early():
    t = MatchTracker()
    t.update(Observation(match_started=True), 0)
    assert t.update(Observation(lobby=False), 5) == []
    assert names(t.update(Observation(lobby=True), 9)) == ["MatchEnded"]
    assert t.phase is Phase.IDLE


def test_end_screens_gone_returns_to_idle():
    t = MatchTracker(end_gone_after=30)
    t.update(Observation(end=RESULT), 0)
    t.update(Observation(end=NOTHING), 10)
    assert t.phase is Phase.ENDED
    t.update(Observation(end=NOTHING), 31)
    assert t.phase is Phase.IDLE


def test_role_from_rows():
    assert ScoreboardReading(ROWS, "X", "The Trapper", 4, 1).role is Role.SURVIVOR
    assert ScoreboardReading(ROWS, "X", None, None, 1).role is None


def test_text_guards():
    assert looks_like_title("BRUTAL KILLER") and looks_like_title("SCOREBOARD")
    assert not looks_like_title("1 AL ' M ' ' I E 4")   # real OCR of a red aura
    assert strip_edge_junk("N SPEEDY") == "SPEEDY"
    assert strip_edge_junk("CARRY POTTER") == "CARRY POTTER"
    assert strip_edge_junk("~ A B C ~") == ""


# -- hatch inference from the End Game Collapse -----------------------------------

from dbd_overlay.core.models import SurvivorOutcome as S  # noqa: E402

KILLS_3_ESC_1 = ScoreboardReading(ROWS, "SPEEDY", "The Trapper", 4, 4, (S.KILLED, S.KILLED, S.ESCAPED, S.KILLED))


def play(egc_ticks, start=True, gap_at=None, board=KILLS_3_ESC_1):
    """Simulate a watched match: 1 tick/s, EGC visible on the given tick indices."""
    t = MatchTracker()
    now = 0.0
    if start:
        t.update(Observation(match_started=True), now)
    for i in range(120):
        now += 31 if i == gap_at else 1
        t.update(Observation(egc=i in egc_ticks), now)
    t.update(Observation(end=RESULT), now + 1)
    (board_event, *_) = t.update(Observation(end=BOARD(board)), now + 2)
    return board_event.hatch_used


def test_no_egc_means_hatch():
    assert play(egc_ticks=set()) is True


def test_egc_seen_means_unknown():
    assert play(egc_ticks=set(range(60, 120))) is None


def test_egc_flicker_is_not_egc():
    assert play(egc_ticks={10, 50}) is True    # isolated frames, never 3 in a row


def test_unwatched_gap_means_unknown():
    assert play(egc_ticks=set(), gap_at=50) is None


def test_missed_start_means_unknown():
    assert play(egc_ticks=set(), start=False) is None


def test_no_escape_no_hatch_claim():
    four_k = ScoreboardReading(ROWS, "SPEEDY", "The Trapper", 4, 4, (S.KILLED,) * 4)
    assert play(egc_ticks=set(), board=four_k) is None



def test_scoreboard_reappearing_is_not_a_new_match():
    """AJ's Rancid Abattoir match was recorded twice: the scoreboard went away
    for >30 s and came back."""
    t = MatchTracker(end_gone_after=30)
    t.update(Observation(match_started=True), 0)
    assert names(t.update(Observation(end=BOARD(FULL)), 100)) == ["MatchEnded", "ScoreboardRead", "KillerDetected", "RoleDetected"]
    t.update(Observation(end=NOTHING), 140)                   # gone for 40 s -> idle
    assert t.update(Observation(end=BOARD(FULL)), 150) == []  # same match: nothing new
    t.update(Observation(lobby=True), 160)                    # lobby: next end screen is a new match
    assert names(t.update(Observation(end=RESULT), 400)) == ["MatchEnded"]
