from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.models.vocabulary import (
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
    VocabularySnapshot,
)
from exif_turbo.tagging.derivative_export_service import (
    DerivativeExportError,
    DerivativeExportService,
    DerivativeExportStatus,
)
from exif_turbo.tagging.sidecar_repository import FilesystemSidecarRepository
from exif_turbo.tagging.vocabulary_snapshot_repository import (
    VocabularySnapshotRepository,
)


class FakeMetadataWriter:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[
            tuple[Path, tuple[str, ...], tuple[Path, ...], tuple[str, ...], bool]
        ] = []

    def write_keywords(
        self,
        target: Path,
        labels: Sequence[str],
        *,
        forbidden_sources: Iterable[Path] = (),
        excluded_labels: Iterable[str] = (),
        preserve_existing_keywords: bool = True,
    ) -> None:
        self.calls.append(
            (
                target,
                tuple(labels),
                tuple(forbidden_sources),
                tuple(excluded_labels),
                preserve_existing_keywords,
            )
        )
        if self.error is not None:
            raise self.error
        target.write_bytes(target.read_bytes() + b"-tagged")


class FakeLocalizationService:
    def export_labels(
        self,
        concept_id: str,
        canonical_label: str,
        *,
        mode: str,
        interface_locale: str,
        selected_locales: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        localized = {
            "de": "Hirsche",
            "fr": "Cerfs",
        }
        if mode == "interface":
            return (localized.get(interface_locale, canonical_label),)
        if mode == "selected":
            labels = tuple(
                canonical_label if locale == "en" else localized[locale]
                for locale in selected_locales
                if locale == "en" or locale in localized
            )
            return labels or (canonical_label,)
        return (canonical_label,)


def _index_image(
    repository: ImageIndexRepository,
    image_path: Path,
    *labels: str,
) -> None:
    repository.upsert_image(
        str(image_path), image_path.name, image_path.stat().st_mtime, image_path.stat().st_size, {}, ""
    )
    tags = tuple(
        ImageTag(
            concept_id=f"loc-tgm:tgm{index:06d}",
            label=label,
            category="subject",
            provenance=TagProvenance(
                method="manual",
                accepted_at="2026-08-09T12:00:00Z",
                vocabulary_checksum="sha256:tgm",
            ),
        )
        for index, label in enumerate(labels, start=1)
    )
    if tags:
        sidecar = ImageSidecar(
            source=SidecarSource(filename=image_path.name),
            updated_at="2026-08-09T12:00:00Z",
            tags=tags,
        )
        revision = FilesystemSidecarRepository().write(
            image_path, sidecar, expected_revision=None
        )
        repository.replace_accepted_tags_and_sidecar_state(
            str(image_path),
            sidecar,
            sidecar_path=f"{image_path}.sidecar.json",
            sidecar_mtime_ns=revision.mtime_ns,
            sidecar_size=revision.size,
            sidecar_checksum=revision.sha256,
            sync_status="synced",
        )


def _vocabulary_repository(tmp_path: Path) -> VocabularySnapshotRepository:
    repository = VocabularySnapshotRepository(tmp_path / "wikidata.json.gz")
    repository.activate(
        VocabularySnapshot(
            concepts=(
                VocabularyConcept(
                    concept_id="wikidata:Q42",
                    category=VocabularyCategory.SUBJECT,
                    canonical_label="English author",
                    localized_terms=(
                        LocalizedVocabularyTerms("en", "English author"),
                        LocalizedVocabularyTerms("de", "Englischer Autor"),
                        LocalizedVocabularyTerms("fr", "International author"),
                        LocalizedVocabularyTerms("it", "International author"),
                    ),
                    source_uri="https://www.wikidata.org/entity/Q42",
                    license_id="CC0-1.0",
                ),
            ),
            version=1,
            created_at=datetime(2026, 8, 23, tzinfo=UTC),
            source_name="Wikidata",
            source_dump_uri="file:///offline/wikidata.json",
            source_dump_sha256="a" * 64,
            manifest_sha256="b" * 64,
            license_id="CC0-1.0",
        )
    )
    return repository


def _write_wikidata_sidecar(image_path: Path) -> None:
    FilesystemSidecarRepository().write(
        image_path,
        ImageSidecar(
            source=SidecarSource(filename=image_path.name),
            updated_at="2026-08-23T12:00:00Z",
            schema_version=2,
            tags=(
                ImageTag(
                    concept_id="wikidata:Q42",
                    label="Stale sidecar label",
                    vocabulary="wikidata",
                    category="subject",
                    provenance=TagProvenance(
                        method="manual",
                        accepted_at="2026-08-23T12:00:00Z",
                        vocabulary_checksum=f"sha256:{'b' * 64}",
                    ),
                ),
            ),
        ),
        expected_revision=None,
    )


def test_create_plan_preserves_relative_tree_and_sorts_unique_labels(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "events" / "photo.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Zebras", "deer", "Zebras")
    service = DerivativeExportService(repo, FakeMetadataWriter())

    # Act
    plan = service.create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].destination == tmp_path / "output" / "events" / "photo.jpg"
    assert plan.items[0].labels == ("deer", "Zebras")


def test_create_plan_includes_custom_free_tags(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")
    sidecar_repository = FilesystemSidecarRepository()
    loaded_sidecar = sidecar_repository.read(image_path)
    assert loaded_sidecar is not None
    updated_sidecar = ImageSidecar(
        source=SidecarSource(filename=image_path.name),
        updated_at="2026-08-09T12:00:00Z",
        tags=repo.get_accepted_tags(str(image_path)),
        free_tags=("Family",),
    )
    revision = sidecar_repository.write(
        image_path,
        updated_sidecar,
        expected_revision=loaded_sidecar.revision,
    )
    repo.replace_accepted_tags_and_sidecar_state(
        str(image_path),
        updated_sidecar,
        sidecar_path=f"{image_path}.sidecar.json",
        sidecar_mtime_ns=revision.mtime_ns,
        sidecar_size=revision.size,
        sidecar_checksum=revision.sha256,
        sync_status="synced",
    )

    # Act
    plan = DerivativeExportService(repo, FakeMetadataWriter()).create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].labels == ("Deer", "Family")


def test_create_plan_interface_language_localizes_controlled_tags(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")
    service = DerivativeExportService(
        repo,
        FakeMetadataWriter(),
        localization_service=FakeLocalizationService(),  # type: ignore[arg-type]
        tag_export_mode="interface",
        interface_locale="de",
    )

    # Act
    plan = service.create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].labels == ("Hirsche",)


def test_create_plan_selected_languages_exports_each_available_label(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")
    service = DerivativeExportService(
        repo,
        FakeMetadataWriter(),
        localization_service=FakeLocalizationService(),  # type: ignore[arg-type]
        tag_export_mode="selected",
        selected_locales=("en", "fr"),
    )

    # Act
    plan = service.create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].labels == ("Cerfs", "Deer")


def test_create_plan_wikidata_modes_use_intrinsic_snapshot_labels(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    repo.upsert_image(str(image_path), image_path.name, 1.0, 8, {}, "")
    _write_wikidata_sidecar(image_path)
    vocabulary = _vocabulary_repository(tmp_path)

    # Act
    canonical = DerivativeExportService(
        repo,
        FakeMetadataWriter(),
        vocabulary_repository=vocabulary,
        tag_export_mode="canonical",
    ).create_plan({source_root: "source"}, tmp_path / "canonical", image_paths=[image_path])
    interface = DerivativeExportService(
        repo,
        FakeMetadataWriter(),
        vocabulary_repository=vocabulary,
        tag_export_mode="interface",
        interface_locale="de",
    ).create_plan({source_root: "source"}, tmp_path / "interface", image_paths=[image_path])
    selected = DerivativeExportService(
        repo,
        FakeMetadataWriter(),
        vocabulary_repository=vocabulary,
        tag_export_mode="selected",
        selected_locales=("en", "fr", "it"),
    ).create_plan({source_root: "source"}, tmp_path / "selected", image_paths=[image_path])

    # Assert
    assert canonical.items[0].labels == ("English author",)
    assert interface.items[0].labels == ("Englischer Autor",)
    assert selected.items[0].labels == (
        "English author",
        "International author",
    )


def test_create_plan_excluded_embedded_tag_omits_matching_label(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    repo.upsert_image(
        str(image_path),
        image_path.name,
        image_path.stat().st_mtime,
        image_path.stat().st_size,
        {"IPTC:Keywords": ["Keep", "Private"]},
        "",
    )
    FilesystemSidecarRepository().write(
        image_path,
        ImageSidecar(
            source=SidecarSource(filename=image_path.name),
            updated_at="2026-08-19T12:00:00Z",
            free_tags=("Added",),
            excluded_embedded_tags=("private",),
        ),
        expected_revision=None,
    )

    # Act
    plan = DerivativeExportService(repo, FakeMetadataWriter()).create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].labels == ("Added", "Keep")
    assert plan.items[0].excluded_embedded_tags == ("private",)


def test_create_plan_exclude_all_embedded_tags_omits_every_embedded_label(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    repo.upsert_image(
        str(image_path),
        image_path.name,
        image_path.stat().st_mtime,
        image_path.stat().st_size,
        {"IPTC:Keywords": ["Keep", "Private"]},
        "",
    )
    FilesystemSidecarRepository().write(
        image_path,
        ImageSidecar(
            source=SidecarSource(filename=image_path.name),
            updated_at="2026-08-19T12:00:00Z",
            free_tags=("Added",),
            exclude_all_embedded_tags=True,
        ),
        expected_revision=None,
    )

    # Act
    plan = DerivativeExportService(repo, FakeMetadataWriter()).create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].labels == ("Added",)
    assert plan.items[0].exclude_all_embedded_tags is True


def test_create_plan_sidecar_tags_missing_from_cache_includes_tags(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    video_path = source_root / "clip.mp4"
    source_root.mkdir()
    video_path.write_bytes(b"original")
    _index_image(repo, video_path)
    FilesystemSidecarRepository().write(
        video_path,
        ImageSidecar(
            source=SidecarSource(filename=video_path.name),
            updated_at="2026-08-15T07:16:50Z",
            free_tags=("Katzenpfote",),
        ),
        expected_revision=None,
    )

    # Act
    plan = DerivativeExportService(repo, FakeMetadataWriter()).create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[video_path]
    )

    # Assert
    assert plan.items[0].labels == ("Katzenpfote",)
    assert plan.items[0].planned_status is None


def test_create_plan_sidecar_tags_differ_from_cache_uses_sidecar_tags(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Stale cache tag")
    sidecar_repository = FilesystemSidecarRepository()
    loaded_sidecar = sidecar_repository.read(image_path)
    assert loaded_sidecar is not None
    sidecar_repository.write(
        image_path,
        ImageSidecar(
            source=SidecarSource(filename=image_path.name),
            updated_at="2026-08-15T07:16:50Z",
            free_tags=("Authoritative sidecar tag",),
        ),
        expected_revision=loaded_sidecar.revision,
    )

    # Act
    plan = DerivativeExportService(repo, FakeMetadataWriter()).create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].labels == ("Authoritative sidecar tag",)


def test_create_plan_cache_tags_without_sidecar_skips_source(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Cache-only tag")
    FilesystemSidecarRepository.sidecar_path(image_path).unlink()

    # Act
    plan = DerivativeExportService(repo, FakeMetadataWriter()).create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].labels == ()
    assert plan.items[0].planned_status is DerivativeExportStatus.SKIPPED_UNTAGGED


def test_create_plan_preserves_embedded_keywords_with_accepted_additions(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")
    repo.upsert_image(
        str(image_path),
        image_path.name,
        image_path.stat().st_mtime,
        image_path.stat().st_size,
        {"XMP-dc:Subject": "['Original', 'deer']"},
        "",
    )

    # Act
    plan = DerivativeExportService(repo, FakeMetadataWriter()).create_plan(
        {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
    )

    # Assert
    assert plan.items[0].labels == ("Deer", "Original")


def test_create_plan_single_used_nested_root_omits_redundant_root_folder(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    parent_root = tmp_path / "library"
    child_root = parent_root / "archive"
    other_root = tmp_path / "other"
    image_path = child_root / "year" / "photo.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")

    # Act
    plan = DerivativeExportService(repo, FakeMetadataWriter()).create_plan(
        {parent_root: "library", child_root: "archive", other_root: "other"},
        tmp_path / "output",
        image_paths=[image_path],
    )

    # Assert
    assert plan.items[0].destination == tmp_path / "output" / "year" / "photo.jpg"


def test_create_plan_duplicate_root_labels_are_collision_safe_and_deterministic(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_image = first_root / "photo.jpg"
    second_image = second_root / "photo.jpg"
    first_root.mkdir()
    second_root.mkdir()
    first_image.write_bytes(b"first")
    second_image.write_bytes(b"second")
    _index_image(repo, first_image, "Deer")
    _index_image(repo, second_image, "Forests")
    service = DerivativeExportService(repo, FakeMetadataWriter())

    # Act
    plan = service.create_plan(
        {first_root: "photos", second_root: "photos"},
        tmp_path / "output",
        image_paths=[second_image, first_image],
    )

    # Assert
    destinations = [item.destination for item in plan.items]
    repeated = service.create_plan(
        {second_root: "photos", first_root: "photos"},
        tmp_path / "output",
        image_paths=[first_image, second_image],
    )
    assert len(set(destinations)) == 2
    assert all(destination.parent.name.startswith("photos-") for destination in destinations)
    assert [item.destination for item in repeated.items] == destinations


def test_create_plan_output_inside_source_rejected_before_creation(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    image_path = source_root / "photo.jpg"
    source_root.mkdir()
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")
    output_root = source_root / "derivatives"

    # Act / Assert
    with pytest.raises(DerivativeExportError, match="outside indexed source root"):
        DerivativeExportService(repo).create_plan(
            {source_root: "source"}, output_root, image_paths=[image_path]
        )
    assert not output_root.exists()


def test_create_plan_source_traversal_rejected_before_creation(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    outside = tmp_path / "outside.jpg"
    source_root.mkdir()
    outside.write_bytes(b"original")
    _index_image(repo, outside, "Deer")
    output_root = tmp_path / "output"

    # Act / Assert
    with pytest.raises(DerivativeExportError, match="does not belong"):
        DerivativeExportService(repo).create_plan(
            {source_root: "source"},
            output_root,
            image_paths=[source_root / ".." / "outside.jpg"],
        )
    assert not output_root.exists()


def test_create_plan_single_used_root_avoids_source_destination_alias(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    image_path = first_root / "photo.jpg"
    first_root.mkdir()
    second_root.mkdir()
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")

    # Act
    plan = DerivativeExportService(repo).create_plan(
        {first_root: "first", second_root: "second"},
        tmp_path,
        image_paths=[image_path],
    )

    # Assert
    assert plan.items[0].destination == tmp_path / "photo.jpg"
    assert plan.items[0].destination != image_path


def test_export_existing_destination_skips_without_overwrite(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    source_root.mkdir()
    image_path = source_root / "photo.jpg"
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")
    destination = tmp_path / "output" / "photo.jpg"
    destination.parent.mkdir()
    destination.write_bytes(b"existing")
    writer = FakeMetadataWriter()
    service = DerivativeExportService(repo, writer)

    # Act
    result = service.export(
        service.create_plan(
            {source_root: "source"}, tmp_path / "output", image_paths=[image_path]
        )
    )

    # Assert
    assert result.skipped_existing_count == 1
    assert destination.read_bytes() == b"existing"
    assert writer.calls == []


def test_export_untagged_source_skips_without_creating_output(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    source_root.mkdir()
    image_path = source_root / "photo.jpg"
    image_path.write_bytes(b"original")
    _index_image(repo, image_path)
    output_root = tmp_path / "output"
    service = DerivativeExportService(repo, FakeMetadataWriter())

    # Act
    result = service.export(
        service.create_plan(
            {source_root: "source"}, output_root, image_paths=[image_path]
        )
    )

    # Assert
    assert result.skipped_untagged_count == 1
    assert not output_root.exists()


def test_export_metadata_failure_removes_temp_and_preserves_source(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    source_root.mkdir()
    image_path = source_root / "photo.jpg"
    image_path.write_bytes(b"original")
    original_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    original_mtime = image_path.stat().st_mtime_ns
    _index_image(repo, image_path, "Deer")
    output_root = tmp_path / "output"
    service = DerivativeExportService(
        repo, FakeMetadataWriter(error=RuntimeError("metadata failed"))
    )

    # Act
    result = service.export(
        service.create_plan(
            {source_root: "source"}, output_root, image_paths=[image_path]
        )
    )

    # Assert
    assert result.failed_count == 1
    assert result.items[0].message == "metadata failed"
    assert not (output_root / "photo.jpg").exists()
    assert list(output_root.glob(".*.tmp*")) == []
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == original_hash
    assert image_path.stat().st_mtime_ns == original_mtime


def test_export_copy_error_reports_failure_and_leaves_no_temp(
    tmp_path: Path,
    repo: ImageIndexRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    source_root.mkdir()
    image_path = source_root / "photo.jpg"
    image_path.write_bytes(b"original")
    _index_image(repo, image_path, "Deer")
    output_root = tmp_path / "output"
    service = DerivativeExportService(repo, FakeMetadataWriter())

    def fail_copy(_source: Path, _destination: Path) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr(shutil, "copy2", fail_copy)

    # Act
    result = service.export(
        service.create_plan(
            {source_root: "source"}, output_root, image_paths=[image_path]
        )
    )

    # Assert
    assert result.failed_count == 1
    assert result.items[0].message == "copy failed"
    assert list(output_root.glob(".*.tmp*")) == []


def test_export_cancellation_preserves_completed_final_and_cancels_remaining(
    tmp_path: Path, repo: ImageIndexRepository
) -> None:
    # Arrange
    source_root = tmp_path / "source"
    source_root.mkdir()
    first_image = source_root / "a.jpg"
    second_image = source_root / "b.jpg"
    first_image.write_bytes(b"first")
    second_image.write_bytes(b"second")
    _index_image(repo, first_image, "Deer")
    _index_image(repo, second_image, "Forests")
    output_root = tmp_path / "output"
    writer = FakeMetadataWriter()
    service = DerivativeExportService(repo, writer)
    canceled = False

    def on_progress(_done: int, _total: int, _item: object) -> None:
        nonlocal canceled
        canceled = True

    # Act
    result = service.export(
        service.create_plan(
            {source_root: "source"},
            output_root,
            image_paths=[first_image, second_image],
        ),
        on_progress=on_progress,
        cancel_check=lambda: canceled,
    )

    # Assert
    assert result.canceled_count == 1
    assert result.copied_count == 1
    assert (output_root / "a.jpg").read_bytes() == b"first-tagged"
    assert not (output_root / "b.jpg").exists()
    assert list(output_root.glob(".*.tmp*")) == []