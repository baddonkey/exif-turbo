from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ...tagging.tagging_service import AggregatedConceptState


class MarkedTagListModel(QAbstractListModel):
    ConceptIdRole = Qt.UserRole + 1
    LabelRole = Qt.UserRole + 2
    CategoriesRole = Qt.UserRole + 3
    CountRole = Qt.UserRole + 4
    MembershipRole = Qt.UserRole + 5

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[AggregatedConceptState] = []

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ConceptIdRole: b"conceptId",
            self.LabelRole: b"label",
            self.CategoriesRole: b"categories",
            self.CountRole: b"count",
            self.MembershipRole: b"membership",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        state = self._rows[index.row()]
        values: dict[int, object] = {
            self.ConceptIdRole: state.concept.concept_id,
            self.LabelRole: state.concept.label,
            self.CategoriesRole: [
                category.value for category in state.concept.categories
            ],
            self.CountRole: state.count,
            self.MembershipRole: state.membership.value,
        }
        return values.get(role)

    def set_rows(self, rows: Iterable[AggregatedConceptState]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()