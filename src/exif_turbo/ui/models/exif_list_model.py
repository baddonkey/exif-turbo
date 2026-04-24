from __future__ import annotations

from typing import List

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class ExifListModel(QAbstractListModel):
    TagRole = Qt.UserRole + 1
    ValueRole = Qt.UserRole + 2

    def __init__(self) -> None:
        super().__init__()
        self._rows: List[tuple[str, str]] = []

    def roleNames(self) -> dict:
        return {
            self.TagRole: b"tag",
            self.ValueRole: b"value",
        }

    def set_rows(self, rows: List[tuple[str, str]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        if role == self.TagRole:
            return self._rows[index.row()][0]
        if role == self.ValueRole:
            return self._rows[index.row()][1]
        return None
