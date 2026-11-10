"""When is the HUD on screen? Pure logic, unit-tested.

Modes (config hud.show):
    always     whenever the game is visible
    match_end  from the end of a match until the next one starts (i.e. in the lobby)
    hotkey     only when toggled
`toggle-hud` overrides the mode until the next match starts or ends.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HudState:
    mode: str = "match_end"
    game_visible: bool = False
    between_matches: bool = True   # app usually starts in the lobby
    forced: bool | None = None     # toggle-hud override
    editing: bool = False

    @property
    def base(self) -> bool:
        return self.mode == "always" or (self.mode == "match_end" and self.between_matches)

    @property
    def shown(self) -> bool:
        if self.editing:
            return True
        return self.game_visible and (self.forced if self.forced is not None else self.base)

    def toggle(self) -> bool:
        self.forced = not (self.forced if self.forced is not None else self.base)
        return self.forced

    def match_started(self) -> None:
        self.between_matches, self.forced = False, None

    def match_ended(self) -> None:
        self.between_matches, self.forced = True, None
