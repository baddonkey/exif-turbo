from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.models.tag_proposal import (
    ProposalBatchResult,
    ProposalGenerationResult,
    ProposalGenerationStatus,
    TagProposal,
    TagProposalStatus,
)
from exif_turbo.models.tgm import TgmCategory, TgmConcept, TgmSnapshot, TgmSourceFormat
from exif_turbo.tagging.sidecar_repository import (
    FilesystemSidecarRepository,
    SidecarRevision,
)
from exif_turbo.tagging.tagging_service import (
    BulkTagStatus,
    TagMembership,
    TaggingConflictError,
    TaggingFreeTagError,
    TaggingPartialFailure,
    TaggingService,
    TaggingSidecarError,
)
from exif_turbo.tagging.tgm_snapshot_repository import TgmSnapshotRepository


NOW = datetime(2026, 8, 9, 12, 30, tzinfo=UTC)


def _service(
    tmp_path: Path,
) -> tuple[TaggingService, ImageIndexRepository, Path]:
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"original image bytes")
    image_stat = image_path.stat()
    image_repository = ImageIndexRepository(tmp_path / "images.db")
    image_repository.upsert_image(
        str(image_path),
        image_path.name,
        image_stat.st_mtime,
        image_stat.st_size,
        {},
        "",
    )
    snapshot_repository = TgmSnapshotRepository(tmp_path / "tgm.json.gz")
    snapshot_repository.activate(
        TgmSnapshot(
            concepts=(
                TgmConcept(
                    concept_id="loc-tgm:tgm000001",
                    tnr="tgm000001",
                    label="Deer",
                    categories=(TgmCategory.SUBJECT, TgmCategory.GENRE_FORMAT),
                    aliases=("Cervidae",),
                ),
                TgmConcept(
                    concept_id="loc-tgm:tgm000002",
                    tnr="tgm000002",
                    label="Photographs",
                    categories=(TgmCategory.GENRE_FORMAT,),
                    aliases=("Photos",),
                ),
            ),
            diagnostics=(),
            source_url="https://example.test/tgm.xml",
            source_format=TgmSourceFormat.XML,
            distribution_date=None,
            imported_at=NOW,
            raw_sha256="snapshot-checksum",
            raw_size_bytes=100,
        )
    )
    return (
        TaggingService(
            image_repository,
            FilesystemSidecarRepository(),
            snapshot_repository,
            clock=lambda: NOW,
        ),
        image_repository,
        image_path,
    )


def test_tagging_service_add_alias_creates_canonical_sidecar_and_cache(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)
    original_stat = image_path.stat()
    original_bytes = image_path.read_bytes()

    # Act
    result = service.add_concept(str(image_path), "Cervidae")

    # Assert
    loaded = FilesystemSidecarRepository().read(image_path)
    assert result.changed is True
    assert loaded is not None
    assert loaded.sidecar.tags[0].concept_id == "loc-tgm:tgm000001"
    assert loaded.sidecar.tags[0].label == "Deer"
    assert loaded.sidecar.tags[0].category == "subject"
    assert loaded.sidecar.tags[0].extra["tgm_categories"] == [
        "subject",
        "genre_format",
    ]
    assert image_repository.get_accepted_tags(str(image_path)) == loaded.sidecar.tags
    assert image_repository.count_images("Cervidae") == 1
    assert image_path.read_bytes() == original_bytes
    assert image_path.stat().st_mtime_ns == original_stat.st_mtime_ns


def test_tagging_service_db_failure_leaves_sidecar_and_raises_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)

    def fail_cache_update(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        image_repository,
        "replace_accepted_tags_and_sidecar_state",
        fail_cache_update,
    )

    # Act / Assert
    with pytest.raises(TaggingPartialFailure, match="database unavailable"):
        service.add_concept(str(image_path), "loc-tgm:tgm000001")
    loaded = FilesystemSidecarRepository().read(image_path)
    assert loaded is not None
    assert [tag.label for tag in loaded.sidecar.tags] == ["Deer"]
    cache_state = image_repository.get_sidecar_sync_state(str(image_path))
    assert cache_state is not None
    assert cache_state.sync_status == "error"


def test_tagging_service_add_and_remove_preserve_unknown_fields_and_other_tags(
    tmp_path: Path,
) -> None:
    # Arrange
    service, _, image_path = _service(tmp_path)
    sidecars = FilesystemSidecarRepository()
    existing_tag = ImageTag(
        concept_id="loc-tgm:tgm000002",
        label="Photographs",
        category="genre_format",
        provenance=TagProvenance(
            method="manual",
            accepted_at="2026-08-01T00:00:00Z",
            vocabulary_checksum="sha256:old",
        ),
        extra={"tag_extension": "preserved"},
    )
    sidecars.write(
        image_path,
        ImageSidecar(
            source=SidecarSource(
                filename=image_path.name,
                size=image_path.stat().st_size,
                mtime_ns=image_path.stat().st_mtime_ns,
                extra={"source_extension": 1},
            ),
            updated_at="2026-08-01T00:00:00Z",
            tags=(existing_tag,),
            extra={"top_extension": {"enabled": True}},
        ),
        expected_revision=None,
    )

    # Act
    service.add_concept(str(image_path), "Deer")
    service.remove_concept(str(image_path), "loc-tgm:tgm000001")

    # Assert
    loaded = sidecars.read(image_path)
    assert loaded is not None
    assert loaded.sidecar.tags == (existing_tag,)
    assert loaded.sidecar.extra == {"top_extension": {"enabled": True}}
    assert loaded.sidecar.source.extra == {"source_extension": 1}


def test_tagging_service_add_and_remove_free_tag_preserves_tgm_and_catalog(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)
    service.add_concept(str(image_path), "Deer")

    # Act
    added = service.add_free_tag(str(image_path), " Family ")
    removed = service.remove_free_tag(str(image_path), "family")

    # Assert
    assert added.sidecar.free_tags == ("Family",)
    assert removed.sidecar.free_tags == ()
    assert len(removed.sidecar.tags) == 1
    assert image_repository.get_free_tags(str(image_path)) == ()
    assert image_repository.search_free_tags("fam") == ("Family",)
    assert image_repository.count_images("Deer") == 1
    assert image_repository.count_images("Family") == 0


def test_tagging_service_add_duplicate_free_tag_ignoring_case_is_no_op(
    tmp_path: Path,
) -> None:
    # Arrange
    service, _, image_path = _service(tmp_path)
    service.add_free_tag(str(image_path), "Family")

    # Act
    result = service.add_free_tag(str(image_path), " family ")

    # Assert
    assert result.changed is False
    assert result.sidecar.free_tags == ("Family",)


def test_tagging_service_reuses_remembered_free_tag_spelling(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)
    service.add_free_tag(str(image_path), "Family")
    service.remove_free_tag(str(image_path), "Family")

    # Act
    result = service.add_free_tag(str(image_path), "family")

    # Assert
    assert result.sidecar.free_tags == ("Family",)
    assert image_repository.get_free_tags(str(image_path)) == ("Family",)


def test_tagging_service_add_blank_free_tag_raises_typed_error(
    tmp_path: Path,
) -> None:
    # Arrange
    service, _, image_path = _service(tmp_path)

    # Act / Assert
    with pytest.raises(TaggingFreeTagError, match="non-empty"):
        service.add_free_tag(str(image_path), "   ")


def test_tagging_service_accept_proposal_uses_clip_provenance_without_pending_cache(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)
    proposal = _proposal(str(image_path), "loc-tgm:tgm000001", "Deer", 0.91)

    # Act
    result = service.accept_proposal(proposal)

    # Assert
    assert result.sidecar.tags[0].provenance.method == "clip"
    assert result.sidecar.tags[0].provenance.confidence == 0.91
    assert image_repository.get_proposals(str(image_path)) == ()


def test_tagging_service_reject_proposal_does_not_write_sidecar(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)
    proposal = _proposal(str(image_path), "loc-tgm:tgm000001", "Deer", 0.91)

    # Act
    service.reject_proposal(proposal)

    # Assert
    assert not FilesystemSidecarRepository.sidecar_path(image_path).exists()
    rejected = image_repository.get_proposals(
        str(image_path), status=TagProposalStatus.REJECTED
    )
    assert rejected == (proposal.__class__(**{**proposal.__dict__, "status": TagProposalStatus.REJECTED}),)


def test_tagging_service_malformed_sidecar_fails_without_replacement(
    tmp_path: Path,
) -> None:
    # Arrange
    service, _, image_path = _service(tmp_path)
    sidecar_path = FilesystemSidecarRepository.sidecar_path(image_path)
    malformed = b"{not valid json"
    sidecar_path.write_bytes(malformed)

    # Act / Assert
    with pytest.raises(TaggingSidecarError, match="invalid sidecar JSON"):
        service.add_concept(str(image_path), "Deer")
    assert sidecar_path.read_bytes() == malformed


class _ConflictingSidecarRepository(FilesystemSidecarRepository):
    def write(
        self,
        image_path: Path,
        sidecar: ImageSidecar,
        expected_revision: SidecarRevision | None,
    ) -> SidecarRevision:
        self.sidecar_path(image_path).write_text("external edit", encoding="utf-8")
        return super().write(image_path, sidecar, expected_revision)


def test_tagging_service_external_edit_is_typed_conflict(tmp_path: Path) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)
    service.add_concept(str(image_path), "Photographs")
    conflicting_service = TaggingService(
        image_repository,
        _ConflictingSidecarRepository(),
        service._tgm_repository,
        clock=lambda: NOW,
    )

    # Act / Assert
    with pytest.raises(TaggingConflictError, match="changed externally"):
        conflicting_service.add_concept(str(image_path), "Deer")


class _TrackingSidecarRepository(FilesystemSidecarRepository):
    def __init__(self) -> None:
        self.write_count = 0

    def write(
        self,
        image_path: Path,
        sidecar: ImageSidecar,
        expected_revision: SidecarRevision | None,
    ) -> SidecarRevision:
        self.write_count += 1
        return super().write(image_path, sidecar, expected_revision)


def test_tagging_service_auto_accepts_multiple_candidates_in_one_clip_write(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)
    tracking = _TrackingSidecarRepository()
    service = TaggingService(
        image_repository,
        tracking,
        service._tgm_repository,
        clock=lambda: NOW,
    )
    proposals = (
        _proposal(str(image_path), "loc-tgm:tgm000001", "Deer", 0.91),
        _proposal(str(image_path), "loc-tgm:tgm000002", "Photographs", 0.87),
    )
    batch = ProposalBatchResult(
        (
            ProposalGenerationResult(
                str(image_path),
                ProposalGenerationStatus.COMPLETED,
                proposals=proposals,
                auto_candidates=proposals,
            ),
        ),
        False,
    )

    # Act
    result = service.accept_auto_candidates(batch)

    # Assert
    loaded = tracking.read(image_path)
    assert result.succeeded_count == 1
    assert tracking.write_count == 1
    assert loaded is not None
    assert {tag.provenance.method for tag in loaded.sidecar.tags} == {"clip"}
    assert {tag.provenance.model for tag in loaded.sidecar.tags} == {"ViT-B-32:openai"}
    assert {
        tag.provenance.extra["provider_fingerprint"] for tag in loaded.sidecar.tags
    } == {"provider-fingerprint"}
    assert image_repository.get_proposals(str(image_path)) == ()


def test_tagging_service_bulk_mixed_results_and_cancellation_retain_completion(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, first_path = _service(tmp_path)
    second_path = _add_image(image_repository, tmp_path / "second.jpg")
    third_path = _add_image(image_repository, tmp_path / "third.jpg")
    service.add_concept(str(first_path), "Deer")
    progress: list[str] = []
    checks = 0

    def cancel_after_two() -> bool:
        nonlocal checks
        checks += 1
        return checks > 2

    # Act
    result = service.add_concept_to_paths(
        (str(first_path), str(second_path), str(third_path)),
        "Deer",
        on_progress=lambda _done, _total, item: progress.append(item.image_path),
        cancel_check=cancel_after_two,
    )

    # Assert
    assert [item.status for item in result.items] == [
        BulkTagStatus.SKIPPED,
        BulkTagStatus.SUCCEEDED,
    ]
    assert result.cancelled is True
    assert progress == [str(first_path), str(second_path)]
    assert not FilesystemSidecarRepository.sidecar_path(third_path).exists()


def test_tagging_service_bulk_remove_missing_is_skipped_and_failure_is_retained(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, first_path = _service(tmp_path)
    second_path = _add_image(image_repository, tmp_path / "second.jpg")
    service.add_concept(str(first_path), "Deer")

    # Act
    result = service.remove_concept_from_paths(
        (str(first_path), str(second_path), str(tmp_path / "missing.jpg")),
        "loc-tgm:tgm000001",
    )

    # Assert
    assert [item.status for item in result.items] == [
        BulkTagStatus.SUCCEEDED,
        BulkTagStatus.SKIPPED,
        BulkTagStatus.FAILED,
    ]
    assert result.succeeded_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 1


def test_tagging_service_marked_aggregate_reports_all_and_some(tmp_path: Path) -> None:
    # Arrange
    service, image_repository, first_path = _service(tmp_path)
    second_path = _add_image(image_repository, tmp_path / "second.jpg")
    service.add_concept(str(first_path), "Deer")
    service.add_concept(str(second_path), "Deer")
    service.add_concept(str(first_path), "Photographs")
    image_repository.mark_images((str(first_path), str(second_path)), True)

    # Act
    aggregate = service.get_marked_tagging_state(
        restrict_to_enabled_folders=False
    )

    # Assert
    assert aggregate.total_marked == 2
    assert aggregate.tagged_marked == 2
    assert {
        item.concept.label: (item.count, item.membership)
        for item in aggregate.concepts
    } == {
        "Deer": (2, TagMembership.ALL),
        "Photographs": (1, TagMembership.SOME),
    }


def test_tagging_service_marked_aggregate_counts_untagged_images(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, first_path = _service(tmp_path)
    second_path = _add_image(image_repository, tmp_path / "second.jpg")
    service.add_concept(str(first_path), "Deer")
    image_repository.mark_images((str(first_path), str(second_path)), True)

    # Act
    aggregate = service.get_marked_tagging_state(
        restrict_to_enabled_folders=False
    )

    # Assert
    assert aggregate.total_marked == 2
    assert aggregate.tagged_marked == 1


def _proposal(
    image_path: str,
    concept_id: str,
    label: str,
    score: float,
) -> TagProposal:
    return TagProposal(
        image_path=image_path,
        concept_id=concept_id,
        label=label,
        category="subject",
        provider_fingerprint="provider-fingerprint",
        score=score,
        rank=1,
        provider_model="ViT-B-32:openai",
    )


def _add_image(repository: ImageIndexRepository, image_path: Path) -> Path:
    image_path.write_bytes(b"another original")
    image_stat = image_path.stat()
    repository.upsert_image(
        str(image_path),
        image_path.name,
        image_stat.st_mtime,
        image_stat.st_size,
        {},
        "",
    )
    return image_path