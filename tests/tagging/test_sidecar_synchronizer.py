from __future__ import annotations

from pathlib import Path

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.tagging.sidecar_repository import (
    FilesystemSidecarRepository,
    LoadedSidecar,
)
from exif_turbo.tagging.sidecar_synchronizer import SidecarSynchronizer


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