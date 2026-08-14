from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.data.tgm_vector_repository import TgmVectorRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.models.tag_proposal import (
    ProposalGenerationResult,
    ProposalGenerationStatus,
    TagProposal,
    TagProposalStatus,
)
from exif_turbo.models.tgm import TgmCategory, TgmConcept, TgmSnapshot, TgmSourceFormat
from exif_turbo.models.tgm_vector import TgmVectorFingerprint
from exif_turbo.tagging.tgm_clip_proposal_provider import TgmClipProposalProvider
from exif_turbo.tagging.tgm_proposal_service import TgmProposalService
from exif_turbo.tagging.tgm_snapshot_repository import TgmSnapshotRepository


def _concept(number: int, label: str) -> TgmConcept:
    return TgmConcept(
        concept_id=f"loc-tgm:tgm{number:06d}",
        tnr=f"tgm{number:06d}",
        label=label,
        categories=(TgmCategory.SUBJECT,),
    )


def _fingerprint() -> TgmVectorFingerprint:
    return TgmVectorFingerprint("snapshot", 1, 1, "ViT-B-32", "openai", 512)


def _setup(
    tmp_path: Path,
    *,
    add_image_vector: bool = True,
) -> tuple[ImageIndexRepository, TgmProposalService, str, TgmVectorFingerprint]:
    image_path = "/photos/photo.jpg"
    image_repository = ImageIndexRepository(tmp_path / "images.db")
    image_repository.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "")

    image_vectors = AiVectorRepository(
        tmp_path / "images.faiss", tmp_path / "image-map.json"
    )
    image_vectors.load()
    query = np.zeros(512, dtype=np.float32)
    query[:3] = (0.9, 0.8, 0.7)
    if add_image_vector:
        image_vectors.add_images(query, [image_path])

    concepts = (_concept(1, "Forests"), _concept(2, "Deer"), _concept(3, "Rivers"))
    snapshot = TgmSnapshot(
        concepts=concepts,
        diagnostics=(),
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        distribution_date=None,
        imported_at=datetime(2026, 8, 9, tzinfo=UTC),
        raw_sha256="snapshot",
        raw_size_bytes=100,
    )
    snapshots = TgmSnapshotRepository(tmp_path / "snapshot.json.gz")
    snapshots.activate(snapshot)

    term_vectors = TgmVectorRepository(
        tmp_path / "terms.faiss",
        tmp_path / "concept-map.json",
        tmp_path / "term-metadata.json",
    )
    term_vectors.load()
    matrix = np.zeros((3, 512), dtype=np.float32)
    matrix[0, 0] = 1.0
    matrix[1, 1] = 1.0
    matrix[2, 2] = 1.0
    fingerprint = _fingerprint()
    term_vectors.replace_index(
        matrix, [concept.concept_id for concept in concepts], fingerprint
    )
    provider = TgmClipProposalProvider(image_vectors, term_vectors, snapshots)
    return (
        image_repository,
        TgmProposalService(image_repository, provider),
        image_path,
        fingerprint,
    )


def _accept_first_concept(
    repository: ImageIndexRepository, image_path: str
) -> None:
    tag = ImageTag(
        concept_id="loc-tgm:tgm000001",
        label="Forests",
        category="subject",
        provenance=TagProvenance(
            method="manual",
            accepted_at="2026-08-09T12:00:00Z",
            vocabulary_checksum="sha256:snapshot",
        ),
    )
    repository.replace_accepted_tags_and_sidecar_state(
        image_path,
        ImageSidecar(
            source=SidecarSource(filename="photo.jpg"),
            updated_at="2026-08-09T12:00:00Z",
            tags=(tag,),
        ),
        sidecar_path=f"{image_path}.sidecar.json",
        sidecar_mtime_ns=1,
        sidecar_size=1,
        sidecar_checksum="sha256:sidecar",
        sync_status="synced",
    )


def test_tgm_proposal_service_missing_image_vector_returns_ai_scan_required(
    tmp_path: Path,
) -> None:
    # Arrange
    repository, service, image_path, fingerprint = _setup(
        tmp_path, add_image_vector=False
    )

    # Act
    batch = service.generate(
        [image_path], fingerprint, top_k=3, threshold=0.0
    )

    # Assert
    assert batch.results[0].status is ProposalGenerationStatus.AI_SCAN_REQUIRED
    assert repository.get_proposals(image_path) == ()


def test_tgm_proposal_service_returns_ranked_results_without_persisting_pending(
    tmp_path: Path,
) -> None:
    # Arrange
    repository, service, image_path, fingerprint = _setup(tmp_path)

    # Act
    batch = service.generate(
        [image_path],
        fingerprint,
        top_k=3,
        threshold=0.0,
        auto_accept_threshold=0.55,
    )

    # Assert
    result = batch.results[0]
    assert [proposal.label for proposal in result.proposals] == [
        "Forests",
        "Deer",
        "Rivers",
    ]
    assert [proposal.rank for proposal in result.proposals] == [1, 2, 3]
    assert [proposal.label for proposal in result.auto_candidates] == ["Forests", "Deer"]
    assert repository.get_proposals(image_path) == ()
    assert repository.get_accepted_tags(image_path) == ()


def test_tgm_proposal_service_excludes_accepted_and_rejected_current_concepts(
    tmp_path: Path,
) -> None:
    # Arrange
    repository, service, image_path, fingerprint = _setup(tmp_path)
    _accept_first_concept(repository, image_path)
    rejected_proposal = service.generate(
        [image_path], fingerprint, top_k=3, threshold=0.0
    ).results[0].proposals[0]
    repository.record_rejected_proposal(
        rejected_proposal
    )

    # Act
    batch = service.generate([image_path], fingerprint, top_k=3, threshold=0.0)

    # Assert
    assert [proposal.concept_id for proposal in batch.results[0].proposals] == [
        "loc-tgm:tgm000003"
    ]
    rejected = repository.get_proposals(
        image_path,
        provider_fingerprint=fingerprint.identifier,
        status=TagProposalStatus.REJECTED,
    )
    assert [proposal.concept_id for proposal in rejected] == [
        "loc-tgm:tgm000002"
    ]


class _DuplicateProvider:
    def propose(self, image_path: str, fingerprint: TgmVectorFingerprint, **_: object) -> ProposalGenerationResult:
        proposal = TagProposal(
            image_path=image_path,
            concept_id="loc-tgm:tgm000001",
            label="Forests",
            category="subject",
            provider_fingerprint=fingerprint.identifier,
            score=0.9,
            rank=1,
        )
        return ProposalGenerationResult(
            image_path,
            ProposalGenerationStatus.COMPLETED,
            proposals=(proposal, proposal),
        )


def test_tgm_proposal_service_deduplicates_canonical_concepts(tmp_path: Path) -> None:
    # Arrange
    repository = ImageIndexRepository(tmp_path / "images.db")
    image_path = "/photos/photo.jpg"
    repository.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "")
    service = TgmProposalService(repository, _DuplicateProvider())  # type: ignore[arg-type]

    # Act
    batch = service.generate([image_path], _fingerprint(), top_k=3, threshold=0.0)

    # Assert
    assert len(batch.results[0].proposals) == 1
    assert repository.get_proposals(image_path) == ()


def test_tgm_proposal_repository_image_delete_cascades_proposals(
    tmp_path: Path,
) -> None:
    # Arrange
    repository, service, image_path, fingerprint = _setup(tmp_path)
    service.generate([image_path], fingerprint, top_k=3, threshold=0.0)

    # Act
    repository.delete_missing([])

    # Assert
    count = repository.conn.execute(
        "SELECT COUNT(*) FROM image_tag_proposals"
    ).fetchone()[0]
    assert count == 0


def test_tgm_proposal_service_cancellation_stops_before_next_image(
    tmp_path: Path,
) -> None:
    # Arrange
    repository, service, image_path, fingerprint = _setup(tmp_path)
    second_path = "/photos/second.jpg"
    repository.upsert_image(second_path, "second.jpg", 1.0, 100, {}, "")
    checks = 0

    def _cancel_after_first() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    # Act
    batch = service.generate(
        [image_path, second_path],
        fingerprint,
        top_k=3,
        threshold=0.0,
        cancel_check=_cancel_after_first,
    )

    # Assert
    assert batch.cancelled is True
    assert len(batch.results) == 1