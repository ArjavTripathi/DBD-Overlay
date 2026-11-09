"""Small searchable list to pick a map when detection isn't sure.

Type to filter, Enter/double-click to choose, Esc to close. If the realm was
detected, only that realm's maps are listed (usually 2-5 entries).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..core.catalog import MapCatalog
from ..detection.text import norm

ROLE = Qt.ItemDataRole.UserRole


class MapPicker(QWidget):
    picked = Signal(str, str)  # realm, map

    def __init__(self, catalog: MapCatalog) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.catalog = catalog
        self.setWindowTitle("DBD Overlay: pick map")
        self.resize(420, 480)

        self.header = QLabel()
        self.search = QLineEdit(placeholderText="Type to filter…")
        self.list = QListWidget()
        layout = QVBoxLayout(self)
        for w in (self.header, self.search, self.list):
            layout.addWidget(w)

        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._choose)
        self.list.itemActivated.connect(lambda _: self._choose())

    def open_for(self, realm: str | None) -> None:
        r = self.catalog.realm(realm) if realm else None
        maps = r.maps if r else self.catalog.maps
        self.header.setText(f"Detected realm: <b>{r.name}</b>, which map?" if r else "Which map?")
        self.list.clear()
        for m in sorted(maps, key=lambda m: (m.realm, m.name)):
            item = QListWidgetItem(f"{m.name}  —  {m.realm}")
            item.setData(ROLE, (m.realm, m.name))
            self.list.addItem(item)
        self.search.clear()
        self.list.setCurrentRow(0)
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        needle = norm(text)
        first = None
        for i in range(self.list.count()):
            item = self.list.item(i)
            hidden = needle not in norm(item.text())
            item.setHidden(hidden)
            if not hidden and first is None:
                first = item
        if first is not None:
            self.list.setCurrentItem(first)

    def _choose(self) -> None:
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return
        realm, name = item.data(ROLE)
        self.hide()
        self.picked.emit(realm, name)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        elif e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.list.keyPressEvent(e)  # arrow keys move the list while typing
        else:
            super().keyPressEvent(e)
