"""Named commands (hotkeys, tray menu, CLI) routed to handlers.

Every input path ends here: Hyprland `bind` -> `dbd-overlay ctl streak-win`
-> socket -> CommandRouter.dispatch("streak-win"). On Windows a global-hotkey
provider will call the same dispatch(), so features never know where a
command came from.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

# The public command set. Features register handlers for these.
COMMANDS: dict[str, str] = {
    "ping": "check that the app is running",
    "toggle-overlay": "show/hide the map overlay",
    "pick-map": "choose the map manually",
    "set-map": "set the map by (partial) name, e.g. `ctl set-map pale rose`",
    "pick-killer": "choose your killer manually",
    "streak-win": "record a win for the current category",
    "streak-loss": "record a loss",
    "streak-ignore": "mark the last match as ignored",
    "streak-undo": "undo the last recorded result",
    "edit-hud": "toggle drag/resize mode for overlay and HUD",
    "quit": "exit the app",
}

# A handler returns an optional message for the caller; raising = error reply.
# Handlers registered with takes_arg=True receive the rest of the line.
CommandHandler = Callable[..., str | None]


class CommandRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[CommandHandler, bool]] = {}

    def register(self, name: str, handler: CommandHandler, takes_arg: bool = False) -> None:
        if name not in COMMANDS:
            raise ValueError(f"unknown command {name!r}; add it to COMMANDS first")
        self._handlers[name] = (handler, takes_arg)

    def dispatch(self, line: str) -> str:
        """Run 'name [argument...]'; always returns a one-line reply starting with 'ok' or 'error'."""
        name, _, arg = line.strip().partition(" ")
        arg = arg.strip()
        if name not in COMMANDS:
            return f"error: unknown command {name!r}"
        if name not in self._handlers:
            return f"error: {name} is not available yet"
        handler, takes_arg = self._handlers[name]
        if arg and not takes_arg:
            return f"error: {name} takes no argument"
        if takes_arg and not arg:
            return f"error: {name} needs an argument"
        try:
            msg = handler(arg) if takes_arg else handler()
        except Exception as e:
            log.exception("command %s failed", name)
            return f"error: {e}"
        log.info("command %s -> ok%s", name, f" ({msg})" if msg else "")
        return f"ok: {msg}" if msg else "ok"
