"""Manual killer selection + a prompt when the scoreboard couldn't be read.

Commands:
    pick-killer          searchable list (last used killer preselected)
    set-killer <name>    e.g. `ctl set-killer trapper` (handy with rofi/wofi)
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject

from ..core.commands import CommandRouter
from ..core.events import EventBus, KillerDetected, RoleDetected, ScoreboardRead
from ..core.models import Killer, Role
from ..core.session import Session
from ..detection.text import best_match
from ..ui.picker import ListPicker
from ..ui.qt_bridge import on_main_thread

log = logging.getLogger(__name__)

SET_KILLER_MIN_SCORE = 70


class KillerSelectFeature(QObject):
    def __init__(
        self,
        bus: EventBus,
        router: CommandRouter,
        killers: tuple[Killer, ...],
        session: Session,
        notify: Callable[[str, str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.bus, self.killers, self.session, self.notify = bus, killers, session, notify
        self.picker = ListPicker("DBD Overlay: pick killer")
        self.picker.picked.connect(self._choose)
        on_main_thread(bus, ScoreboardRead, self._on_board, self)
        router.register("pick-killer", self._cmd_pick)
        router.register("set-killer", self._cmd_set, takes_arg=True)

    def _on_board(self, e: ScoreboardRead) -> None:
        if e.complete:
            you = "you played" if e.role is Role.KILLER else "you were a survivor vs."
            self.notify("Match over", f"{you} {e.killer}")
            return
        log.info("scoreboard incomplete (role=%s killer=%s); asking", e.role, e.killer)
        if e.role is Role.SURVIVOR:
            return  # survivor streak doesn't need the killer
        if e.role is Role.KILLER:
            self._open("Couldn't read your killer from the scoreboard. Which one did you play?")
        else:
            self._open("Couldn't read the scoreboard. If you played killer, which one? (Esc if you were survivor)")

    def _open(self, header: str) -> None:
        items = [(k.name, k.name) for k in sorted(self.killers, key=lambda k: k.name)]
        self.picker.open(header, items, selected=self.session.my_killer)

    def _choose(self, name: str) -> None:
        self.bus.publish(KillerDetected(name, 1.0, source="manual"))
        self.bus.publish(RoleDetected(Role.KILLER, source="manual"))

    def _cmd_pick(self) -> str:
        self._open("Which killer are you playing?")
        return "picker open"

    def _cmd_set(self, text: str) -> str:
        k, score, _ = best_match(text, self.killers, lambda k: (k.name, k.name.removeprefix("The "), *k.aliases))
        if k is None or score < SET_KILLER_MIN_SCORE:
            raise ValueError(f"no killer matches {text!r}")
        self._choose(k.name)
        return k.name
