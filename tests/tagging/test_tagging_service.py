from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.tagging.sidecar_repository import (
    FilesystemSidecarRepository,
    SidecarRevision,
)
from exif_turbo.tagging.tagging_service import (
    BulkTagStatus,
    CopyTagsMode,
    TaggingConflictError,
    TaggingFreeTagError,
    TaggingPartialFailure,
    TaggingService,
    TaggingSidecarError,
)


NOW = datetime(2026, 8, 9, 12, 30, tzinfo=UTC)


def _service(
    tmp_path: Path,
) -> tuple[TaggingService, ImageIndexRepository, Path]:
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"original image bytes")
    image_stat = image_path.stat()
    image_repository = ImageIndexRepository(tmp_path / "images.db", key="")
    image_repository.upsert_image(
        str(image_path),
        image_path.name,
        image_stat.st_mtime,
        image_stat.st_size,
        {},
        "",
    )
    return (
        TaggingService(
            image_repository,
            FilesystemSidecarRepository(),
            clock=lambda: NOW,
        ),
        image_repository,
        image_path,
    )


def _add_indexed_image(
    image_repository: ImageIndexRepository,
    tmp_path: Path,
    filename: str,
) -> Path:
    image_path = tmp_path / filename
    image_path.write_bytes(f"image bytes for {filename}".encode())
    image_stat = image_path.stat()
    image_repository.upsert_image(
        str(image_path),
        image_path.name,
        image_stat.st_mtime,
        image_stat.st_size,
        {},
        "",
    )
    return image_path


def test_tagging_service_embedded_exclusions_persist_in_sidecar(
    tmp_path: Path,
) -> None:
    # Arrange
    service, _image_repository, image_path = _service(tmp_path)

    # Act
    service.set_embedded_tag_excluded(str(image_path), "Private", True)
    service.set_all_embedded_tags_excluded(str(image_path), True)

    # Assert
    loaded = FilesystemSidecarRepository().read(image_path)
    assert loaded is not None
    assert loaded.sidecar.excluded_embedded_tags == ("Private",)
    assert loaded.sidecar.exclude_all_embedded_tags is True


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
        "replace_custom_tags_and_sidecar_state",
        fail_cache_update,
    )

    # Act / Assert
    with pytest.raises(TaggingPartialFailure, match="database unavailable"):
        service.add_free_tag(str(image_path), "Family")
    loaded = FilesystemSidecarRepository().read(image_path)
    assert loaded is not None
    assert loaded.sidecar.free_tags == ("Family",)
    cache_state = image_repository.get_sidecar_sync_state(str(image_path))
    assert cache_state is not None
    assert cache_state.sync_status == "error"


def test_tagging_service_custom_tag_mutations_preserve_unknown_fields(
    tmp_path: Path,
) -> None:
    # Arrange
    service, _, image_path = _service(tmp_path)
    sidecars = FilesystemSidecarRepository()
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
            free_tags=("Existing",),
            extra={"top_extension": {"enabled": True}},
        ),
        expected_revision=None,
    )

    # Act
    service.add_free_tag(str(image_path), "New")
    service.remove_free_tag(str(image_path), "new")

    # Assert
    loaded = sidecars.read(image_path)
    assert loaded is not None
    assert loaded.sidecar.tags == ()
    assert loaded.sidecar.free_tags == ("Existing",)
    assert loaded.sidecar.extra == {"top_extension": {"enabled": True}}
    assert loaded.sidecar.source.extra == {"source_extension": 1}


def test_tagging_service_add_and_remove_free_tag_updates_catalog(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, image_path = _service(tmp_path)
    # Act
    added = service.add_free_tag(str(image_path), " Family ")
    removed = service.remove_free_tag(str(image_path), "family")

    # Assert
    assert added.sidecar.free_tags == ("Family",)
    assert removed.sidecar.free_tags == ()
    assert removed.sidecar.tags == ()
    assert image_repository.get_free_tags(str(image_path)) == ()
    assert image_repository.search_free_tags("fam") == ("Family",)
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


def test_tagging_service_copy_tags_add_merges_deduplicates_and_excludes_source(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, source_path = _service(tmp_path)
    target_path = _add_indexed_image(image_repository, tmp_path, "target.jpg")
    service.add_free_tag(str(source_path), "Family")
    service.add_free_tag(str(source_path), "Vacation")
    service.add_free_tag(str(target_path), "family")
    service.add_free_tag(str(target_path), "Archive")

    # Act
    result = service.copy_tags_to_paths(
        str(source_path),
        [str(source_path), str(target_path), str(target_path)],
        CopyTagsMode.ADD,
    )

    # Assert
    target = service.get_image_tagging_state(str(target_path)).sidecar
    assert result.succeeded_count == 1
    assert len(result.items) == 1
    assert target is not None
    assert target.tags == ()
    assert set(target.free_tags) == {"Family", "Archive", "Vacation"}
    assert service.get_image_tagging_state(str(source_path)).sidecar is not None


def test_tagging_service_copy_tags_add_copies_only_applicable_exclusions(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, source_path = _service(tmp_path)
    target_path = _add_indexed_image(image_repository, tmp_path, "target.jpg")
    target_stat = target_path.stat()
    image_repository.upsert_image(
        str(target_path),
        target_path.name,
        target_stat.st_mtime,
        target_stat.st_size,
        {"IPTC:Keywords": ["Private", "Target only"]},
        "",
    )
    service.set_embedded_tag_excluded(str(source_path), "Private", True)
    service.set_embedded_tag_excluded(str(source_path), "Source only", True)
    service.set_all_embedded_tags_excluded(str(source_path), True)

    # Act
    result = service.copy_tags_to_paths(
        str(source_path),
        [str(target_path)],
        CopyTagsMode.ADD,
    )

    # Assert
    target = service.get_image_tagging_state(str(target_path)).sidecar
    assert result.succeeded_count == 1
    assert target is not None
    assert target.excluded_embedded_tags == ("Private",)
    assert target.exclude_all_embedded_tags is True


def test_tagging_service_copy_tags_replace_preserves_target_sidecar_metadata(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, source_path = _service(tmp_path)
    target_path = _add_indexed_image(image_repository, tmp_path, "target.jpg")
    service.add_free_tag(str(source_path), "Family")
    service.set_embedded_tag_excluded(str(source_path), "Private", True)
    service.set_embedded_tag_excluded(str(source_path), "Source only", True)
    target_tag = ImageTag(
        concept_id="loc-tgm:tgm000002",
        label="Photographs",
        category="genre_format",
        provenance=TagProvenance(
            method="manual",
            accepted_at="2026-08-01T00:00:00Z",
            vocabulary_checksum="sha256:old",
        ),
    )
    target_stat = target_path.stat()
    image_repository.upsert_image(
        str(target_path),
        target_path.name,
        target_stat.st_mtime,
        target_stat.st_size,
        {"IPTC:Keywords": ["Private", "Target only"]},
        "",
    )
    FilesystemSidecarRepository().write(
        target_path,
        ImageSidecar(
            source=SidecarSource(
                filename=target_path.name,
                size=target_stat.st_size,
                mtime_ns=target_stat.st_mtime_ns,
                extra={"source_extension": "keep"},
            ),
            updated_at="2026-08-01T00:00:00Z",
            tags=(target_tag,),
            free_tags=("Archive",),
            excluded_embedded_tags=("Target only",),
            exclude_all_embedded_tags=True,
            extra={"top_extension": "keep"},
        ),
        expected_revision=None,
    )

    # Act
    result = service.copy_tags_to_paths(
        str(source_path),
        [str(target_path)],
        CopyTagsMode.REPLACE,
    )

    # Assert
    target = result.items[0]
    loaded = FilesystemSidecarRepository().read(target_path)
    assert target.status is BulkTagStatus.SUCCEEDED
    assert loaded is not None
    assert loaded.sidecar.tags == ()
    assert loaded.sidecar.free_tags == ("Family",)
    assert loaded.sidecar.excluded_embedded_tags == ("Private",)
    assert loaded.sidecar.exclude_all_embedded_tags is False
    assert loaded.sidecar.source.filename == "target.jpg"
    assert loaded.sidecar.source.extra == {"source_extension": "keep"}
    assert loaded.sidecar.extra == {"top_extension": "keep"}


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
        service.add_free_tag(str(image_path), "Family")
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
    service.add_free_tag(str(image_path), "Existing")
    conflicting_service = TaggingService(
        image_repository,
        _ConflictingSidecarRepository(),
        clock=lambda: NOW,
    )

    # Act / Assert
    with pytest.raises(TaggingConflictError, match="changed externally"):
        conflicting_service.add_free_tag(str(image_path), "Family")



def test_tagging_service_copy_cancellation_retains_completed_targets(
    tmp_path: Path,
) -> None:
    # Arrange
    service, image_repository, first_path = _service(tmp_path)
    second_path = _add_indexed_image(image_repository, tmp_path, "second.jpg")
    third_path = _add_indexed_image(image_repository, tmp_path, "third.jpg")
    fourth_path = _add_indexed_image(image_repository, tmp_path, "fourth.jpg")
    service.add_free_tag(str(first_path), "Family")
    service.add_free_tag(str(second_path), "Family")
    progress: list[str] = []
    checks = 0

    def cancel_after_two() -> bool:
        nonlocal checks
        checks += 1
        return checks > 2

    # Act
    result = service.copy_tags_to_paths(
        str(first_path),
        (str(second_path), str(third_path), str(fourth_path)),
        CopyTagsMode.ADD,
        on_progress=lambda _done, _total, item: progress.append(item.image_path),
        cancel_check=cancel_after_two,
    )

    # Assert
    assert [item.status for item in result.items] == [
        BulkTagStatus.SKIPPED,
        BulkTagStatus.SUCCEEDED,
    ]
    assert result.cancelled is True
    assert progress == [str(second_path), str(third_path)]
    assert service.get_image_tagging_state(str(third_path)).free_tags == ("Family",)
    assert not FilesystemSidecarRepository.sidecar_path(fourth_path).exists()


