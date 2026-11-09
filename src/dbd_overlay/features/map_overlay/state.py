"""When is the map overlay on screen? Pure logic, no Qt, so it's unit-tested."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OverlayState:
    wanted: bool = False        # user/auto-show wants it (toggle hotkey flips this)
    game_visible: bool = False  # game is on the visible workspace
    has_image: bool = False     # an image exists for the current map
    editing: bool = False       # edit mode always shows (with a placeholder if needed)

    @property
    def shown(self) -> bool:
        # Layer-shell surfaces appear on every workspace, so hide when the
        # user switches away from the game.
        return self.editing or (self.wanted and self.game_visible and self.has_image)
