"""TOML config: typed defaults, merge user file over them, validate.

The dataclasses below ARE the schema: their field defaults are the defaults,
their type hints are what the loader checks. Add a setting = add a field.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import tomllib
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

log = logging.getLogger(__name__)

KILLER_PRESETS = ("4k", "3k_hatch", "3k_any", "custom")
SURVIVOR_PRESETS = ("i_escape", "3_out", "4_out", "custom")
HUD_SHOW = ("always", "match_end", "hotkey")
HUD_LAYOUTS = ("card", "compact")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class ConfigError(ValueError):
    pass


@dataclass
class GeneralConfig:
    log_level: str = "INFO"
    # Save title cards that couldn't be read to <data dir>/debug/ (rare, ~5 MB each).
    save_failed_frames: bool = True


@dataclass
class CaptureConfig:
    window_class: str = "steam_app_381210"
    poll_seconds: float = 1.0


@dataclass
class OverlayConfig:
    # Folder containing maps/<realm>/<map>.<png|webp|jpg>. Empty = <data dir>/assets.
    assets_dir: str = ""
    auto_show: bool = True
    opacity: float = 0.85
    x: int = 40
    y: int = 40
    width: int = 600
    height: int = 600


@dataclass
class HudConfig:
    show: str = "match_end"  # always | match_end (until the next match starts) | hotkey
    opacity: float = 0.85
    scale: float = 1.0
    x: int = 40
    y: int = 700
    # Look (all editable in Settings > HUD, previewed live).
    layout: str = "card"            # card (icon, title, numbers) | compact (icon + number)
    show_icon: bool = True
    show_title: bool = True
    show_attempt: bool = True
    show_best: bool = True
    icon_size: int = 64
    accent: str = "#e0c040"         # prompts, edit frame
    text_color: str = "#ffffff"
    background: str = "#101014"
    background_opacity: float = 0.82
    border: bool = True
    corner_radius: int = 10
    font: str = ""                  # font family; empty = system default
    survivor_title: str = "Survivor Streak"
    killer_title: str = "Killer Streak: {killer}"   # {killer} = 'Hillbilly'


@dataclass
class IconsConfig:
    """Icons picked in Settings > Icons (full paths). Anything not set here
    falls back to <assets>/icons/survivor.png, <assets>/icons/killers/<name>.png."""
    survivor: str = ""
    killers: dict[str, str] = field(default_factory=dict)   # "The Hillbilly" = "/path/to/img.png"


@dataclass
class StreakConfig:
    # Presets: 4k | 3k_hatch | 3k_any | custom   and   i_escape | 3_out | 4_out | custom
    killer_preset: str = "3k_hatch"
    survivor_preset: str = "i_escape"
    dc_counts_as_kill: bool = True
    # Used when a preset is "custom".
    custom_killer_required: int = 4          # survivors that must be killed/sacrificed/removed
    custom_killer_count_hatch: bool = False  # a hatch escape counts as removed
    custom_survivor_self_escape: bool = True # you must escape yourself
    custom_survivor_min_escapes: int = 1     # survivors out in total (incl. you)


@dataclass
class DiscordConfig:
    """Discord status ("Rich Presence"). Needs your own Discord application:
    discord.com/developers/applications > New Application; its NAME is what
    Discord shows after "Playing". Paste its Application ID as client_id."""
    enabled: bool = False
    client_id: str = ""
    # Optional: an image key uploaded under Rich Presence > Art Assets, or an https URL.
    large_image: str = ""
    show_map: bool = True


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    hud: HudConfig = field(default_factory=HudConfig)
    streaks: StreakConfig = field(default_factory=StreakConfig)
    icons: IconsConfig = field(default_factory=IconsConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)


# --------------------------------------------------------------------------

def _build[T](cls: type[T], data: dict[str, Any], path: str) -> T:
    """Construct dataclass `cls` from `data`, recursing into nested sections."""
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]
        key = f"{path}{f.name}"
        if f.name not in data:
            continue  # keep default
        value, expected = data[f.name], hints[f.name]
        if dataclasses.is_dataclass(expected):
            if not isinstance(value, dict):
                raise ConfigError(f"[{key}] must be a table")
            kwargs[f.name] = _build(expected, value, f"{key}.")
            continue
        if typing.get_origin(expected) is dict:
            if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
                raise ConfigError(f"[{key}] must be a table of strings")
            kwargs[f.name] = dict(value)
            continue
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)  # TOML `1` for a float field is fine
        # bool is a subclass of int; don't let `x = true` pass as an int.
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise ConfigError(f"{key}: expected {expected.__name__}, got {type(value).__name__} ({value!r})")
        kwargs[f.name] = value
    for unknown in data.keys() - {f.name for f in dataclasses.fields(cls)}:  # type: ignore[arg-type]
        log.warning("config: ignoring unknown key %s%s", path, unknown)
    return cls(**kwargs)


def _check_choice(key: str, value: str, choices: tuple[str, ...]) -> None:
    if value not in choices:
        raise ConfigError(f"{key}: {value!r} is not one of {', '.join(choices)}")


def _check_range(key: str, value: float, lo: float, hi: float) -> None:
    if not lo <= value <= hi:
        raise ConfigError(f"{key}: {value} is outside {lo}..{hi}")


def validate(cfg: Config) -> None:
    """Rules the type system can't express."""
    _check_choice("general.log_level", cfg.general.log_level, LOG_LEVELS)
    _check_range("capture.poll_seconds", cfg.capture.poll_seconds, 0.1, 10)
    _check_range("overlay.opacity", cfg.overlay.opacity, 0.05, 1)
    _check_range("hud.opacity", cfg.hud.opacity, 0.05, 1)
    if cfg.overlay.width < 50 or cfg.overlay.height < 50:
        raise ConfigError("overlay.width/height must be at least 50")
    _check_choice("hud.show", cfg.hud.show, HUD_SHOW)
    _check_choice("streaks.killer_preset", cfg.streaks.killer_preset, KILLER_PRESETS)
    _check_choice("streaks.survivor_preset", cfg.streaks.survivor_preset, SURVIVOR_PRESETS)
    _check_range("streaks.custom_killer_required", cfg.streaks.custom_killer_required, 0, 4)
    _check_range("streaks.custom_survivor_min_escapes", cfg.streaks.custom_survivor_min_escapes, 0, 4)
    _check_range("hud.scale", cfg.hud.scale, 0.5, 3)
    _check_choice("hud.layout", cfg.hud.layout, HUD_LAYOUTS)
    _check_range("hud.icon_size", cfg.hud.icon_size, 16, 256)
    _check_range("hud.background_opacity", cfg.hud.background_opacity, 0, 1)
    _check_range("hud.corner_radius", cfg.hud.corner_radius, 0, 40)
    for name in ("accent", "text_color", "background"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", getattr(cfg.hud, name)):
            raise ConfigError(f"hud.{name}: expected a colour like #e0c040")
    cid = cfg.discord.client_id.strip()
    if cid and not cid.isdigit():
        raise ConfigError("discord.client_id: expected the numeric Application ID")


def from_dict(data: dict[str, Any]) -> Config:
    cfg = _build(Config, data, "")
    validate(cfg)
    return cfg


def load(path: Path) -> Config:
    """Load config; a missing file is created with the defaults so it's easy to edit."""
    if not path.exists():
        cfg = Config()
        save(cfg, path)
        log.info("wrote default config to %s", path)
        return cfg
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    return from_dict(data)


def save(cfg: Config, path: Path) -> None:
    validate(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(tomli_w.dumps(dataclasses.asdict(cfg)))
    tmp.replace(path)  # atomic: a crash mid-write never leaves a half-written config
