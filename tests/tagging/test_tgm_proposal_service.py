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
    TagProposalKind,
    TagProposalStatus,
)
from exif_turbo.models.tgm_vector import TgmVectorFingerprint
from exif_turbo.models.vocabulary import (
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
    VocabularySnapshot,
)
from exif_turbo.tagging.tgm_clip_proposal_provider import TgmClipProposalProvider
from exif_turbo.tagging.tgm_proposal_service import TgmProposalService
from exif_turbo.tagging.vocabulary_snapshot_repository import VocabularySnapshotRepository


def _concept(number: int, label: str) -> VocabularyConcept:
    return VocabularyConcept(
        concept_id=f"wikidata:Q{number}",
        category=VocabularyCategory.SUBJECT,
        canonical_label=label,
        localized_terms=tuple(
            LocalizedVocabularyTerms(locale, label)
            for locale in ("en", "de", "fr", "it")
        ),
        source_uri=f"https://www.wikidata.org/entity/Q{number}",
        license_id="CC0-1.0",
    )


def _fingerprint() -> TgmVectorFingerprint:
    return TgmVectorFingerprint(
        vocabulary="wikidata",
        snapshot_version=1,
        source_dump_sha256="a" * 64,
        manifest_sha256="b" * 64,
        prompt_version=3,
        prompt_strategy="wikidata-multilingual-labels-aliases-v1",
        prompt_locales=("en", "de", "fr", "it"),
        model_name="ViT-B-32",
        pretrained="openai",
        dimension=512,
    )


def _public_figure_fingerprint() -> TgmVectorFingerprint:
    return TgmVectorFingerprint(
        vocabulary="wikidata",
        snapshot_version=1,
        source_dump_sha256="c" * 64,
        manifest_sha256="d" * 64,
        prompt_version=1,
        prompt_strategy="wikidata-public-figure-names-v1",
        prompt_locales=("en", "de", "fr", "it"),
        model_name="ViT-B-32",
        pretrained="openai",
        dimension=512,
    )


def _setup(
    tmp_path: Path,
    *,
    add_image_vector: bool = True,
    add_crop_vector: bool = False,
    add_public_figure_index: bool = False,
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
        if add_crop_vector:
            crop = np.zeros(512, dtype=np.float32)
            crop[1] = 1.0
            image_vectors.add_images(
                np.stack([query, crop]),
                [image_path, image_path],
                view_ids=["full", "top_left"],
            )
        else:
            image_vectors.add_images(query, [image_path])

    concepts = (_concept(1, "Forests"), _concept(2, "Deer"), _concept(3, "Rivers"))
    snapshot = VocabularySnapshot(
        concepts=concepts,
        version=1,
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
        source_name="Wikidata",
        source_dump_uri="file:///offline/wikidata.json",
        source_dump_sha256="a" * 64,
        manifest_sha256="b" * 64,
        license_id="CC0-1.0",
    )
    snapshots = VocabularySnapshotRepository(tmp_path / "snapshot.json.gz")
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
        matrix,
        [concept.concept_id for concept in concepts],
        fingerprint,
        locales=["en", "de", "fr"],
    )
    public_figure_vectors = None
    public_figure_snapshots = None
    if add_public_figure_index:
        public_figure_snapshots = VocabularySnapshotRepository(
            tmp_path / "public-figures.json.gz"
        )
        public_figure_snapshots.activate(
            VocabularySnapshot(
                concepts=(_concept(43274, "Charles III"),),
                version=1,
                created_at=datetime(2026, 8, 24, tzinfo=UTC),
                source_name="Wikidata public figures",
                source_dump_uri="file:///offline/public-figures.json",
                source_dump_sha256="c" * 64,
                manifest_sha256="d" * 64,
                license_id="CC0-1.0",
            )
        )
        public_figure_vectors = TgmVectorRepository(
            tmp_path / "people.faiss",
            tmp_path / "people-map.json",
            tmp_path / "people-metadata.json",
        )
        public_figure_vectors.load()
        public_figure_vectors.replace_index(
            query.reshape(1, -1),
            ["wikidata:Q43274"],
            _public_figure_fingerprint(),
            locales=["en"],
        )
    provider = TgmClipProposalProvider(
        image_vectors,
        term_vectors,
        snapshots,
        public_figure_vectors,
        public_figure_snapshots,
    )
    return (
        image_repository,
        TgmProposalService(image_repository, provider),
        image_path,
        fingerprint,
    )


def test_tgm_proposal_service_merges_public_figure_as_review_only_candidate(
    tmp_path: Path,
) -> None:
    # Arrange
    repository, service, image_path, fingerprint = _setup(
        tmp_path,
        add_public_figure_index=True,
    )

    # Act
    batch = service.generate(
        [image_path],
        fingerprint,
        expected_public_figure_fingerprint=_public_figure_fingerprint(),
        top_k=4,
        threshold=0.0,
        auto_accept_threshold=0.5,
    )

    # Assert
    proposals = batch.results[0].proposals
    assert proposals[0].concept_id == "wikidata:Q43274"
    assert proposals[0].label == "Charles III"
    assert proposals[0].kind is TagProposalKind.PUBLIC_FIGURE
    assert proposals[0].provider_fingerprint == _public_figure_fingerprint().identifier
    assert all(
        proposal.concept_id != "wikidata:Q43274"
        for proposal in batch.results[0].auto_candidates
    )
    repository.close()


def _accept_first_concept(
    repository: ImageIndexRepository, image_path: str
) -> None:
    tag = ImageTag(
        concept_id="wikidata:Q1",
        label="Forests",
        vocabulary="wikidata",
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
            schema_version=2,
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


def test_tgm_proposal_service_max_pools_image_views_and_reports_winning_locale(
    tmp_path: Path,
) -> None:
    # Arrange
    repository, service, image_path, fingerprint = _setup(
        tmp_path,
        add_crop_vector=True,
    )

    # Act
    batch = service.generate(
        [image_path],
        fingerprint,
        top_k=3,
        threshold=0.0,
    )

    # Assert
    proposal = batch.results[0].proposals[0]
    assert proposal.label == "Deer"
    assert proposal.winning_view_id == "top_left"
    assert proposal.winning_locale == "de"
    repository.close()


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
        "wikidata:Q3"
    ]
    rejected = repository.get_proposals(
        image_path,
        provider_fingerprint=fingerprint.identifier,
        status=TagProposalStatus.REJECTED,
    )
    assert [proposal.concept_id for proposal in rejected] == [
        "wikidata:Q2"
    ]


def test_tgm_proposal_service_refills_limit_after_accepted_concept(
    tmp_path: Path,
) -> None:
    # Arrange
    repository, service, image_path, fingerprint = _setup(tmp_path)
    _accept_first_concept(repository, image_path)

    # Act
    batch = service.generate([image_path], fingerprint, top_k=2, threshold=0.0)

    # Assert
    assert [proposal.concept_id for proposal in batch.results[0].proposals] == [
        "wikidata:Q2",
        "wikidata:Q3",
    ]


class _DuplicateProvider:
    def propose(self, image_path: str, fingerprint: TgmVectorFingerprint, **_: object) -> ProposalGenerationResult:
        proposal = TagProposal(
            image_path=image_path,
            concept_id="wikidata:Q1",
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