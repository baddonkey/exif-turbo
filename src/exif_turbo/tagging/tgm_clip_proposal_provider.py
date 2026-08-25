from __future__ import annotations

from ..data.ai_vector_repository import AiVectorRepository
from ..data.tgm_vector_repository import TgmVectorRepository
from ..models.tag_proposal import (
    ProposalGenerationResult,
    ProposalGenerationStatus,
    TagProposal,
    TagProposalKind,
)
from ..models.tgm_vector import TgmVectorFingerprint
from .vocabulary_snapshot_repository import VocabularySnapshotRepository


class TgmClipProposalProvider:
    def __init__(
        self,
        image_vectors: AiVectorRepository,
        term_vectors: TgmVectorRepository,
        snapshots: VocabularySnapshotRepository,
        public_figure_vectors: TgmVectorRepository | None = None,
        public_figure_snapshots: VocabularySnapshotRepository | None = None,
    ) -> None:
        self._image_vectors = image_vectors
        self._term_vectors = term_vectors
        self._snapshots = snapshots
        self._public_figure_vectors = public_figure_vectors
        self._public_figure_snapshots = public_figure_snapshots

    def propose(
        self,
        image_path: str,
        expected_fingerprint: TgmVectorFingerprint,
        *,
        expected_public_figure_fingerprint: TgmVectorFingerprint | None = None,
        top_k: int,
        threshold: float,
    ) -> ProposalGenerationResult:
        if self._term_vectors.fingerprint != expected_fingerprint:
            return ProposalGenerationResult(
                image_path, ProposalGenerationStatus.TGM_INDEX_REQUIRED
            )
        if (
            self._public_figure_vectors is not None
            and (
                expected_public_figure_fingerprint is None
                or self._public_figure_vectors.fingerprint
                != expected_public_figure_fingerprint
            )
        ):
            return ProposalGenerationResult(
                image_path, ProposalGenerationStatus.TGM_INDEX_REQUIRED
            )
        image_vectors = self._image_vectors.get_view_vectors(image_path)
        if not image_vectors:
            return ProposalGenerationResult(
                image_path, ProposalGenerationStatus.AI_SCAN_REQUIRED
            )
        sources = [
            (
                self._term_vectors,
                self._snapshots,
                expected_fingerprint,
                TagProposalKind.VISUAL_CONCEPT,
            )
        ]
        if (
            self._public_figure_vectors is not None
            and self._public_figure_snapshots is not None
            and expected_public_figure_fingerprint is not None
        ):
            sources.append(
                (
                    self._public_figure_vectors,
                    self._public_figure_snapshots,
                    expected_public_figure_fingerprint,
                    TagProposalKind.PUBLIC_FIGURE,
                )
            )
        pooled: dict[
            str,
            tuple[
                float,
                str,
                str,
                VocabularySnapshotRepository,
                TgmVectorFingerprint,
                TagProposalKind,
            ],
        ] = {}
        for view_id, image_vector in image_vectors.items():
            for vectors, snapshots, fingerprint, kind in sources:
                for hit in vectors.search(
                    image_vector,
                    top_k=top_k,
                    threshold=threshold,
                ):
                    candidate = (
                        hit.score,
                        view_id,
                        hit.locale,
                        snapshots,
                        fingerprint,
                        kind,
                    )
                    current = pooled.get(hit.concept_id)
                    if current is None or candidate[0] > current[0]:
                        pooled[hit.concept_id] = candidate
        ranked = sorted(
            (
                (
                    score,
                    concept_id,
                    view_id,
                    locale,
                    snapshots,
                    fingerprint,
                    kind,
                )
                for concept_id, (
                    score,
                    view_id,
                    locale,
                    snapshots,
                    fingerprint,
                    kind,
                ) in pooled.items()
            ),
            key=lambda value: (-value[0], value[1]),
        )[:top_k]
        proposals: list[TagProposal] = []
        for rank, (
            score,
            concept_id,
            view_id,
            locale,
            snapshots,
            fingerprint,
            kind,
        ) in enumerate(ranked, start=1):
            concept = snapshots.get(concept_id)
            if concept is None:
                continue
            proposals.append(
                TagProposal(
                    image_path=image_path,
                    concept_id=concept.concept_id,
                    label=concept.canonical_label,
                    category=concept.category.value,
                    provider_fingerprint=fingerprint.identifier,
                    score=score,
                    rank=rank,
                    provider_model=(
                        f"{fingerprint.model_name}:"
                        f"{fingerprint.pretrained}"
                    ),
                    winning_view_id=view_id,
                    winning_locale=locale,
                    kind=kind,
                )
            )
        return ProposalGenerationResult(
            image_path,
            ProposalGenerationStatus.COMPLETED,
            proposals=tuple(proposals),
        )