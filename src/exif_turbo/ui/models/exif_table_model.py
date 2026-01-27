from __future__ import annotations

from typing import List

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class ExifTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: List[tuple[str, str]] = []

    def set_rows(self, rows: List[tuple[str, str]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 2

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            return self._rows[index.row()][index.column()]
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ["Tag", "Value"][section]
