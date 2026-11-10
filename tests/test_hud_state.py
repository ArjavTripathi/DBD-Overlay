from dbd_overlay.features.streaks.state import HudState


def test_match_end_mode_shows_between_matches_only():
    s = HudState(mode="match_end", game_visible=True)
    assert s.shown                 # app starts in the lobby
    s.match_started()
    assert not s.shown
    s.match_ended()
    assert s.shown


def test_hidden_when_game_not_visible():
    assert not HudState(mode="always", game_visible=False).shown


def test_toggle_overrides_until_next_match_event():
    s = HudState(mode="match_end", game_visible=True)
    s.match_started()
    assert s.toggle() and s.shown  # peek during a match
    s.match_ended()
    s.match_started()
    assert not s.shown             # override cleared


def test_hotkey_mode():
    s = HudState(mode="hotkey", game_visible=True)
    assert not s.shown
    s.toggle()
    assert s.shown


def test_editing_always_shows():
    assert HudState(mode="hotkey", game_visible=False, editing=True).shown
