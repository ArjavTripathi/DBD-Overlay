"""What the Discord status should say. Pure logic: events in, activity dict out.

    CLOSED ─window─> MENUS <──lobby gone (after PLAY)── LOBBY
                       │                                 │ lobby gone (after READY/CANCEL)
                       │                                 v
                       └──────────title card────────> MATCH
                                                         │ end screen
                                                         v
                                                     POSTGAME ──lobby──> LOBBY

Leaving a lobby you queued from already counts as MATCH: the title card is
only up for a few seconds and is missed if the game's workspace isn't shown
right then. When it IS seen, it supplies the map and restarts the timer at
the real start of play.

Role and your killer come from the Session (it already decides whose killer
a scoreboard name is). The map is tracked here, per match, so a missed title
card never shows the previous match's map.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from ...core.events import (Event, GameWindowChanged, LobbyChanged, MapDetected, MatchEnded, MatchStarted,
                            RoleDetected, KillerDetected, ScoreboardRead)
from ...core.models import Role
from ...core.session import Session
from ...detection.lobby import QUEUED_WORDS


class Where(StrEnum):
    CLOSED = "closed"
    MENUS = "menus"
    LOBBY = "lobby"
    MATCH = "match"
    POSTGAME = "postgame"


MAX_LEN = 128  # Discord rejects longer details/state


def _clip(text: str | None) -> str | None:
    if not text:
        return None
    text = text if len(text) <= MAX_LEN else text[:MAX_LEN - 1] + "…"
    return text if len(text) >= 2 else text + " "  # and shorter than 2 chars


class PresenceState:
    def __init__(self, session: Session, large_image: str = "", show_map: bool = True,
                 clock: Callable[[], float] = time.time) -> None:
        self.session = session
        self.large_image, self.show_map = large_image, show_map
        self.clock = clock
        self.where = Where.CLOSED
        self.button: str | None = None
        self.match_start: int | None = None
        self.result = ""
        self.opponent: str | None = None
        self.map: str | None = None

    def update(self, e: Event) -> None:
        match e:
            case GameWindowChanged(running=False):
                self.where = Where.CLOSED
            case GameWindowChanged() if self.where is Where.CLOSED:
                self.where = Where.MENUS
            case LobbyChanged(visible=True, button=button):
                self.where, self.button = Where.LOBBY, button
            case LobbyChanged(visible=False, button=button) if self.where is Where.LOBBY:
                # Leaving a lobby you queued from = loading into the match.
                if button in QUEUED_WORDS:
                    self._enter_match()
                else:
                    self.where = Where.MENUS
            case MatchStarted():
                self._enter_match()
            case MapDetected(map=name) if name and self.where is Where.MATCH:
                self.map = name
            case MatchEnded() if self.where is not Where.LOBBY:
                # (Not in LOBBY: the lobby itself can end a match that had no end screens.)
                self.where = Where.POSTGAME
            case ScoreboardRead(result=result, killer=killer):
                self.where, self.result, self.opponent = Where.POSTGAME, result, killer
            case _:
                pass  # role/killer/map live in the session; still a reason to re-render

    def _enter_match(self) -> None:
        self.where, self.match_start = Where.MATCH, int(self.clock())
        self.result, self.opponent, self.map = "", None, None

    # -- rendering -------------------------------------------------------------

    def _character(self) -> str | None:
        s = self.session
        if s.role is Role.KILLER:
            return s.my_killer or "Killer"
        if s.role is Role.SURVIVOR:
            return "Survivor"
        return None

    def _map(self) -> str | None:
        return self.map if self.show_map else None

    def activity(self) -> dict[str, Any] | None:
        """The SET_ACTIVITY payload; None = clear the status."""
        char = self._character()
        role_line = (f"Killer · {char}" if self.session.role is Role.KILLER else char) if char else None
        start = None
        match self.where:
            case Where.CLOSED:
                return None
            case Where.MENUS:
                details, state = "In the menus", role_line
            case Where.LOBBY:
                details = "Searching for a match" if self.button == "CANCEL" else "In the lobby"
                state = role_line
            case Where.MATCH:
                details = f"In a match as {char}" if char else "In a match"
                state, start = self._map(), self.match_start
            case Where.POSTGAME:
                details = "Match over"
                parts = [self.result.title() if self.result else None]
                if self.session.role is Role.SURVIVOR and self.opponent:
                    parts.append(f"vs {self.opponent}")
                state = " · ".join(p for p in parts if p) or self._map()
        act: dict[str, Any] = {"details": _clip(details)}
        if state:
            act["state"] = _clip(state)
        if start:
            act["timestamps"] = {"start": start}
        if self.large_image:
            act["assets"] = {"large_image": self.large_image, "large_text": "Dead by Daylight"}
        return act


RELEVANT = (GameWindowChanged, LobbyChanged, MatchStarted, MatchEnded, ScoreboardRead,
            MapDetected, RoleDetected, KillerDetected)
