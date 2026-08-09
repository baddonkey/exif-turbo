from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ...models.image_tag import ImageTag


class AcceptedTagListModel(QAbstractListModel):
    ConceptIdRole = Qt.UserRole + 1
    LabelRole = Qt.UserRole + 2
    CategoryRole = Qt.UserRole + 3
    MethodRole = Qt.UserRole + 4
    ConfidenceRole = Qt.UserRole + 5
    ModelRole = Qt.UserRole + 6
    AcceptedAtRole = Qt.UserRole + 7

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[ImageTag] = []

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ConceptIdRole: b"conceptId",
            self.LabelRole: b"label",
            self.CategoryRole: b"category",
            self.MethodRole: b"method",
            self.ConfidenceRole: b"confidence",
            self.ModelRole: b"providerModel",
            self.AcceptedAtRole: b"acceptedAt",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        tag = self._rows[index.row()]
        values: dict[int, object] = {
            self.ConceptIdRole: tag.concept_id,
            self.LabelRole: tag.label,
            self.CategoryRole: tag.category,
            self.MethodRole: tag.provenance.method,
            self.ConfidenceRole: tag.provenance.confidence,
            self.ModelRole: tag.provenance.model or "",
            self.AcceptedAtRole: tag.provenance.accepted_at,
        }
        return values.get(role)

    def set_rows(self, rows: Iterable[ImageTag]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()