"""Settings window: streaks on/off, win rules, HUD look, icons, Discord status.

Edits a copy of the config. HUD and icon changes are previewed live on the
real HUD (`preview` signal); Cancel/close reverts (`closed`), Save emits
`saved` with the new config and the app applies + writes it.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.config import Config, DiscordConfig, HudConfig, IconsConfig, StreakConfig
from ..features.streaks.icons import Icons
from ..features.streaks.rules import Rules, describe_killer, describe_survivor
from .overlay import load_image

KILLER_PRESETS = [("4k", "4k: all four"), ("3k_hatch", "3k + hatch"), ("3k_any", "3k: last one may escape"),
                  ("custom", "Custom")]
SURVIVOR_PRESETS = [("i_escape", "I escape"), ("3_out", "3 out (SWF)"), ("4_out", "4 out (SWF)"),
                    ("custom", "Custom")]
HUD_MODES = [("match_end", "Between matches"), ("always", "Always"), ("hotkey", "Only on toggle-hud")]
HUD_LAYOUTS = [("card", "Card: icon, title, numbers"), ("compact", "Compact: icon + streak")]
PAGES = [("Streaks", "Which streaks you're going for right now"),
         ("Win rules", "What counts as a win"),
         ("HUD", "How the streak HUD looks. Changes preview live on screen"),
         ("Icons", "Pictures shown on the HUD for each streak"),
         ("Discord", "Show lobby, match, character and map as your Discord status")]
IMAGE_FILTER = "Images (*.png *.webp *.jpg *.jpeg)"

ACCENT = "#c8283c"
ICONS = (Path(__file__).parent / "icons").as_posix()
LABEL_WIDTH = 200
STYLE = f"""
QWidget#settings {{ background: #141418; }}
QWidget {{ color: #e4e4e8; font-size: 13px; }}
QLabel#pageTitle {{ font-size: 20px; font-weight: 700; }}
QLabel#muted, QLabel#hint {{ color: #8b8b96; }}
QLabel#cardTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#rule {{ color: #f0d070; font-weight: 600; }}
QListWidget#nav {{ background: #0e0e11; border: none; border-right: 1px solid #24242b; padding: 10px 6px; outline: 0; }}
QListWidget#nav::item {{ padding: 9px 12px; border-radius: 6px; margin: 1px 0; color: #b4b4bd; }}
QListWidget#nav::item:selected {{ background: #26262e; color: white; border-left: 3px solid {ACCENT}; }}
QListWidget#nav::item:hover:!selected {{ background: #1b1b21; }}
QFrame#card {{ background: #1c1c22; border: 1px solid #2a2a32; border-radius: 10px; }}
QFrame#card QLabel {{ background: transparent; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QComboBox, QSpinBox, QLineEdit {{
    background: #24242b; border: 1px solid #34343d; border-radius: 6px; padding: 5px 8px; min-height: 18px; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox:disabled, QSpinBox:disabled {{ color: #6a6a73; background: #1d1d22; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({ICONS}/chevron-down.svg); width: 12px; height: 12px; }}
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; background: transparent; width: 20px; }}
QSpinBox::up-arrow {{ image: url({ICONS}/chevron-up.svg); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({ICONS}/chevron-down.svg); width: 10px; height: 10px; }}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled, QComboBox::down-arrow:disabled {{ image: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #34343d; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a4a55; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QComboBox QAbstractItemView {{ background: #24242b; selection-background-color: {ACCENT}; border: 1px solid #34343d; }}
QPushButton {{ background: #2a2a32; border: 1px solid #3a3a44; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ background: #33333c; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #dc3349; }}
QPushButton#flat {{ background: transparent; border: none; color: #b4b4bd; }}
QPushButton#flat:hover {{ color: white; }}
QSlider::groove:horizontal {{ height: 4px; background: #34343d; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; margin: -6px 0; border-radius: 7px; }}
QListWidget#iconList {{ background: #1c1c22; border: 1px solid #2a2a32; border-radius: 10px; padding: 4px; outline: 0; }}
QListWidget#iconList::item {{ padding: 4px; border-radius: 6px; }}
QListWidget#iconList::item:selected {{ background: #2e2e37; color: white; }}
QWidget#footer {{ background: #101013; border-top: 1px solid #24242b; }}
"""


# -- small widgets -------------------------------------------------------------

class Toggle(QAbstractButton):
    """An on/off switch (a checkbox that looks like one)."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(40, 22)

    def paintEvent(self, _) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on, enabled = self.isChecked(), self.isEnabled()
        track = QColor(ACCENT if on else "#3a3a44")
        if not enabled:
            track.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor("white" if enabled else "#9a9aa3"))
        p.drawEllipse(QRectF(21 if on else 3, 3, 16, 16))


class ColorButton(QPushButton):
    """Shows a colour swatch; click to pick a new one."""

    changed = Signal()

    def __init__(self, color: str) -> None:
        super().__init__()
        self.setFixedWidth(110)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color: str) -> None:
        self.color = color.lower()
        pm = QPixmap(14, 14)
        pm.fill(QColor(self.color))
        self.setIcon(QIcon(pm))
        self.setText(self.color)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self.window(), "Pick a colour")
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit()


def _combo(options: list[tuple[str, str]], current: str) -> QComboBox:
    c = QComboBox()
    for value, label in options:
        c.addItem(label, value)
    c.setCurrentIndex(max(0, c.findData(current)))
    return c


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    if name:
        lab.setObjectName(name)
    return lab


def _card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    box = QVBoxLayout(frame)
    box.setContentsMargins(16, 14, 16, 14)
    box.setSpacing(10)
    if title:
        box.addWidget(_label(title, "cardTitle"))
    return frame, box


class _Form(QFormLayout):
    """Form whose labels share one width, so cards line up."""

    def addRow(self, label, field=None):  # noqa: N802 (Qt API)
        if isinstance(label, str) and field is not None:
            lab = QLabel(label)
            lab.setFixedWidth(LABEL_WIDTH)
            lab.setWordWrap(True)
            return super().addRow(lab, field)
        return super().addRow(label, field) if field is not None else super().addRow(label)


def _form() -> QFormLayout:
    f = _Form()
    f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    f.setHorizontalSpacing(18)
    f.setVerticalSpacing(10)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
    return f


def _slider(lo: int, hi: int, value: float, suffix: str = "%") -> tuple[QWidget, QSlider]:
    """Slider + live value label."""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(round(value))
    s.setFixedWidth(200)
    val = QLabel()
    val.setFixedWidth(44)
    val.setObjectName("muted")
    s.valueChanged.connect(lambda v: val.setText(f"{v}{suffix}"))
    val.setText(f"{s.value()}{suffix}")
    row.addWidget(s)
    row.addWidget(val)
    row.addStretch()
    return w, s


def _scroll(page: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(page)
    return area


def _thumb(path: Path | None, size: int, name: str = "") -> QPixmap:
    img = load_image(path, QSize(size * 2, size * 2)) if path else None
    if img is None:  # placeholder: rounded tile with the initial
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2a2a32"))
        p.drawRoundedRect(QRectF(0, 0, size, size), size / 6, size / 6)
        initial = name.removeprefix("The ")[:1].upper()
        if initial:
            f = p.font()
            f.setPixelSize(round(size * 0.45))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#6e6e7a"))
            p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, initial)
        p.end()
        return pm
    return QPixmap.fromImage(img).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)


def _streak_name(category: str) -> str:
    return "Survivor" if category == "survivor" else category.removeprefix("killer:")


# -- the window ----------------------------------------------------------------

class SettingsWindow(QWidget):
    # (new config copy, re-judge history?, {category: on?})
    saved = Signal(object, bool, dict)
    # Live preview of (HudConfig, IconsConfig) on the real HUD.
    preview = Signal(object, object)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName("settings")
        self.setWindowTitle("DBD Overlay: settings")
        self.setStyleSheet(STYLE)
        self.resize(860, 640)
        self.setMinimumSize(760, 520)
        self._open = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(170)
        brand = QListWidgetItem("DBD OVERLAY")
        brand.setFlags(Qt.ItemFlag.NoItemFlags)
        f = brand.font()
        f.setBold(True)
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 1.5)
        brand.setFont(f)
        brand.setForeground(QColor(ACCENT))
        self.nav.addItem(brand)
        for name, _ in PAGES:
            self.nav.addItem(QListWidgetItem(name))
        root.addWidget(self.nav)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        head = QVBoxLayout()
        head.setContentsMargins(28, 22, 28, 10)
        self.page_title = _label("", "pageTitle")
        self.page_sub = _label("", "muted")
        head.addWidget(self.page_title)
        head.addWidget(self.page_sub)
        right.addLayout(head)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)

        footer = QWidget()
        footer.setObjectName("footer")
        fb = QHBoxLayout(footer)
        fb.setContentsMargins(20, 12, 20, 12)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("flat")
        self.save_all = QPushButton("Save && re-judge history")
        self.save_all.setToolTip("Re-judge every recorded match with these rules (undo with streak-undo)")
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.setDefault(True)
        fb.addWidget(cancel)
        fb.addStretch()
        fb.addWidget(self.save_all)
        fb.addWidget(save)
        right.addWidget(footer)
        root.addLayout(right, 1)

        cancel.clicked.connect(self.close)
        save.clicked.connect(lambda: self._save(False))
        self.save_all.clicked.connect(lambda: self._save(True))
        self.nav.currentRowChanged.connect(self._show_page)

    # -- building ------------------------------------------------------------

    def open(self, cfg: Config, streak_list: list | None = None, killers: list[str] | None = None,
             icons: Icons | None = None, run_command: Callable[[str], object] | None = None) -> None:
        """(Re)build every page from the current config and show the window."""
        self._cfg = copy.deepcopy(cfg)
        self._icons = icons.with_overrides(cfg.icons) if icons else None
        self._killers = sorted(killers or [], key=lambda k: k.removeprefix("The "))
        self._run = run_command or (lambda _: None)
        self._streak_list = streak_list or []

        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        for page in (self._streaks_page(), self._rules_page(), self._hud_page(), self._icons_page(),
                     self._discord_page()):
            self.stack.addWidget(_scroll(page))

        self._update_rules()
        self._open = True
        if self.nav.currentRow() < 1:
            self.nav.setCurrentRow(1)
        else:
            self._show_page(self.nav.currentRow())
        self.show()
        self.raise_()
        self.activateWindow()

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        box = QVBoxLayout(w)
        box.setContentsMargins(28, 8, 28, 24)
        box.setSpacing(14)
        return w, box

    def _streaks_page(self) -> QWidget:
        page, box = self._page()
        card, cbox = _card()
        cbox.setSpacing(0)
        self.streak_toggles: dict[str, Toggle] = {}
        for i, (category, on, stats) in enumerate(self._streak_list):
            if i:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet("color: #2a2a32")
                cbox.addWidget(line)
            row = QHBoxLayout()
            row.setContentsMargins(0, 8, 0, 8)
            row.setSpacing(12)
            pic = QLabel()
            pic.setPixmap(_thumb(self._icons.source(category)[0] if self._icons else None, 36, _streak_name(category)))
            pic.setFixedSize(36, 36)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(_label(_streak_name(category), "cardTitle", wrap=False))
            text.addWidget(_label(f"Streak {stats.current}   ·   Attempt #{stats.attempt}   ·   Best {stats.best}",
                                  "muted", wrap=False))
            toggle = Toggle(on)
            self.streak_toggles[category] = toggle
            row.addWidget(pic)
            row.addLayout(text, 1)
            row.addWidget(toggle)
            cbox.addLayout(row)
        if not self._streak_list:
            cbox.addWidget(_label("No streaks yet: play a match or pick a killer.", "muted"))
        box.addWidget(card)
        box.addWidget(_label("Off = matches are still saved but don't count, like a pause. New killers start off. "
                             "Hotkey streak-toggle flips the current one (right after a match it also counts "
                             "that match).", "hint"))
        box.addStretch()
        return page

    def _rules_page(self) -> QWidget:
        page, box = self._page()
        s = self._cfg.streaks

        kcard, kbox = _card("Killer")
        kform = _form()
        self.k_preset = _combo(KILLER_PRESETS, s.killer_preset)
        self.k_required = QSpinBox(minimum=0, maximum=4, value=s.custom_killer_required)
        self.k_hatch = Toggle(s.custom_killer_count_hatch)
        self.k_dc = Toggle(s.dc_counts_as_kill)
        kform.addRow("Preset", self.k_preset)
        kform.addRow("Survivors to remove", self.k_required)
        kform.addRow("Hatch escape counts as removed", self.k_hatch)
        kform.addRow("Disconnect counts as a kill", self.k_dc)
        kbox.addLayout(kform)
        self.k_text = _label("", "rule")
        kbox.addWidget(self.k_text)

        scard, sbox = _card("Survivor")
        sform = _form()
        self.s_preset = _combo(SURVIVOR_PRESETS, s.survivor_preset)
        self.s_self = Toggle(s.custom_survivor_self_escape)
        self.s_min = QSpinBox(minimum=0, maximum=4, value=s.custom_survivor_min_escapes)
        sform.addRow("Preset", self.s_preset)
        sform.addRow("You must escape", self.s_self)
        sform.addRow("Survivors out (incl. you)", self.s_min)
        sbox.addLayout(sform)
        self.s_text = _label("", "rule")
        sbox.addWidget(self.s_text)

        box.addWidget(kcard)
        box.addWidget(scard)
        box.addWidget(_label("Surrenders always count as kills. When the scoreboard can't decide (e.g. hatch vs "
                             "gate) the HUD asks you instead of guessing. Pick a preset to see its settings; "
                             "Custom starts from them.", "hint"))
        box.addStretch()

        for w in (self.k_preset, self.s_preset):
            w.currentIndexChanged.connect(self._update_rules)
        for w in (self.k_required, self.s_min):
            w.valueChanged.connect(self._update_rules)
        for w in (self.k_hatch, self.k_dc, self.s_self):
            w.toggled.connect(self._update_rules)
        return page

    def _hud_page(self) -> QWidget:
        page, box = self._page()
        h = self._cfg.hud

        vcard, vbox = _card("When and where")
        vform = _form()
        self.hud_mode = _combo(HUD_MODES, h.show)
        vform.addRow("Show", self.hud_mode)
        vbox.addLayout(vform)
        move = QPushButton("Move it on screen…")
        move.setToolTip("Same as the edit-hud hotkey: drag the HUD, Esc to lock")
        move.clicked.connect(lambda: self._run("edit-hud"))
        row = QHBoxLayout()
        row.addWidget(move)
        row.addStretch()
        vbox.addLayout(row)

        lcard, lbox = _card("Layout")
        lform = _form()
        self.h_layout = _combo(HUD_LAYOUTS, h.layout)
        self.h_icon = Toggle(h.show_icon)
        self.h_title = Toggle(h.show_title)
        self.h_attempt = Toggle(h.show_attempt)
        self.h_best = Toggle(h.show_best)
        self.h_icon_size = QSpinBox(minimum=16, maximum=256, value=h.icon_size, suffix=" px")
        lform.addRow("Layout", self.h_layout)
        lform.addRow("Icon", self.h_icon)
        lform.addRow("Icon size", self.h_icon_size)
        lform.addRow("Title", self.h_title)
        lform.addRow("Attempt #", self.h_attempt)
        lform.addRow("Best", self.h_best)
        lbox.addLayout(lform)

        scard, sbox = _card("Size and colours")
        sform = _form()
        scale_w, self.h_scale = _slider(50, 300, h.scale * 100)
        opacity_w, self.h_opacity = _slider(5, 100, h.opacity * 100)
        bg_w, self.h_bg_opacity = _slider(0, 100, h.background_opacity * 100)
        self.h_text_color = ColorButton(h.text_color)
        self.h_accent = ColorButton(h.accent)
        self.h_background = ColorButton(h.background)
        self.h_border = Toggle(h.border)
        self.h_radius = QSpinBox(minimum=0, maximum=40, value=h.corner_radius, suffix=" px")
        self.h_font = QComboBox()
        self.h_font.addItem("System default", "")
        for fam in QFontDatabase.families():
            self.h_font.addItem(fam, fam)
        self.h_font.setCurrentIndex(max(0, self.h_font.findData(h.font)))
        self.h_font.setMaxVisibleItems(16)
        sform.addRow("Size", scale_w)
        sform.addRow("Opacity", opacity_w)
        sform.addRow("Text", self.h_text_color)
        sform.addRow("Highlight", self.h_accent)
        sform.addRow("Background", self.h_background)
        sform.addRow("Background opacity", bg_w)
        sform.addRow("Border", self.h_border)
        sform.addRow("Corner radius", self.h_radius)
        sform.addRow("Font", self.h_font)
        sbox.addLayout(sform)

        tcard, tbox = _card("Titles")
        tform = _form()
        tform.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.h_survivor_title = QLineEdit(h.survivor_title)
        self.h_killer_title = QLineEdit(h.killer_title)
        self.h_killer_title.setToolTip("{killer} becomes the killer's name, e.g. Hillbilly")
        tform.addRow("Survivor", self.h_survivor_title)
        tform.addRow("Killer", self.h_killer_title)
        tbox.addLayout(tform)
        tbox.addWidget(_label("{killer} is replaced by the killer's name.", "hint"))

        reset = QPushButton("Reset look to defaults")
        reset.clicked.connect(self._reset_hud)
        row = QHBoxLayout()
        row.addWidget(reset)
        row.addStretch()

        for w in (vcard, lcard, scard, tcard):
            box.addWidget(w)
        box.addLayout(row)
        box.addStretch()

        for w in (self.h_layout, self.h_font):
            w.currentIndexChanged.connect(self._emit_preview)
        for w in (self.h_icon, self.h_title, self.h_attempt, self.h_best, self.h_border):
            w.toggled.connect(self._emit_preview)
        for w in (self.h_icon_size, self.h_radius, self.h_scale, self.h_opacity, self.h_bg_opacity):
            w.valueChanged.connect(self._emit_preview)
        for w in (self.h_text_color, self.h_accent, self.h_background):
            w.changed.connect(self._emit_preview)
        for w in (self.h_survivor_title, self.h_killer_title):
            w.textChanged.connect(self._emit_preview)
        self.h_layout.currentIndexChanged.connect(self._update_hud_enabled)
        self._update_hud_enabled()
        return page

    def _icons_page(self) -> QWidget:
        page, box = self._page()
        row = QHBoxLayout()
        row.setSpacing(16)
        self.icon_list = QListWidget()
        self.icon_list.setObjectName("iconList")
        self.icon_list.setIconSize(QSize(32, 32))
        self.icon_list.setFixedWidth(260)
        self.icon_list.setMinimumHeight(300)
        for category in ["survivor", *(f"killer:{k}" for k in self._killers)]:
            item = QListWidgetItem(_streak_name(category))
            item.setData(Qt.ItemDataRole.UserRole, category)
            self.icon_list.addItem(item)
        row.addWidget(self.icon_list)

        detail, dbox = _card()
        dbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(128, 128)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_name = _label("", "cardTitle")
        self.icon_source = _label("", "muted")
        choose = QPushButton("Choose image…")
        choose.setObjectName("primary")
        self.icon_clear = QPushButton("Use default")
        buttons = QHBoxLayout()
        buttons.addWidget(choose)
        buttons.addWidget(self.icon_clear)
        buttons.addStretch()
        dbox.addWidget(self.icon_preview)
        dbox.addWidget(self.icon_name)
        dbox.addWidget(self.icon_source)
        dbox.addLayout(buttons)
        folder = str(self._icons.dir if self._icons else Path("assets/icons")).replace(str(Path.home()), "~")
        dbox.addWidget(_label(f"PNG, WebP or JPG; square looks best. \"Use default\" goes back to the files in "
                              f"{folder}/ (survivor.png, killers/Hillbilly.png …), if any.", "hint"))
        row.addWidget(detail, 1, Qt.AlignmentFlag.AlignTop)
        box.addLayout(row, 1)

        self.icon_list.currentRowChanged.connect(lambda _: self._show_icon())
        choose.clicked.connect(self._choose_icon)
        self.icon_clear.clicked.connect(lambda: self._set_icon(""))
        self._refresh_icon_list()
        self.icon_list.setCurrentRow(0)
        return page

    def _discord_page(self) -> QWidget:
        page, box = self._page()
        d = self._cfg.discord
        card, cbox = _card()
        form = _form()
        self.d_enabled = Toggle(d.enabled)
        self.d_client = QLineEdit(d.client_id)
        self.d_client.setPlaceholderText("Application ID, e.g. 1234567890123456789")
        self.d_image = QLineEdit(d.large_image)
        self.d_image.setPlaceholderText("optional: art asset key or https:// URL")
        self.d_map = Toggle(d.show_map)
        form.addRow("Show status in Discord", self.d_enabled)
        form.addRow("Client ID", self.d_client)
        form.addRow("Large image", self.d_image)
        form.addRow("Show the map during a match", self.d_map)
        cbox.addLayout(form)
        self.d_error = _label("", "hint")
        self.d_error.setStyleSheet(f"color: {ACCENT}")
        cbox.addWidget(self.d_error)
        box.addWidget(card)
        box.addWidget(_label(
            "Needs the Discord desktop app on this computer and your own Discord application: "
            "discord.com/developers/applications > New Application. Its name is what Discord shows after "
            "\"Playing\" (e.g. \"Dead by Daylight\"); copy its Application ID here. If Discord also shows "
            "the game on its own, turn that off in Discord > Settings > Registered Games. "
            "Hotkey: toggle-discord.", "hint"))
        box.addStretch()
        self.d_client.textChanged.connect(self._check_discord)
        self.d_enabled.toggled.connect(self._check_discord)
        self._check_discord()
        return page

    def _check_discord(self) -> None:
        cid = self.d_client.text().strip()
        if cid and not cid.isdigit():
            self.d_error.setText("The client ID is a number (Application ID, not the app name or secret).")
        elif self.d_enabled.isChecked() and not cid:
            self.d_error.setText("Enter a client ID to turn this on.")
        else:
            self.d_error.setText("")

    # -- behaviour -------------------------------------------------------------

    def _show_page(self, row: int) -> None:
        if row < 1:  # the brand line isn't a page
            self.nav.setCurrentRow(1)
            return
        i = row - 1
        self.stack.setCurrentIndex(i)
        self.page_title.setText(PAGES[i][0])
        self.page_sub.setText(PAGES[i][1])
        self.save_all.setVisible(PAGES[i][0] == "Win rules")
        self._emit_preview()

    def _current_category(self) -> str | None:
        item = self.icon_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _refresh_icon_list(self) -> None:
        if not self._icons:
            return
        for i in range(self.icon_list.count()):
            item = self.icon_list.item(i)
            cat = item.data(Qt.ItemDataRole.UserRole)
            item.setIcon(QIcon(_thumb(self._icons.source(cat)[0], 32, _streak_name(cat))))

    def _show_icon(self) -> None:
        cat = self._current_category()
        if cat is None or not self._icons:
            return
        path, where = self._icons.source(cat)
        self.icon_preview.setPixmap(_thumb(path, 128, _streak_name(cat)))
        self.icon_name.setText(_streak_name(cat))
        if where == "custom":
            text = f"Custom: {str(path).replace(str(Path.home()), '~')}"
        elif where == "assets":
            text = f"From the assets folder: {path.name}"
        else:
            text = "No icon yet"
        self.icon_source.setText(text)
        self.icon_clear.setEnabled(where == "custom")

    def _choose_icon(self) -> None:
        cat = self._current_category()
        if cat is None:
            return
        start = str(self._icons.dir) if self._icons and self._icons.dir.is_dir() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, f"Icon for {_streak_name(cat)}", start, IMAGE_FILTER)
        if path:
            self._set_icon(path)

    def _set_icon(self, path: str) -> None:
        cat = self._current_category()
        if cat is None or not self._icons:
            return
        self._icons.set(cat, path)
        row = self.icon_list.currentRow()
        item = self.icon_list.item(row)
        item.setIcon(QIcon(_thumb(self._icons.source(cat)[0], 32, _streak_name(cat))))
        self._show_icon()
        self._emit_preview()

    def _update_hud_enabled(self) -> None:
        card = self.h_layout.currentData() == "card"
        for w in (self.h_title, self.h_attempt, self.h_best, self.h_survivor_title, self.h_killer_title):
            w.setEnabled(card)

    def _reset_hud(self) -> None:
        d = HudConfig()
        self._quietly(self.h_layout.setCurrentIndex, self.h_layout.findData(d.layout))
        for t, v in ((self.h_icon, d.show_icon), (self.h_title, d.show_title), (self.h_attempt, d.show_attempt),
                     (self.h_best, d.show_best), (self.h_border, d.border)):
            self._quietly(t.setChecked, v)
        for s, v in ((self.h_icon_size, d.icon_size), (self.h_radius, d.corner_radius),
                     (self.h_scale, round(d.scale * 100)), (self.h_opacity, round(d.opacity * 100)),
                     (self.h_bg_opacity, round(d.background_opacity * 100))):
            s.setValue(v)  # fires previews; fine, and keeps slider labels in sync
        for b, v in ((self.h_text_color, d.text_color), (self.h_accent, d.accent), (self.h_background, d.background)):
            b.set_color(v)
        self._quietly(self.h_font.setCurrentIndex, 0)
        self._quietly(self.h_survivor_title.setText, d.survivor_title)
        self._quietly(self.h_killer_title.setText, d.killer_title)
        self._update_hud_enabled()
        self._emit_preview()

    def _emit_preview(self) -> None:
        if self._open:
            self.preview.emit(self.hud_config(), self.icons_config())

    @property
    def previewing(self) -> bool:
        """HUD/Icons page open: the app shows the HUD so changes are visible."""
        return self._open and PAGES[self.stack.currentIndex()][0] in ("HUD", "Icons")

    def _update_rules(self) -> None:
        cfg = self.streak_config()
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

    @staticmethod
    def _quietly(setter, value) -> None:
        """Set a widget value without firing its change signal (no update loop)."""
        widget = setter.__self__
        old = widget.blockSignals(True)
        setter(value)
        widget.blockSignals(old)

    # -- results ---------------------------------------------------------------

    def streak_config(self) -> StreakConfig:
        s = copy.copy(self._cfg.streaks)
        s.killer_preset = self.k_preset.currentData()
        s.survivor_preset = self.s_preset.currentData()
        s.dc_counts_as_kill = self.k_dc.isChecked()
        s.custom_killer_required = self.k_required.value()
        s.custom_killer_count_hatch = self.k_hatch.isChecked()
        s.custom_survivor_self_escape = self.s_self.isChecked()
        s.custom_survivor_min_escapes = self.s_min.value()
        return s

    def hud_config(self) -> HudConfig:
        h = copy.copy(self._cfg.hud)
        h.show = self.hud_mode.currentData()
        h.layout = self.h_layout.currentData()
        h.show_icon, h.show_title = self.h_icon.isChecked(), self.h_title.isChecked()
        h.show_attempt, h.show_best = self.h_attempt.isChecked(), self.h_best.isChecked()
        h.icon_size, h.corner_radius = self.h_icon_size.value(), self.h_radius.value()
        h.scale = self.h_scale.value() / 100
        h.opacity = self.h_opacity.value() / 100
        h.background_opacity = self.h_bg_opacity.value() / 100
        h.text_color, h.accent, h.background = self.h_text_color.color, self.h_accent.color, self.h_background.color
        h.border = self.h_border.isChecked()
        h.font = self.h_font.currentData()
        h.survivor_title = self.h_survivor_title.text().strip() or HudConfig.survivor_title
        h.killer_title = self.h_killer_title.text().strip() or HudConfig.killer_title
        return h

    def icons_config(self) -> IconsConfig:
        o = self._icons.overrides if self._icons else self._cfg.icons
        return IconsConfig(survivor=o.survivor, killers=dict(o.killers))

    def discord_config(self) -> DiscordConfig:
        cid = self.d_client.text().strip()
        return DiscordConfig(enabled=self.d_enabled.isChecked() and cid.isdigit(),
                             client_id=cid if cid.isdigit() else self._cfg.discord.client_id,
                             large_image=self.d_image.text().strip(), show_map=self.d_map.isChecked())

    def active_states(self) -> dict[str, bool]:
        return {cat: t.isChecked() for cat, t in self.streak_toggles.items()}

    def config(self) -> Config:
        cfg = copy.deepcopy(self._cfg)
        cfg.streaks, cfg.hud, cfg.icons = self.streak_config(), self.hud_config(), self.icons_config()
        cfg.discord = self.discord_config()
        return cfg

    def _save(self, history: bool) -> None:
        cfg = self.config()
        self.saved.emit(cfg, history, self.active_states())
        self._cfg = cfg  # so close() below doesn't "revert"
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._open:
            self._open = False
            self.closed.emit()
        super().closeEvent(event)
