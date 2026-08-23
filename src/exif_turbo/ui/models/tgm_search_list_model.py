from __future__ import annotations

from collections.abc import Iterable
from typing import Callable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ...models.tgm import TgmConcept
from ...models.vocabulary import VocabularyConcept


SearchConcept = TgmConcept | VocabularyConcept


class TgmSearchListModel(QAbstractListModel):
    ConceptIdRole = Qt.UserRole + 1
    LabelRole = Qt.UserRole + 2
    CategoriesRole = Qt.UserRole + 3
    AliasesRole = Qt.UserRole + 4
    CanonicalLabelRole = Qt.UserRole + 5

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[SearchConcept] = []
        self._label_resolver: Callable[[str], str] | None = None
        self._alias_resolver: Callable[[str], tuple[str, ...]] | None = None

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ConceptIdRole: b"conceptId",
            self.LabelRole: b"label",
            self.CategoriesRole: b"categories",
            self.AliasesRole: b"aliases",
            self.CanonicalLabelRole: b"canonicalLabel",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        concept = self._rows[index.row()]
        canonical_label = (
            concept.canonical_label
            if isinstance(concept, VocabularyConcept)
            else concept.label
        )
        canonical_aliases = (
            concept.aliases("en")
            if isinstance(concept, VocabularyConcept)
            else concept.aliases
        )
        label = (
            self._label_resolver(concept.concept_id)
            if self._label_resolver is not None
            else canonical_label
        )
        aliases = (
            self._alias_resolver(concept.concept_id)
            if self._alias_resolver is not None
            else canonical_aliases
        )
        categories = (
            [concept.category.value]
            if isinstance(concept, VocabularyConcept)
            else [category.value for category in concept.categories]
        )
        values: dict[int, object] = {
            self.ConceptIdRole: concept.concept_id,
            self.LabelRole: label,
            self.CategoriesRole: categories,
            self.AliasesRole: list(aliases),
            self.CanonicalLabelRole: canonical_label,
        }
        return values.get(role)

    def set_rows(self, rows: Iterable[SearchConcept]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def set_localization(
        self,
        label_resolver: Callable[[str], str] | None,
        alias_resolver: Callable[[str], tuple[str, ...]] | None,
    ) -> None:
        self._label_resolver = label_resolver
        self._alias_resolver = alias_resolver