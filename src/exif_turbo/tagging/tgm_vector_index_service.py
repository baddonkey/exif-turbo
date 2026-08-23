from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..data.tgm_vector_repository import TgmVectorRepository
from ..indexing.ai_indexer_service import AiIndexerService
from ..models.tgm_vector import TgmVectorBuildResult, TgmVectorFingerprint
from ..models.vocabulary import VocabularySnapshot
from .tgm_prompt_builder import TgmPromptBuilder
from .vocabulary_snapshot_repository import VocabularySnapshotRepository


class TgmVectorIndexService:
    def __init__(
        self,
        snapshot_repository: VocabularySnapshotRepository,
        vector_repository: TgmVectorRepository,
        encoder: AiIndexerService,
        prompt_builder: TgmPromptBuilder | None = None,
    ) -> None:
        self._snapshot_repository = snapshot_repository
        self._vector_repository = vector_repository
        self._encoder = encoder
        self._prompt_builder = prompt_builder or TgmPromptBuilder()

    def expected_fingerprint(self) -> TgmVectorFingerprint:
        return self._fingerprint_for(self._snapshot_repository.load())

    def is_current(self) -> bool:
        return self._vector_repository.fingerprint == self.expected_fingerprint()

    def build(
        self,
        *,
        batch_size: int = 64,
        on_progress: Callable[[int, int, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> TgmVectorBuildResult:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        snapshot = self._snapshot_repository.load()
        concepts = snapshot.concepts
        vectors: list[np.ndarray] = []
        concept_ids: list[str] = []
        locales: list[str] = []
        total = len(concepts)
        for start in range(0, total, batch_size):
            if cancel_check is not None and cancel_check():
                return TgmVectorBuildResult(False, start)
            batch = concepts[start : start + batch_size]
            rows = [
                (concept.concept_id, locale, prompt)
                for concept in batch
                for locale, prompt in self._prompt_builder.build_all(concept)
            ]
            prompts = [prompt for _concept_id, _locale, prompt in rows]
            vectors.append(self._encoder.encode_texts(prompts, batch_size=batch_size))
            concept_ids.extend(concept_id for concept_id, _locale, _prompt in rows)
            locales.extend(locale for _concept_id, locale, _prompt in rows)
            done = start + len(batch)
            if on_progress is not None:
                on_progress(done, total, batch[-1].canonical_label)
        if cancel_check is not None and cancel_check():
            return TgmVectorBuildResult(False, total)
        matrix = (
            np.concatenate(vectors, axis=0)
            if vectors
            else np.empty((0, self._encoder.profile.dimension), dtype=np.float32)
        )
        self._vector_repository.replace_index(
            matrix,
            concept_ids,
            self._fingerprint_for(snapshot),
            locales=locales,
        )
        return TgmVectorBuildResult(True, total)

    def _fingerprint_for(self, snapshot: VocabularySnapshot) -> TgmVectorFingerprint:
        profile = self._encoder.profile
        return TgmVectorFingerprint(
            vocabulary="wikidata",
            snapshot_version=snapshot.version,
            source_dump_sha256=snapshot.source_dump_sha256,
            manifest_sha256=snapshot.manifest_sha256,
            prompt_version=self._prompt_builder.VERSION,
            prompt_strategy=self._prompt_builder.STRATEGY,
            prompt_locales=self._prompt_builder.LOCALES,
            model_name=profile.model_name,
            pretrained=profile.pretrained,
            dimension=profile.dimension,
        )