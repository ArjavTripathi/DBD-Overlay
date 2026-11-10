"""System tray icon. Left-click opens settings, right-click shows the menu.
Menu items go through the CommandRouter, same as hotkeys.

On Hyprland the tray needs a StatusNotifier host, e.g. waybar's `tray` module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

log = logging.getLogger(__name__)


def _make_icon() -> QIcon:
    """Drawn at runtime so the repo ships no game art."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#8b0000"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 60, 60)
    p.setPen(QColor("white"))
    p.setFont(QFont("Sans", 30, QFont.Weight.Bold))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "D")
    p.end()
    return QIcon(pm)


MENU: list[tuple[str, str] | None] = [  # (label, command); None = separator
    ("Toggle map overlay", "toggle-overlay"),
    ("Pick map…", "pick-map"),
    ("Pick killer…", "pick-killer"),
    ("Edit HUD layout", "edit-hud"),
    ("Toggle Discord status", "toggle-discord"),
    None,
    ("Record win", "streak-win"),
    ("Record loss", "streak-loss"),
    ("Ignore last match", "streak-ignore"),
    ("Undo last result", "streak-undo"),
    None,
    ("Settings…", "settings"),
    ("Quit", "quit"),
]


class Tray(QObject):
    def __init__(self, dispatch: Callable[[str], str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dispatch = dispatch
        self.icon = QSystemTrayIcon(_make_icon(), self)
        self.icon.setToolTip("DBD Overlay")
        menu = QMenu()
        for item in MENU:
            if item is None:
                menu.addSeparator()
                continue
            label, cmd = item
            act = QAction(label, menu)
            act.triggered.connect(lambda _=False, c=cmd: self._run(c))
            menu.addAction(act)
        self._menu = menu  # keep a Python reference or Qt may free it
        self.icon.setContextMenu(menu)  # right-click
        # Left-click: open settings (most bars send "activate" on left-click).
        self.icon.activated.connect(self._on_activated)

    def show(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("no system tray found (on Hyprland, enable waybar's tray module); use hotkeys/CLI")
        self.icon.show()

    def notify(self, title: str, msg: str) -> None:
        self.icon.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 4000)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._run("settings")

    def _run(self, cmd: str) -> None:
        reply = self._dispatch(cmd)
        if reply.startswith("error"):
            self.notify("DBD Overlay", reply)
