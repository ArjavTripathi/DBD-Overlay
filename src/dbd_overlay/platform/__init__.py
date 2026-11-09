"""Pick the platform adapters once, at startup. Nothing else imports a
platform-specific module directly."""

from __future__ import annotations

import os
import sys

from .base import ScreenCapture, WindowLocator


def create(window_class: str) -> tuple[WindowLocator, ScreenCapture]:
    if sys.platform.startswith("linux") and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        from .linux_hyprland import GrimCapture, HyprlandWindowLocator, missing_tools

        if missing := missing_tools():
            raise RuntimeError(f"missing tools: {', '.join(missing)} (sudo pacman -S grim hyprland)")
        return HyprlandWindowLocator(window_class), GrimCapture()
    raise RuntimeError(f"unsupported platform/compositor ({sys.platform}); only Hyprland is implemented so far")
