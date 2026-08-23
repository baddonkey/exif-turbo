from __future__ import annotations

from collections.abc import Iterable
from typing import Callable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ...models.tag_proposal import TagProposal


class PendingProposalListModel(QAbstractListModel):
    ConceptIdRole = Qt.UserRole + 1
    LabelRole = Qt.UserRole + 2
    CategoryRole = Qt.UserRole + 3
    ScoreRole = Qt.UserRole + 4
    RankRole = Qt.UserRole + 5
    ProviderRole = Qt.UserRole + 6
    ProviderFingerprintRole = Qt.UserRole + 7
    CanonicalLabelRole = Qt.UserRole + 8
    WinningViewRole = Qt.UserRole + 9
    WinningLocaleRole = Qt.UserRole + 10

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[TagProposal] = []
        self._label_resolver: Callable[[str], str] | None = None

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ConceptIdRole: b"conceptId",
            self.LabelRole: b"label",
            self.CategoryRole: b"category",
            self.ScoreRole: b"score",
            self.RankRole: b"rank",
            self.ProviderRole: b"provider",
            self.ProviderFingerprintRole: b"providerFingerprint",
            self.CanonicalLabelRole: b"canonicalLabel",
            self.WinningViewRole: b"winningView",
            self.WinningLocaleRole: b"winningLocale",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        proposal = self._rows[index.row()]
        label = (
            self._label_resolver(proposal.concept_id)
            if self._label_resolver is not None
            else proposal.label
        )
        values: dict[int, object] = {
            self.ConceptIdRole: proposal.concept_id,
            self.LabelRole: label,
            self.CategoryRole: proposal.category,
            self.ScoreRole: proposal.score,
            self.RankRole: proposal.rank,
            self.ProviderRole: proposal.provider_model,
            self.ProviderFingerprintRole: proposal.provider_fingerprint,
            self.CanonicalLabelRole: proposal.label,
            self.WinningViewRole: proposal.winning_view_id,
            self.WinningLocaleRole: proposal.winning_locale,
        }
        return values.get(role)

    def set_rows(self, rows: Iterable[TagProposal]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def set_label_resolver(self, resolver: Callable[[str], str] | None) -> None:
        self._label_resolver = resolver

    def find(self, concept_id: str, provider_fingerprint: str) -> TagProposal | None:
        return next(
            (
                proposal
                for proposal in self._rows
                if proposal.concept_id == concept_id
                and proposal.provider_fingerprint == provider_fingerprint
            ),
            None,
        )

    def remove(self, proposal: TagProposal) -> None:
        self.set_rows(item for item in self._rows if item is not proposal)