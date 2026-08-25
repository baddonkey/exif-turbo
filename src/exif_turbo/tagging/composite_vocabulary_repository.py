from __future__ import annotations

from ..config import bundled_public_figure_vocabulary_path, bundled_vocabulary_path
from ..models.vocabulary import VocabularyConcept, VocabularySnapshot
from .vocabulary_snapshot_repository import VocabularySnapshotRepository


class CompositeVocabularyRepository:
    def __init__(
        self,
        primary: VocabularySnapshotRepository,
        *additional: VocabularySnapshotRepository,
    ) -> None:
        self._repositories = (primary, *additional)

    def load(self) -> VocabularySnapshot:
        return self._repositories[0].load()

    def get(self, concept_id: str) -> VocabularyConcept | None:
        for repository in self._repositories:
            if concept := repository.get(concept_id):
                return concept
        return None

    def snapshot_for(self, concept_id: str) -> VocabularySnapshot | None:
        for repository in self._repositories:
            if snapshot := repository.snapshot_for(concept_id):
                return snapshot
        return None

    def preferred_label(self, concept_id: str, locale: str) -> str | None:
        concept = self.get(concept_id)
        return None if concept is None else concept.preferred_label(locale)

    def resolve_label(
        self,
        label: str,
        locale: str,
    ) -> VocabularyConcept | None:
        matches = tuple(
            concept
            for repository in self._repositories
            if (concept := repository.resolve_label(label, locale)) is not None
        )
        concept_ids = {concept.concept_id for concept in matches}
        if len(concept_ids) > 1:
            raise ValueError(f"label is ambiguous in locale {locale}: {label}")
        return matches[0] if matches else None

    def search(
        self,
        query: str,
        locale: str,
        limit: int = 20,
    ) -> tuple[VocabularyConcept, ...]:
        if limit <= 0:
            return ()
        concepts: dict[str, VocabularyConcept] = {}
        for repository in self._repositories:
            for concept in repository.search(query, locale, limit):
                concepts.setdefault(concept.concept_id, concept)
        return tuple(
            sorted(
                concepts.values(),
                key=lambda concept: (
                    concept.preferred_label(locale).casefold(),
                    concept.concept_id,
                ),
            )[:limit]
        )


def bundled_controlled_vocabulary_repository() -> CompositeVocabularyRepository:
    primary = VocabularySnapshotRepository(bundled_vocabulary_path())
    public_figures_path = bundled_public_figure_vocabulary_path()
    additional = (
        (VocabularySnapshotRepository(public_figures_path),)
        if public_figures_path.exists()
        else ()
    )
    return CompositeVocabularyRepository(primary, *additional)