"""Small searchable list for 'detection wasn't sure, please pick'.

Type to filter, Enter/double-click to choose, Esc to close. Used for maps
and killers.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..detection.text import norm

ROLE = Qt.ItemDataRole.UserRole


class ListPicker(QWidget):
    picked = Signal(object)  # the payload of the chosen item

    def __init__(self, title: str) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(title)
        self.resize(420, 480)

        self.header = QLabel(wordWrap=True)
        self.search = QLineEdit(placeholderText="Type to filter…")
        self.list = QListWidget()
        layout = QVBoxLayout(self)
        for w in (self.header, self.search, self.list):
            layout.addWidget(w)

        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._choose)
        self.list.itemActivated.connect(lambda _: self._choose())

    def open(self, header: str, items: list[tuple[str, Any]], selected: Any = None) -> None:
        self.header.setText(header)
        self.list.clear()
        current = 0
        for i, (label, payload) in enumerate(items):
            item = QListWidgetItem(label)
            item.setData(ROLE, payload)
            self.list.addItem(item)
            if payload == selected:
                current = i
        self.search.clear()
        self.list.setCurrentRow(current)
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
        self.hide()
        self.picked.emit(item.data(ROLE))

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        elif e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.list.keyPressEvent(e)  # arrow keys move the list while typing
        else:
            super().keyPressEvent(e)
