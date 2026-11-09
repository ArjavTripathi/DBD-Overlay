"""Where files live. XDG on Linux, %APPDATA% on Windows."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP = "dbd-overlay"


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


def config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / APP
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / APP
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def config_file() -> Path:
    return config_dir() / "config.toml"


def db_file() -> Path:
    return data_dir() / "matches.db"


def log_file() -> Path:
    return data_dir() / "dbd-overlay.log"


def assets_dir(configured: str) -> Path:
    return Path(configured).expanduser() if configured else data_dir() / "assets"


def control_socket_name() -> str:
    """Name for QLocalServer: a full socket path on Unix, a pipe name on Windows."""
    if sys.platform == "win32":
        return APP
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return str(Path(runtime) / f"{APP}.sock")
