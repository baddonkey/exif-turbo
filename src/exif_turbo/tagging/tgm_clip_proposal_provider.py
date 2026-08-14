from __future__ import annotations

from ..data.ai_vector_repository import AiVectorRepository
from ..data.tgm_vector_repository import TgmVectorRepository
from ..models.tag_proposal import (
    ProposalGenerationResult,
    ProposalGenerationStatus,
    TagProposal,
)
from ..models.tgm_vector import TgmVectorFingerprint
from .tgm_snapshot_repository import TgmSnapshotRepository


class TgmClipProposalProvider:
    def __init__(
        self,
        image_vectors: AiVectorRepository,
        term_vectors: TgmVectorRepository,
        snapshots: TgmSnapshotRepository,
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
        image_vector = self._image_vectors.get_vector(image_path)
        if image_vector is None:
            return ProposalGenerationResult(
                image_path, ProposalGenerationStatus.AI_SCAN_REQUIRED
            )
        proposals: list[TagProposal] = []
        for hit in self._term_vectors.search(
            image_vector, top_k=top_k, threshold=threshold
        ):
            concept = self._snapshots.get(hit.concept_id)
            if concept is None or not concept.selectable:
                continue
            proposals.append(
                TagProposal(
                    image_path=image_path,
                    concept_id=concept.concept_id,
                    label=concept.label,
                    category=concept.categories[0].value,
                    provider_fingerprint=expected_fingerprint.identifier,
                    score=hit.score,
                    rank=hit.rank,
                    provider_model=(
                        f"{expected_fingerprint.model_name}:"
                        f"{expected_fingerprint.pretrained}"
                    ),
                )
            )
        return ProposalGenerationResult(
            image_path,
            ProposalGenerationStatus.COMPLETED,
            proposals=tuple(proposals),
        )