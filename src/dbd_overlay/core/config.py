"""TOML config: typed defaults, merge user file over them, validate.

The dataclasses below ARE the schema: their field defaults are the defaults,
their type hints are what the loader checks. Add a setting = add a field.
"""

from __future__ import annotations

import dataclasses
import logging
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
    show: str = "match_end"
    opacity: float = 0.8
    x: int = 40
    y: int = 700


@dataclass
class StreakConfig:
    killer_preset: str = "3k_hatch"
    survivor_preset: str = "i_escape"
    dc_counts_as_kill: bool = True


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    hud: HudConfig = field(default_factory=HudConfig)
    streaks: StreakConfig = field(default_factory=StreakConfig)


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
