"""StreakFeature with a real (offscreen) HUD: what the HUD shows after settings changes."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dbd_overlay.core.commands import CommandRouter  # noqa: E402
from dbd_overlay.core.config import StreakConfig  # noqa: E402
from dbd_overlay.core.events import EventBus, KillerDetected, RoleDetected  # noqa: E402
from dbd_overlay.core.models import Role  # noqa: E402
from dbd_overlay.core.session import Session  # noqa: E402
from dbd_overlay.features.streaks import StreakFeature  # noqa: E402
from dbd_overlay.features.streaks.icons import Icons  # noqa: E402
from dbd_overlay.features.streaks.rules import Rules  # noqa: E402
from dbd_overlay.features.streaks.service import StreakService  # noqa: E402
from dbd_overlay.storage.db import Database  # noqa: E402
from dbd_overlay.ui.overlay import HudWindow, create_engine  # noqa: E402


@pytest.fixture
def feature(tmp_path):
    app = QApplication.instance() or QApplication([])
    bus = EventBus()
    session = Session(bus, tmp_path / "state.json")
    engine, store = create_engine("generic")
    hud = HudWindow(engine, store, (0, 0), 0.85, 1.0)
    svc = StreakService(Database(":memory:"), Rules.from_config(StreakConfig()))
    f = StreakFeature(bus, CommandRouter(), svc, session, hud, Icons(tmp_path), "match_end",
                      notify=lambda *a: None, save_position=lambda p: None)
    # AJ's situation: last scoreboard said killer / Hillbilly, Hillbilly streak on.
    bus.publish(KillerDetected("The Hillbilly", 1.0, source="manual"))
    bus.publish(RoleDetected(Role.KILLER, source="manual"))
    svc.set_active("killer:The Hillbilly", True)
    app.processEvents()
    f._engine = engine  # keep alive
    return f, session, hud, app


def title(hud):
    return hud.root.property("title")


def test_ticking_survivor_shows_survivor(feature):
    f, session, hud, app = feature
    assert title(hud) == "Killer Streak: Hillbilly"
    f.apply_settings(f.svc.rules, "match_end", False, {"survivor": True, "killer:The Hillbilly": False})
    app.processEvents()
    assert session.category == "survivor"
    assert title(hud) == "Survivor Streak" and hud.root.property("active") is True


def test_only_one_on_and_shown_one_off_switches(feature):
    f, session, hud, app = feature
    f.svc.set_active("survivor", True)  # already on before opening settings
    f.apply_settings(f.svc.rules, "match_end", False, {"survivor": True, "killer:The Hillbilly": False})
    app.processEvents()
    assert session.category == "survivor"


def test_unrelated_save_keeps_current(feature):
    f, session, hud, app = feature
    f.apply_settings(f.svc.rules, "always", False, {"killer:The Hillbilly": True})
    app.processEvents()
    assert session.category == "killer:The Hillbilly"


def test_custom_titles_and_style(feature):
    from dbd_overlay.core.config import HudConfig
    f, session, hud, app = feature
    f.set_look(HudConfig(killer_title="{killer} run", layout="compact", accent="#ff0000"))
    app.processEvents()
    assert title(hud) == "Hillbilly run"
    assert hud.root.property("compact") is True


def test_preview_shows_hud_even_without_game(feature):
    f, session, hud, app = feature
    f.state.game_visible = False
    f.set_preview(True)
    assert hud.root.property("visible") is True
    f.set_preview(False)
    assert hud.root.property("visible") is False
