from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class FreeTagListModel(QAbstractListModel):
    LabelRole = Qt.UserRole + 1

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[str] = []

    def roleNames(self) -> dict[int, bytes]:
        return {self.LabelRole: b"label"}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        if role in (self.LabelRole, Qt.DisplayRole):
            return self._rows[index.row()]
        return None

    def set_rows(self, rows: Iterable[str]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()