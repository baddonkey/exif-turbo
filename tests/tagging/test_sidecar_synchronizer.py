from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.models.vocabulary import (
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
    VocabularySnapshot,
)
from exif_turbo.tagging.sidecar_repository import (
    FilesystemSidecarRepository,
    LoadedSidecar,
)
from exif_turbo.tagging.sidecar_synchronizer import SidecarSynchronizer
from exif_turbo.tagging.vocabulary_snapshot_repository import (
    VocabularySnapshotRepository,
)


class _TrackingSidecarRepository(FilesystemSidecarRepository):
    def __init__(self) -> None:
        self.read_count = 0

    def read(self, image_path: Path) -> LoadedSidecar | None:
        self.read_count += 1
        return super().read(image_path)


def _sidecar(filename: str) -> ImageSidecar:
    return ImageSidecar(
        source=SidecarSource(filename=filename),
        updated_at="2026-08-09T12:30:00Z",
        tags=(
            ImageTag(
                concept_id="loc-tgm:tgm000001",
                label="Mountain landscapes",
                category="subject",
                provenance=TagProvenance(
                    method="manual",
                    accepted_at="2026-08-09T12:30:00Z",
                    vocabulary_checksum="sha256:abc123",
                ),
            ),
        ),
        free_tags=("Family",),
    )


def _vocabulary_repository(tmp_path: Path) -> VocabularySnapshotRepository:
    repository = VocabularySnapshotRepository(tmp_path / "wikidata.json.gz")
    repository.activate(
        VocabularySnapshot(
            concepts=(
                VocabularyConcept(
                    concept_id="wikidata:Q42",
                    category=VocabularyCategory.SUBJECT,
                    canonical_label="Douglas Adams",
                    localized_terms=(
                        LocalizedVocabularyTerms("en", "Douglas Adams"),
                        LocalizedVocabularyTerms(
                            "de", "Englischer Schriftsteller", aliases=("Autor",)
                        ),
                        LocalizedVocabularyTerms(
                            "fr", "Ecrivain anglais", aliases=("Auteur",)
                        ),
                        LocalizedVocabularyTerms(
                            "it", "Scrittore inglese", aliases=("Autore",)
                        ),
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


def test_synchronize_unchanged_sidecar_skips_second_parse(tmp_path: Path) -> None:
    # Arrange
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"original image")
    image_stat = image_path.stat()
    image_repository = ImageIndexRepository(tmp_path / "index.db", key="")
    image_repository.upsert_image(
        str(image_path),
        image_path.name,
        image_stat.st_mtime,
        image_stat.st_size,
        {},
        "",
    )
    sidecar_repository = _TrackingSidecarRepository()
    sidecar_repository.write(
        image_path,
        _sidecar(image_path.name),
        expected_revision=None,
    )
    synchronizer = SidecarSynchronizer(image_repository, sidecar_repository)
    synchronizer.synchronize([str(image_path)])
    synchronized_free_tags = image_repository.get_free_tags(str(image_path))
    free_tag_search_count = image_repository.count_images("Family")

    # Act
    result = synchronizer.synchronize([str(image_path)])

    # Assert
    assert result.error_count == 0
    assert sidecar_repository.read_count == 1
    assert synchronized_free_tags == ("Family",)
    assert free_tag_search_count == 1
    image_repository.close()


def test_synchronize_force_rereads_same_stamp_external_edit(
    tmp_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"original image")
    image_stat = image_path.stat()
    image_repository = ImageIndexRepository(tmp_path / "index.db", key="")
    image_repository.upsert_image(
        str(image_path),
        image_path.name,
        image_stat.st_mtime,
        image_stat.st_size,
        {},
        "",
    )
    sidecar_repository = _TrackingSidecarRepository()
    sidecar_repository.write(image_path, _sidecar(image_path.name), None)
    synchronizer = SidecarSynchronizer(image_repository, sidecar_repository)
    synchronizer.synchronize([str(image_path)])
    sidecar_path = sidecar_repository.sidecar_path(image_path)
    original_stat = sidecar_path.stat()
    original_bytes = sidecar_path.read_bytes()
    changed_bytes = original_bytes.replace(b"Family", b"Travel")
    assert len(changed_bytes) == len(original_bytes)
    sidecar_path.write_bytes(changed_bytes)
    os.utime(
        sidecar_path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    progress: list[tuple[int, int, str]] = []

    # Act
    result = synchronizer.synchronize(
        [str(image_path)],
        on_progress=lambda done, total, path: progress.append((done, total, path)),
        force=True,
    )

    # Assert
    assert result.error_count == 0
    assert sidecar_repository.read_count == 2
    assert image_repository.get_free_tags(str(image_path)) == ("Travel",)
    assert image_repository.count_images("Family") == 0
    assert image_repository.count_images("Travel") == 1
    assert progress == [(1, 1, str(image_path))]
    image_repository.close()


def test_synchronize_wikidata_sidecar_indexes_required_locale_labels(
    tmp_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"original image")
    image_repository = ImageIndexRepository(tmp_path / "index.db", key="")
    image_repository.upsert_image(
        str(image_path), image_path.name, 1.0, image_path.stat().st_size, {}, ""
    )
    sidecar_repository = FilesystemSidecarRepository()
    sidecar_repository.write(
        image_path,
        ImageSidecar(
            source=SidecarSource(filename=image_path.name),
            updated_at="2026-08-09T12:30:00Z",
            schema_version=2,
            tags=(
                ImageTag(
                    concept_id="wikidata:Q42",
                    label="Douglas Adams",
                    vocabulary="wikidata",
                    category="subject",
                    provenance=TagProvenance(
                        method="manual",
                        accepted_at="2026-08-09T12:30:00Z",
                        vocabulary_checksum=f"sha256:{'b' * 64}",
                    ),
                ),
            ),
        ),
        expected_revision=None,
    )
    synchronizer = SidecarSynchronizer(
        image_repository,
        sidecar_repository,
        vocabulary_repository=_vocabulary_repository(tmp_path),
    )

    # Act
    result = synchronizer.synchronize([str(image_path)], force=True)

    # Assert
    assert result.error_count == 0
    assert image_repository.count_images('"Englischer Schriftsteller"') == 1
    assert image_repository.count_images('"Ecrivain anglais"') == 1
    assert image_repository.count_images('"Scrittore inglese"') == 1
    assert image_repository.count_images("Autor") == 1
    assert image_repository.count_images("Auteur") == 1
    assert image_repository.count_images("Autore") == 1
    image_repository.close()