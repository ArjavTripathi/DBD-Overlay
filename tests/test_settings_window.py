"""Settings window: what Save emits, preview, cancel."""

import os
from types import SimpleNamespace as NS

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dbd_overlay.core.config import Config  # noqa: E402
from dbd_overlay.features.streaks.icons import Icons  # noqa: E402
from dbd_overlay.ui.settings import SettingsWindow  # noqa: E402

STATS = NS(current=1, attempt=2, best=3)


def make(tmp_path):
    QApplication.instance() or QApplication([])
    w = SettingsWindow()
    got = {"saved": [], "preview": [], "closed": 0}
    w.saved.connect(lambda *a: got["saved"].append(a))
    w.preview.connect(lambda *a: got["preview"].append(a))
    w.closed.connect(lambda: got.__setitem__("closed", got["closed"] + 1))
    w.open(Config(), [("survivor", False, STATS), ("killer:The Pig", True, STATS)],
           ["The Pig", "The Hillbilly"], Icons(tmp_path))
    return w, got


def test_save_emits_everything(tmp_path):
    w, got = make(tmp_path)
    w.streak_toggles["survivor"].setChecked(True)
    w.k_preset.setCurrentIndex(w.k_preset.findData("4k"))
    w.h_layout.setCurrentIndex(w.h_layout.findData("compact"))
    w.h_scale.setValue(150)
    w.icon_list.setCurrentRow(1)  # The Hillbilly (sorted)
    w._set_icon("/tmp/billy.png")
    w._save(False)
    (cfg, history, active), = got["saved"]
    assert active == {"survivor": True, "killer:The Pig": True} and history is False
    assert cfg.streaks.killer_preset == "4k"
    assert cfg.hud.layout == "compact" and cfg.hud.scale == 1.5
    assert cfg.icons.killers == {"The Hillbilly": "/tmp/billy.png"}
    assert got["closed"] == 1


def test_hud_changes_preview_live(tmp_path):
    w, got = make(tmp_path)
    w.nav.setCurrentRow(3)  # HUD page
    assert w.previewing
    w.h_icon.setChecked(False)
    hud, _ = got["preview"][-1]
    assert hud.show_icon is False


def test_cancel_emits_closed_not_saved(tmp_path):
    w, got = make(tmp_path)
    w.close()
    assert got["saved"] == [] and got["closed"] == 1


def test_discord_page(tmp_path):
    w, got = make(tmp_path)
    w.d_enabled.setChecked(True)
    assert "client ID" in w.d_error.text()
    w.d_client.setText("Dead by Daylight")              # name instead of ID: rejected, stays off
    assert "number" in w.d_error.text()
    assert w.discord_config().enabled is False
    w.d_client.setText(" 1234567890 ")
    assert w.d_error.text() == ""
    w._save(False)
    (cfg, _, _), = got["saved"]
    assert cfg.discord.enabled and cfg.discord.client_id == "1234567890"
