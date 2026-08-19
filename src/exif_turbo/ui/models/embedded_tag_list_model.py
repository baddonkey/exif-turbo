from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class EmbeddedTagListModel(QAbstractListModel):
    LabelRole = Qt.UserRole + 1
    ExcludedRole = Qt.UserRole + 2

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[tuple[str, bool]] = []

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.LabelRole: b"label",
            self.ExcludedRole: b"excluded",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        label, excluded = self._rows[index.row()]
        if role in (self.LabelRole, Qt.DisplayRole):
            return label
        if role == self.ExcludedRole:
            return excluded
        return None

    def set_rows(self, rows: Iterable[tuple[str, bool]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()