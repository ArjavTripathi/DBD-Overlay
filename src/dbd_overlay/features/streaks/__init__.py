"""Winstreak feature: record matches, apply win rules, show the streak HUD.

Listens to: ScoreboardRead (auto-record), MatchStarted/MatchEnded (HUD
show/hide), GameWindowChanged, RoleDetected/KillerDetected (HUD category).
Commands: streak-win/-loss/-ignore/-undo/-reset/-recompute/-toggle, set-role, toggle-hud.

Each streak can be switched on/off (streak-toggle, settings window); new ones
start off. Matches are always saved; only those played while their streak
was on count toward it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QSize

from ...core.commands import CommandRouter
from ...core.config import HudConfig
from ...core.events import (
    EventBus,
    GameWindowChanged,
    KillerDetected,
    MatchEnded,
    MatchStarted,
    ResultRecorded,
    ResultsChanged,
    RoleDetected,
    ScoreboardRead,
)
from ...core.models import SURVIVOR_CATEGORY, ManualOutcome, Role, Verdict
from ...core.session import Session
from ...ui.overlay import HudWindow, load_image
from ...ui.qt_bridge import on_main_thread
from .icons import Icons
from .rules import why_unknown
from .service import StreakService
from .state import HudState

log = logging.getLogger(__name__)


class StreakFeature(QObject):
    def __init__(
        self,
        bus: EventBus,
        router: CommandRouter,
        service: StreakService,
        session: Session,
        hud: HudWindow,
        icons: Icons,
        show_mode: str,
        notify: Callable[[str, str], None],
        save_position: Callable[[tuple[int, int]], None],
        game_visible: bool = False,
        style: HudConfig | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.bus, self.svc, self.session, self.hud, self.icons = bus, service, session, hud, icons
        self.style = style or HudConfig()
        hud.set_style(self.style)
        self.notify, self.save_position = notify, save_position
        self.state = HudState(mode=show_mode, game_visible=game_visible)
        hud.edit_done.connect(lambda: self.set_editing(False))

        on_main_thread(bus, ScoreboardRead, self._on_board, self)
        on_main_thread(bus, MatchStarted, self._on_match_started, self)
        on_main_thread(bus, MatchEnded, self._on_match_ended, self)
        on_main_thread(bus, GameWindowChanged, self._on_game_window, self)
        for etype in (RoleDetected, KillerDetected, ResultsChanged):
            on_main_thread(bus, etype, lambda _: self.refresh(), self)

        for name, outcome in (("streak-win", ManualOutcome.WIN), ("streak-loss", ManualOutcome.LOSS)):
            router.register(name, lambda o=outcome: self._changed(
                self.svc.win_or_loss(o, self.session.role, self.session.my_killer)))
        router.register("streak-ignore", lambda: self._changed(self.svc.ignore_last()))
        router.register("streak-undo", lambda: self._changed(self.svc.undo()))
        router.register("streak-reset", self._cmd_reset)
        router.register("streak-toggle", self._cmd_toggle_streak)
        router.register("streak-recompute", lambda: self._changed(f"{self.svc.recompute_all()} matches changed"))
        router.register("set-role", self._cmd_set_role, takes_arg=True)
        router.register("toggle-hud", self._cmd_toggle)
        self.refresh()

    @property
    def editing(self) -> bool:
        return self.state.editing

    def streak_list(self):
        """For the settings window: known streaks, plus Survivor and your current
        killer even before they have any matches (so they can be switched on)."""
        known = self.svc.streaks()
        have = {c for c, _, _ in known}
        extra = [SURVIVOR_CATEGORY]
        if self.session.my_killer:
            extra.append(f"killer:{self.session.my_killer}")
        for cat in extra:
            if cat not in have:
                known.append((cat, self.svc.is_active(cat), self.svc.stats(cat)))
        return sorted(known, key=lambda t: (t[0] != SURVIVOR_CATEGORY, t[0]))

    def set_look(self, style: HudConfig, icons: Icons | None = None) -> None:
        """HUD look and icons; used for the live preview and on save."""
        self.style = style
        if icons is not None:
            self.icons = icons
        self.hud.set_style(style)
        self.refresh()

    def set_preview(self, on: bool) -> None:
        self.state.previewing = on
        self._apply()

    def apply_settings(self, rules, show_mode: str, history: bool, active: dict[str, bool]) -> str:
        """New win rules, HUD mode and streak on/off take effect immediately."""
        self.svc.rules = rules
        self.state.mode = show_mode
        newly_on = [c for c, on in active.items() if on and not self.svc.is_active(c)]
        for cat, on in active.items():
            self.svc.set_active(cat, on)
        # Show the streak you just switched on. Or, if the one shown is off and
        # exactly one streak is on, show that one.
        on_now = [c for c, on in active.items() if on]
        target = newly_on[0] if newly_on else None
        if target is None and self._category() not in on_now and len(on_now) == 1:
            target = on_now[0]
        if target is not None:
            self.focus(target)
        msg = "saved"
        if history:
            msg += f"; {self.svc.recompute_all()} past matches re-judged (streak-undo reverts)"
        self._changed(msg)
        self._apply()
        return msg

    # -- events --------------------------------------------------------------

    def _on_board(self, e: ScoreboardRead) -> None:
        m = self.svc.match_from_board(e, self.session.my_killer, self.session.map, self.session.realm)
        if m is None:
            self.notify("Match not recorded", "Couldn't tell your role. Use streak-win / streak-loss.")
            return
        m = self.svc.record(m)
        self.bus.publish(ResultRecorded(m.id, m.category))
        name = "Survivor" if m.category == SURVIVOR_CATEGORY else m.killer
        if not m.counted:
            self.notify(f"{name}: {m.verdict.value} (streak off)", "Not counted. streak-toggle now to count it.")
        elif m.verdict is Verdict.UNKNOWN:
            self.notify(f"{name}: needs you", why_unknown(self.svc.rules, m))
        else:
            st = self.svc.stats(m.category)
            self.notify(f"{name}: {m.verdict.value.upper()}", f"Streak {st.current} · attempt #{st.attempt}")
        self.refresh()

    def _on_match_started(self, _: MatchStarted) -> None:
        self.state.match_started()
        self._apply()

    def _on_match_ended(self, _: MatchEnded) -> None:
        self.state.match_ended()
        self._apply()

    def _on_game_window(self, e: GameWindowChanged) -> None:
        self.state.game_visible = e.visible
        self._apply()

    # -- commands --------------------------------------------------------------

    def _changed(self, msg: str) -> str:
        self.bus.publish(ResultsChanged())  # refresh() runs via the subscription
        return msg

    def focus(self, category: str) -> None:
        """Make `category` the current streak (HUD, hotkeys) by setting role/killer."""
        if category == SURVIVOR_CATEGORY:
            self.bus.publish(RoleDetected(Role.SURVIVOR, source="manual"))
        else:
            self.bus.publish(KillerDetected(category.removeprefix("killer:"), 1.0, source="manual"))
            self.bus.publish(RoleDetected(Role.KILLER, source="manual"))

    def _cmd_toggle_streak(self) -> str:
        cat = self._category()
        if cat is None:
            raise ValueError("no current streak: play a match, or set-killer / set-role first")
        return self._changed(self.svc.toggle(cat))

    def _cmd_reset(self) -> str:
        cat = self._category()
        if cat is None:
            raise ValueError("no current streak to reset")
        return self._changed(self.svc.reset(cat))

    def _cmd_set_role(self, text: str) -> str:
        role = {"killer": Role.KILLER, "survivor": Role.SURVIVOR}.get(text.strip().lower())
        if role is None:
            raise ValueError("use `set-role killer` or `set-role survivor`")
        self.bus.publish(RoleDetected(role, source="manual"))
        return role.value

    def _cmd_toggle(self) -> str:
        shown = self.state.toggle()
        self._apply()
        return "shown" if shown else "hidden"

    def set_editing(self, editing: bool) -> None:
        if editing == self.state.editing:
            return
        self.state.editing = editing
        self.hud.set_edit_mode(editing)
        if not editing:
            self.save_position(self.hud.position())
        self._apply()

    # -- view ------------------------------------------------------------------

    def _category(self) -> str | None:
        """Session's current streak, else the last recorded match's."""
        if cat := self.session.category:
            return cat
        last = self.svc.last_match()
        return last.category if last else None

    def refresh(self) -> None:
        cat = self._category()
        if cat is None:
            self.hud.show_stats("No streak yet", 0, 1, 0, "Play a match, or set-killer / set-role", None, False)
            return
        st = self.svc.stats(cat)
        if cat == SURVIVOR_CATEGORY:
            title, icon_path = self.style.survivor_title, self.icons.survivor()
        else:
            killer = cat.removeprefix("killer:")
            title = self.style.killer_title.replace("{killer}", killer.removeprefix("The "))
            icon_path = self.icons.killer(killer)
        active = self.svc.is_active(cat)
        last = self.svc.last_match()
        waiting = (last is not None and last.category == cat and last.counted and not last.ignored
                   and last.verdict is Verdict.UNKNOWN)
        prompt = why_unknown(self.svc.rules, last) if waiting else ("" if active else "Not tracking · streak-toggle to start")
        icon = load_image(icon_path, QSize(256, 256)) if icon_path else None
        self.hud.show_stats(title, st.current, st.attempt, st.best, prompt, icon, active)

    def _apply(self) -> None:
        self.hud.set_shown(self.state.shown)
