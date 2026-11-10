from dbd_overlay.core.config import IconsConfig
from dbd_overlay.features.streaks.icons import Icons


def test_custom_icon_beats_assets_folder_and_clears(tmp_path):
    (tmp_path / "icons" / "killers").mkdir(parents=True)
    folder = tmp_path / "icons" / "killers" / "Hillbilly.png"
    folder.write_bytes(b"x")
    custom = tmp_path / "mine.webp"
    custom.write_bytes(b"x")
    icons = Icons(tmp_path)
    assert icons.source("killer:The Hillbilly") == (folder, "assets")
    icons.set("killer:The Hillbilly", str(custom))
    assert icons.source("killer:The Hillbilly") == (custom, "custom")
    icons.set("killer:The Hillbilly", "")
    assert icons.killer("The Hillbilly") == folder
    assert icons.source("survivor") == (None, "")


def test_missing_custom_file_falls_back(tmp_path):
    icons = Icons(tmp_path, IconsConfig(survivor=str(tmp_path / "gone.png")))
    assert icons.survivor() is None


def test_with_overrides_copies(tmp_path):
    base = Icons(tmp_path)
    o = IconsConfig()
    other = base.with_overrides(o)
    other.set("killer:The Pig", "/p.png")
    assert o.killers == {}
