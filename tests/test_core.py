from dataclasses import dataclass

import pytest

from dbd_overlay.core import config
from dbd_overlay.core.commands import CommandRouter
from dbd_overlay.core.events import Event, EventBus, MapDetected, MatchStarted

# -- event bus ---------------------------------------------------------------


def test_bus_delivers_by_type():
    bus, got = EventBus(), []
    bus.subscribe(MapDetected, got.append)
    bus.publish(MatchStarted())
    bus.publish(MapDetected("Backwater Swamp", "The Pale Rose", 0.95))
    assert got == [MapDetected("Backwater Swamp", "The Pale Rose", 0.95)]


def test_bus_base_class_sees_everything_and_unsubscribe_works():
    bus, got = EventBus(), []
    unsub = bus.subscribe(Event, got.append)
    bus.publish(MatchStarted())
    unsub()
    bus.publish(MatchStarted())
    assert got == [MatchStarted()]


def test_bus_isolates_failing_handler():
    bus, got = EventBus(), []

    def boom(_):
        raise RuntimeError("feature bug")

    bus.subscribe(MatchStarted, boom)
    bus.subscribe(MatchStarted, got.append)
    bus.publish(MatchStarted())
    assert got == [MatchStarted()]


# -- command router ------------------------------------------------------------


def test_router_replies():
    r = CommandRouter()
    r.register("ping", lambda: "running")
    r.register("streak-win", lambda: None)
    r.register("streak-undo", lambda: 1 / 0)
    assert r.dispatch("ping") == "ok: running"
    assert r.dispatch("streak-win\n") == "ok"
    assert r.dispatch("streak-undo").startswith("error: division")
    assert r.dispatch("toggle-overlay") == "error: toggle-overlay is not available yet"
    assert r.dispatch("rm -rf").startswith("error: unknown command")


def test_router_arguments():
    r = CommandRouter()
    r.register("set-map", lambda arg: arg.upper(), takes_arg=True)
    r.register("ping", lambda: "running")
    assert r.dispatch("set-map  pale rose \n") == "ok: PALE ROSE"
    assert r.dispatch("set-map") == "error: set-map needs an argument"
    assert r.dispatch("ping extra") == "error: ping takes no argument"


def test_router_rejects_unknown_registration():
    with pytest.raises(ValueError):
        CommandRouter().register("typo", lambda: None)


# -- config --------------------------------------------------------------------


def test_config_defaults_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.load(path)  # creates the file
    assert path.exists()
    assert cfg == config.Config()
    cfg.overlay.opacity = 0.5
    config.save(cfg, path)
    assert config.load(path).overlay.opacity == 0.5


def test_config_partial_file_keeps_other_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[streaks]\nkiller_preset = "4k"\n[overlay]\nopacity = 1\n')
    cfg = config.load(path)
    assert cfg.streaks.killer_preset == "4k"
    assert cfg.overlay.opacity == 1.0 and isinstance(cfg.overlay.opacity, float)
    assert cfg.capture == config.CaptureConfig()


@pytest.mark.parametrize(
    "data, message",
    [
        ({"overlay": {"opacity": 2.0}}, "overlay.opacity"),
        ({"overlay": {"x": "left"}}, "overlay.x: expected int"),
        ({"overlay": {"x": True}}, "overlay.x: expected int"),
        ({"streaks": {"killer_preset": "5k"}}, "streaks.killer_preset"),
        ({"hud": "big"}, "[hud] must be a table"),
    ],
)
def test_config_validation_errors(data, message):
    with pytest.raises(config.ConfigError, match=message.replace("[", r"\[").replace("]", r"\]")):
        config.from_dict(data)


def test_config_unknown_key_is_warning_not_error(caplog):
    cfg = config.from_dict({"overlay": {"opacity": 0.3, "colour": "red"}})
    assert cfg.overlay.opacity == 0.3
    assert "overlay.colour" in caplog.text


def test_config_bad_toml(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is = = not toml")
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_icons_and_hud_style_config_roundtrip(tmp_path):
    from dbd_overlay.core import config as c
    cfg = c.Config()
    cfg.icons.killers["The Hillbilly"] = "/x/billy.png"
    cfg.hud.layout, cfg.hud.accent = "compact", "#ff0000"
    c.save(cfg, tmp_path / "c.toml")
    back = c.load(tmp_path / "c.toml")
    assert back.icons.killers == {"The Hillbilly": "/x/billy.png"} and back.hud.layout == "compact"


def test_bad_hud_colour_and_icon_table_rejected():
    import pytest
    from dbd_overlay.core import config as c
    with pytest.raises(c.ConfigError):
        c.from_dict({"hud": {"accent": "red"}})
    with pytest.raises(c.ConfigError):
        c.from_dict({"icons": {"killers": {"The Pig": 3}}})
