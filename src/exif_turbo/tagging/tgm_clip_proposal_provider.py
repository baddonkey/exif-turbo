from __future__ import annotations

from ..data.ai_vector_repository import AiVectorRepository
from ..data.tgm_vector_repository import TgmVectorRepository
from ..models.tag_proposal import (
    ProposalGenerationResult,
    ProposalGenerationStatus,
    TagProposal,
)
from ..models.tgm_vector import TgmVectorFingerprint
from .vocabulary_snapshot_repository import VocabularySnapshotRepository


class TgmClipProposalProvider:
    def __init__(
        self,
        image_vectors: AiVectorRepository,
        term_vectors: TgmVectorRepository,
        snapshots: VocabularySnapshotRepository,
    ) -> None:
        self._image_vectors = image_vectors
        self._term_vectors = term_vectors
        self._snapshots = snapshots

    def propose(
        self,
        image_path: str,
        expected_fingerprint: TgmVectorFingerprint,
        *,
        top_k: int,
        threshold: float,
    ) -> ProposalGenerationResult:
        if self._term_vectors.fingerprint != expected_fingerprint:
            return ProposalGenerationResult(
                image_path, ProposalGenerationStatus.TGM_INDEX_REQUIRED
            )
        image_vectors = self._image_vectors.get_view_vectors(image_path)
        if not image_vectors:
            return ProposalGenerationResult(
                image_path, ProposalGenerationStatus.AI_SCAN_REQUIRED
            )
        pooled: dict[str, tuple[float, str, str]] = {}
        for view_id, image_vector in image_vectors.items():
            for hit in self._term_vectors.search(
                image_vector,
                top_k=top_k,
                threshold=threshold,
            ):
                candidate = (hit.score, view_id, hit.locale)
                current = pooled.get(hit.concept_id)
                if current is None or candidate[0] > current[0]:
                    pooled[hit.concept_id] = candidate
        ranked = sorted(
            (
                (score, concept_id, view_id, locale)
                for concept_id, (score, view_id, locale) in pooled.items()
            ),
            key=lambda value: (-value[0], value[1]),
        )[:top_k]
        proposals: list[TagProposal] = []
        for rank, (score, concept_id, view_id, locale) in enumerate(ranked, start=1):
            concept = self._snapshots.get(concept_id)
            if concept is None:
                continue
            proposals.append(
                TagProposal(
                    image_path=image_path,
                    concept_id=concept.concept_id,
                    label=concept.canonical_label,
                    category=concept.category.value,
                    provider_fingerprint=expected_fingerprint.identifier,
                    score=score,
                    rank=rank,
                    provider_model=(
                        f"{expected_fingerprint.model_name}:"
                        f"{expected_fingerprint.pretrained}"
                    ),
                    winning_view_id=view_id,
                    winning_locale=locale,
                )
            )
        return ProposalGenerationResult(
            image_path,
            ProposalGenerationStatus.COMPLETED,
            proposals=tuple(proposals),
        )