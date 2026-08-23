from __future__ import annotations

from collections.abc import Iterable

from ..models.vocabulary import REQUIRED_VOCABULARY_LOCALES
from .controlled_vocabulary_repository import ControlledVocabularyRepository
from .tgm_snapshot_repository import TgmSnapshotRepository


class AcceptedTagAliasResolver:
    def __init__(
        self,
        *,
        vocabulary_repository: ControlledVocabularyRepository | None = None,
        tgm_repository: TgmSnapshotRepository | None = None,
    ) -> None:
        self._vocabulary_repository = vocabulary_repository
        self._tgm_repository = tgm_repository

    def resolve(self, concept_ids: Iterable[str]) -> dict[str, tuple[str, ...]]:
        return {
            concept_id: labels
            for concept_id in concept_ids
            if (labels := self._labels_for(concept_id))
        }

    def _labels_for(self, concept_id: str) -> tuple[str, ...]:
        if concept_id.startswith("wikidata:"):
            if self._vocabulary_repository is None:
                return ()
            concept = self._vocabulary_repository.get(concept_id)
            if concept is None:
                return ()
            labels = (
                label
                for locale in sorted(REQUIRED_VOCABULARY_LOCALES)
                for label in (
                    concept.preferred_label(locale),
                    *concept.aliases(locale),
                )
            )
            return self._deduplicate(labels)
        if not concept_id.startswith("loc-tgm:") or self._tgm_repository is None:
            return ()
        concept = self._tgm_repository.get(concept_id)
        if concept is None:
            return ()
        return self._deduplicate((concept.label, *concept.aliases))

    @staticmethod
    def _deduplicate(labels: Iterable[str]) -> tuple[str, ...]:
        values: dict[str, str] = {}
        for value in labels:
            label = value.strip()
            if label:
                values.setdefault(label.casefold(), label)
        return tuple(values.values())