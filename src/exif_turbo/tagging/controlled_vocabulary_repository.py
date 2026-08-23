from __future__ import annotations

from typing import Protocol

from ..models.vocabulary import VocabularyConcept, VocabularySnapshot


class ControlledVocabularyRepository(Protocol):
    def load(self) -> VocabularySnapshot: ...

    def get(self, concept_id: str) -> VocabularyConcept | None: ...

    def resolve_label(
        self,
        label: str,
        locale: str,
    ) -> VocabularyConcept | None: ...