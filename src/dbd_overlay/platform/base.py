"""Interfaces every platform adapter implements.

Core/detection/features depend only on these Protocols. Hyprland and Windows
specifics live in their own modules, chosen once at startup (platform.get()).
A Protocol is structural typing: any class with matching methods qualifies,
no inheritance needed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np
    from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class WindowInfo:
    """Game window geometry in global (compositor) coordinates."""

    x: int
    y: int
    width: int
    height: int
    visible: bool  # on an active workspace, i.e. capturable right now


class WindowLocator(Protocol):
    def find_game_window(self) -> WindowInfo | None: ...


Rect = tuple[int, int, int, int]  # left, top, right, bottom (pixels, window-relative)


class ScreenCapture(Protocol):
    def grab(self, window: WindowInfo, region: Rect | None = None) -> np.ndarray | None:
        """BGR image of `region` of the window (whole window if None), or None on failure.

        Capturing only what detectors need matters: piping a full 1440p frame
        into Python costs ~10x more CPU than the detection itself."""
        ...


class HotkeyProvider(Protocol):
    """Hyprland: no-op (binds call `dbd-overlay ctl`). Windows: global hotkeys."""

    def start(self, dispatch: Callable[[str], str]) -> None: ...
    def stop(self) -> None: ...


class OverlayWindowHelper(Protocol):
    def make_overlay(self, widget: QWidget, click_through: bool) -> None:
        """Apply always-on-top / no-focus / click-through flags for this platform."""
        ...
