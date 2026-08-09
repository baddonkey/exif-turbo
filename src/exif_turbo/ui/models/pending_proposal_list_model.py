from __future__ import annotations

from collections.abc import Iterable

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

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[TagProposal] = []

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ConceptIdRole: b"conceptId",
            self.LabelRole: b"label",
            self.CategoryRole: b"category",
            self.ScoreRole: b"score",
            self.RankRole: b"rank",
            self.ProviderRole: b"provider",
            self.ProviderFingerprintRole: b"providerFingerprint",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        proposal = self._rows[index.row()]
        values: dict[int, object] = {
            self.ConceptIdRole: proposal.concept_id,
            self.LabelRole: proposal.label,
            self.CategoryRole: proposal.category,
            self.ScoreRole: proposal.score,
            self.RankRole: proposal.rank,
            self.ProviderRole: proposal.provider_model,
            self.ProviderFingerprintRole: proposal.provider_fingerprint,
        }
        return values.get(role)

    def set_rows(self, rows: Iterable[TagProposal]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()