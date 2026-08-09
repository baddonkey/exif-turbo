from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ...models.tgm import TgmConcept


class TgmSearchListModel(QAbstractListModel):
    ConceptIdRole = Qt.UserRole + 1
    LabelRole = Qt.UserRole + 2
    CategoriesRole = Qt.UserRole + 3
    AliasesRole = Qt.UserRole + 4

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[TgmConcept] = []

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ConceptIdRole: b"conceptId",
            self.LabelRole: b"label",
            self.CategoriesRole: b"categories",
            self.AliasesRole: b"aliases",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        concept = self._rows[index.row()]
        values: dict[int, object] = {
            self.ConceptIdRole: concept.concept_id,
            self.LabelRole: concept.label,
            self.CategoriesRole: [category.value for category in concept.categories],
            self.AliasesRole: list(concept.aliases),
        }
        return values.get(role)

    def set_rows(self, rows: Iterable[TgmConcept]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()