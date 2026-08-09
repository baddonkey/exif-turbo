from __future__ import annotations

import json
from pathlib import Path

import pytest

from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import (
    ImageTag,
    SidecarValidationError,
    TagProvenance,
)
from exif_turbo.tagging.sidecar_repository import (
    FilesystemSidecarRepository,
    SidecarConflictError,
)


def _sidecar(filename: str = "photo.jpg") -> ImageSidecar:
    return ImageSidecar(
        source=SidecarSource(filename=filename, size=123, mtime_ns=456),
        updated_at="2026-08-09T12:30:00Z",
        tags=(
            ImageTag(
                concept_id="loc-tgm:tgm000001",
                label="Example term",
                category="subject",
                provenance=TagProvenance(
                    method="manual",
                    accepted_at="2026-08-09T12:30:00Z",
                    vocabulary_checksum="sha256:abc123",
                ),
            ),
        ),
    )


def test_sidecar_repository_write_and_read_round_trips_sidecar(
    tmp_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"image")
    repository = FilesystemSidecarRepository()
    sidecar = _sidecar()

    # Act
    revision = repository.write(image_path, sidecar, expected_revision=None)
    loaded = repository.read(image_path)

    # Assert
    assert loaded is not None
    assert loaded.sidecar == sidecar
    assert loaded.revision == revision
    assert repository.sidecar_path(image_path).name == "photo.jpg.sidecar.json"


def test_sidecar_repository_read_and_write_preserves_unknown_fields(
    tmp_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"image")
    sidecar_path = FilesystemSidecarRepository.sidecar_path(image_path)
    data = _sidecar().to_dict()
    data["future_top_level"] = {"enabled": True}
    data["source"]["future_source"] = "value"
    data["tags"][0]["future_tag"] = [1, 2]
    data["tags"][0]["provenance"]["future_provenance"] = "value"
    sidecar_path.write_text(json.dumps(data), encoding="utf-8")
    repository = FilesystemSidecarRepository()

    # Act
    loaded = repository.read(image_path)
    assert loaded is not None
    repository.write(image_path, loaded.sidecar, loaded.revision)
    rewritten = json.loads(sidecar_path.read_text(encoding="utf-8"))

    # Assert
    assert rewritten["future_top_level"] == {"enabled": True}
    assert rewritten["source"]["future_source"] == "value"
    assert rewritten["tags"][0]["future_tag"] == [1, 2]
    assert rewritten["tags"][0]["provenance"]["future_provenance"] == "value"


def test_sidecar_repository_write_after_external_change_raises_conflict(
    tmp_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"image")
    repository = FilesystemSidecarRepository()
    revision = repository.write(image_path, _sidecar(), expected_revision=None)
    sidecar_path = repository.sidecar_path(image_path)
    external_content = sidecar_path.read_text(encoding="utf-8") + " "
    sidecar_path.write_text(external_content, encoding="utf-8")

    # Act / Assert
    with pytest.raises(SidecarConflictError, match="changed externally"):
        repository.write(image_path, _sidecar(), expected_revision=revision)
    assert sidecar_path.read_text(encoding="utf-8") == external_content


def test_image_sidecar_duplicate_concepts_raises_validation_error() -> None:
    # Arrange
    tag = _sidecar().tags[0]

    # Act / Assert
    with pytest.raises(SidecarValidationError, match="unique by concept_id"):
        ImageSidecar(
            source=SidecarSource(filename="photo.jpg"),
            updated_at="2026-08-09T12:30:00Z",
            tags=(tag, tag),
        )


def test_image_tag_invalid_tgm_identifier_raises_validation_error() -> None:
    # Arrange
    provenance = TagProvenance(
        method="manual",
        accepted_at="2026-08-09T12:30:00Z",
        vocabulary_checksum="sha256:abc123",
    )

    # Act / Assert
    with pytest.raises(SidecarValidationError, match="loc-tgm:tgmNNNNNN"):
        ImageTag(
            concept_id="local:example",
            label="Example",
            category="subject",
            provenance=provenance,
        )


def test_sidecar_repository_invalid_json_raises_validation_error(
    tmp_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photo.jpg"
    sidecar_path = FilesystemSidecarRepository.sidecar_path(image_path)
    sidecar_path.write_text("{invalid", encoding="utf-8")

    # Act / Assert
    with pytest.raises(SidecarValidationError, match="invalid sidecar JSON"):
        FilesystemSidecarRepository().read(image_path)