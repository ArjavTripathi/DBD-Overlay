from dbd_overlay.features.map_overlay.state import OverlayState


def test_needs_wanted_visible_and_image():
    s = OverlayState(wanted=True, game_visible=True, has_image=True)
    assert s.shown
    for field in ("wanted", "game_visible", "has_image"):
        t = OverlayState(wanted=True, game_visible=True, has_image=True)
        setattr(t, field, False)
        assert not t.shown, field


def test_edit_mode_always_shows():
    assert OverlayState(editing=True).shown
