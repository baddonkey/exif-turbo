from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..data.tgm_vector_repository import TgmVectorRepository
from ..indexing.ai_indexer_service import (
    AiIndexerService,
    CLIP_MODEL_NAME,
    CLIP_PRETRAINED,
    CLIP_VECTOR_DIMENSION,
)
from ..models.tgm import TgmSnapshot
from ..models.tgm_vector import TgmVectorBuildResult, TgmVectorFingerprint
from .tgm_prompt_builder import TgmPromptBuilder
from .tgm_snapshot_repository import TgmSnapshotRepository


class TgmVectorIndexService:
    def __init__(
        self,
        snapshot_repository: TgmSnapshotRepository,
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
        concepts = snapshot.selectable_concepts
        vectors: list[np.ndarray] = []
        total = len(concepts)
        for start in range(0, total, batch_size):
            if cancel_check is not None and cancel_check():
                return TgmVectorBuildResult(False, start)
            batch = concepts[start : start + batch_size]
            prompts = [self._prompt_builder.build(concept) for concept in batch]
            vectors.append(self._encoder.encode_texts(prompts, batch_size=batch_size))
            done = start + len(batch)
            if on_progress is not None:
                on_progress(done, total, batch[-1].label)
        if cancel_check is not None and cancel_check():
            return TgmVectorBuildResult(False, total)
        matrix = (
            np.concatenate(vectors, axis=0)
            if vectors
            else np.empty((0, CLIP_VECTOR_DIMENSION), dtype=np.float32)
        )
        self._vector_repository.replace_index(
            matrix,
            [concept.concept_id for concept in concepts],
            self._fingerprint_for(snapshot),
        )
        return TgmVectorBuildResult(True, total)

    def _fingerprint_for(self, snapshot: TgmSnapshot) -> TgmVectorFingerprint:
        return TgmVectorFingerprint(
            raw_tgm_sha256=snapshot.raw_sha256,
            normalization_version=snapshot.normalization_version,
            prompt_version=self._prompt_builder.VERSION,
            model_name=CLIP_MODEL_NAME,
            pretrained=CLIP_PRETRAINED,
            dimension=CLIP_VECTOR_DIMENSION,
        )