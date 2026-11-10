"""Settings window: win conditions (+ HUD mode). Edits a copy of the config;
the app applies and saves it when the user clicks a Save button."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.config import HudConfig, StreakConfig
from ..features.streaks.rules import Rules, describe_killer, describe_survivor

KILLER_PRESETS = [("4k", "4k: all four"), ("3k_hatch", "3k + hatch"), ("3k_any", "3k: last one may escape"),
                  ("custom", "Custom")]
SURVIVOR_PRESETS = [("i_escape", "I escape"), ("3_out", "3 out (SWF)"), ("4_out", "4 out (SWF)"),
                    ("custom", "Custom")]
HUD_MODES = [("match_end", "Between matches"), ("always", "Always"), ("hotkey", "Only on toggle-hud")]


def _combo(options: list[tuple[str, str]], current: str) -> QComboBox:
    c = QComboBox()
    for value, label in options:
        c.addItem(label, value)
    c.setCurrentIndex(max(0, c.findData(current)))
    return c


def _streak_label(category: str, stats) -> str:
    name = "Survivor" if category == "survivor" else category.removeprefix("killer:")
    return f"{name}   (streak {stats.current}, attempt #{stats.attempt}, best {stats.best})"


class SettingsWindow(QWidget):
    # (new streak config, new hud show mode, apply to history?, {category: on?})
    saved = Signal(object, str, bool, dict)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("DBD Overlay: settings")
        self.setMinimumWidth(520)
        self._layout = QVBoxLayout(self)
        # Never smaller than the contents (word-wrapped labels need this).
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

    def open(self, streaks: StreakConfig, hud: HudConfig, streak_list: list | None = None) -> None:
        """(Re)build the form from the current config and show it."""
        while (item := self._layout.takeAt(0)) is not None:
            if w := item.widget():
                w.deleteLater()
        self._base = dataclasses.replace(streaks)

        # Killer
        kbox, kform = QGroupBox("Killer win condition"), QFormLayout()
        self.k_preset = _combo(KILLER_PRESETS, streaks.killer_preset)
        self.k_required = QSpinBox(minimum=0, maximum=4, value=streaks.custom_killer_required)
        self.k_hatch = QCheckBox("A hatch escape counts as removed", checked=streaks.custom_killer_count_hatch)
        self.k_dc = QCheckBox("A disconnect counts as a kill", checked=streaks.dc_counts_as_kill)
        kform.addRow("Preset", self.k_preset)
        kform.addRow("Survivors to remove", self.k_required)
        kform.addRow("", self.k_hatch)
        kform.addRow("", self.k_dc)
        self.k_text = QLabel(wordWrap=True)
        kbox.setLayout(self._with_text(kform, self.k_text))

        # Survivor
        sbox, sform = QGroupBox("Survivor win condition"), QFormLayout()
        self.s_preset = _combo(SURVIVOR_PRESETS, streaks.survivor_preset)
        self.s_self = QCheckBox("You must escape", checked=streaks.custom_survivor_self_escape)
        self.s_min = QSpinBox(minimum=0, maximum=4, value=streaks.custom_survivor_min_escapes)
        sform.addRow("Preset", self.s_preset)
        sform.addRow("", self.s_self)
        sform.addRow("Survivors out (incl. you)", self.s_min)
        self.s_text = QLabel(wordWrap=True)
        sbox.setLayout(self._with_text(sform, self.s_text))

        # Which streaks are being done right now
        lbox, lvbox = QGroupBox("Streaks you're doing (only these count)"), QVBoxLayout()
        self.streak_items = QListWidget()
        for category, on, stats in streak_list or []:
            item = QListWidgetItem(_streak_label(category, stats))
            item.setData(Qt.ItemDataRole.UserRole, category)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            self.streak_items.addItem(item)
        rows = max(1, min(self.streak_items.count(), 6))
        self.streak_items.setFixedHeight(rows * self.streak_items.sizeHintForRow(0) + 6 if self.streak_items.count() else 30)
        hint = QLabel("Not ticked = matches are saved but don't count. New killers start unticked. "
                      "Hotkey: streak-toggle (right after a match it also counts that match).", wordWrap=True)
        hint.setStyleSheet("color: gray")
        lvbox.addWidget(self.streak_items)
        lvbox.addWidget(hint)
        lbox.setLayout(lvbox)

        # HUD
        hbox, hform = QGroupBox("Streak HUD"), QFormLayout()
        self.hud_mode = _combo(HUD_MODES, hud.show)
        hform.addRow("Show", self.hud_mode)
        hbox.setLayout(hform)

        note = QLabel("Surrenders always count as kills. Matches the scoreboard can't decide "
                      "(e.g. hatch vs gate) ask you on the HUD instead of guessing.", wordWrap=True)
        note.setStyleSheet("color: gray")

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        save = QPushButton("Save (from now on)")
        save_all = QPushButton("Save && apply to history")
        save_all.setToolTip("Re-judge every recorded match with these rules (undo with streak-undo)")
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(save)
        buttons.addWidget(save_all)
        cancel.clicked.connect(self.hide)
        save.clicked.connect(lambda: self._save(False))
        save_all.clicked.connect(lambda: self._save(True))

        for w in (lbox, kbox, sbox, hbox, note):
            self._layout.addWidget(w)
        self._layout.addLayout(buttons)

        for w in (self.k_preset, self.s_preset):
            w.currentIndexChanged.connect(self._update)
        for w in (self.k_required, self.s_min):
            w.valueChanged.connect(self._update)
        for w in (self.k_hatch, self.k_dc, self.s_self):
            w.toggled.connect(self._update)
        self._update()
        self.show()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _with_text(form: QFormLayout, text: QLabel) -> QVBoxLayout:
        """Form + a wrapping description below it (labels in form rows don't wrap)."""
        text.setStyleSheet("font-weight: bold")
        box = QVBoxLayout()
        box.addLayout(form)
        box.addWidget(text)
        return box

    def config(self) -> StreakConfig:
        return dataclasses.replace(
            self._base,
            killer_preset=self.k_preset.currentData(),
            survivor_preset=self.s_preset.currentData(),
            dc_counts_as_kill=self.k_dc.isChecked(),
            custom_killer_required=self.k_required.value(),
            custom_killer_count_hatch=self.k_hatch.isChecked(),
            custom_survivor_self_escape=self.s_self.isChecked(),
            custom_survivor_min_escapes=self.s_min.value(),
        )

    def _update(self) -> None:
        cfg = self.config()
        k_custom, s_custom = cfg.killer_preset == "custom", cfg.survivor_preset == "custom"
        rules = Rules.from_config(cfg)
        # Greyed-out fields show what the preset means; picking "Custom" then
        # starts from those values.
        if not k_custom:
            self._quietly(self.k_required.setValue, rules.killer.required)
            self._quietly(self.k_hatch.setChecked, rules.killer.count_hatch)
        if not s_custom:
            self._quietly(self.s_self.setChecked, rules.survivor.self_escape)
            self._quietly(self.s_min.setValue, rules.survivor.min_escapes)
        for w in (self.k_required, self.k_hatch):
            w.setEnabled(k_custom)
        for w in (self.s_self, self.s_min):
            w.setEnabled(s_custom)
        self.k_text.setText(describe_killer(rules.killer))
        self.s_text.setText(describe_survivor(rules.survivor))
        self._fit()

    def _fit(self) -> None:
        """Qt sizes the window before word-wrapped labels know their width, so
        it under-estimates their height. Give every wrapped label its real
        wrapped height, then let the window grow to fit."""
        width = max(self.width(), self.minimumWidth()) - 60
        for label in self.findChildren(QLabel):
            if label.wordWrap():
                label.setMinimumHeight(label.heightForWidth(width))
        self.adjustSize()

    @staticmethod
    def _quietly(setter, value) -> None:
        """Set a widget value without firing its change signal (no update loop)."""
        widget = setter.__self__
        old = widget.blockSignals(True)
        setter(value)
        widget.blockSignals(old)

    def active_states(self) -> dict[str, bool]:
        items = (self.streak_items.item(i) for i in range(self.streak_items.count()))
        return {it.data(Qt.ItemDataRole.UserRole): it.checkState() == Qt.CheckState.Checked for it in items}

    def _save(self, history: bool) -> None:
        self.hide()
        self.saved.emit(self.config(), self.hud_mode.currentData(), history, self.active_states())
