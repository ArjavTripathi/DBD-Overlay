"""Hyprland adapter: hyprctl to find the game window, grim to capture it.

Both are read-only: hyprctl queries the compositor, grim asks it for pixels.
Neither touches the game process.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

import cv2
import numpy as np

from .base import Rect, WindowInfo

log = logging.getLogger(__name__)


def _hyprctl(*args: str) -> list | dict:
    out = subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True, timeout=3, check=True)
    return json.loads(out.stdout)


def missing_tools() -> list[str]:
    return [t for t in ("hyprctl", "grim") if shutil.which(t) is None]


class HyprlandWindowLocator:
    def __init__(self, window_class: str) -> None:
        self.window_class = window_class

    def find_game_window(self) -> WindowInfo | None:
        try:
            clients = _hyprctl("clients")
            win = next((c for c in clients if c.get("class") == self.window_class and c.get("mapped", True)), None)
            if win is None:
                return None
            monitors = _hyprctl("monitors")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
            log.warning("hyprctl failed: %s", e)
            return None
        ws = win["workspace"]["id"]
        mon = next((m for m in monitors if m["id"] == win["monitor"]), None)
        # Capturable only if its workspace is the one shown on its monitor.
        visible = mon is not None and ws in (mon["activeWorkspace"]["id"], mon.get("specialWorkspace", {}).get("id"))
        (x, y), (w, h) = win["at"], win["size"]
        return WindowInfo(x, y, w, h, visible)


class GrimCapture:
    def grab(self, window: WindowInfo, region: Rect | None = None) -> np.ndarray | None:
        l, t, r, b = region or (0, 0, window.width, window.height)
        geom = f"{window.x + l},{window.y + t} {r - l}x{b - t}"
        try:
            # PPM: uncompressed, so no PNG encode/decode cost.
            r = subprocess.run(["grim", "-g", geom, "-t", "ppm", "-"], capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("grim failed: %s", e)
            return None
        if r.returncode != 0 or not r.stdout:
            log.warning("grim failed: %s", r.stderr.decode(errors="replace").strip())
            return None
        return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
