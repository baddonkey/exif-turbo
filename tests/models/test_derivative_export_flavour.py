from __future__ import annotations

import pytest

from exif_turbo.models.derivative_export_flavour import (
    DerivativeExportFlavour,
    DerivativeFormat,
    MetadataMode,
    ResizeMode,
    default_derivative_export_flavours,
)


def test_default_derivative_export_flavours_include_suggested_presets() -> None:
    # Arrange / Act
    flavours = default_derivative_export_flavours()

    # Assert
    assert [flavour.name for flavour in flavours] == [
        "Original (as is)",
        "Web JPEG",
        "Web PNG",
        "Full Resolution PNG",
        "Thumbnail PNG",
        "Archive TIFF",
    ]
    assert [flavour.selected_by_default for flavour in flavours] == [
        True,
        True,
        True,
        False,
        False,
        False,
    ]


def test_derivative_export_flavour_round_trips_settings() -> None:
    # Arrange
    flavour = default_derivative_export_flavours()[1]

    # Act
    restored = DerivativeExportFlavour.from_dict(flavour.to_dict())

    # Assert
    assert restored == flavour
    assert restored.output_format is DerivativeFormat.JPEG
    assert restored.metadata_mode is MetadataMode.NONE
    assert restored.resize_mode is ResizeMode.LONGEST_EDGE


def test_derivative_export_flavour_rejects_unsafe_suffix() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="unsafe characters"):
        DerivativeExportFlavour(
            "test-flavour",
            "Test",
            DerivativeFormat.PNG,
            "../escape",
        )


def test_derivative_export_flavour_rejects_limited_resize_without_limit() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="require a positive pixel_limit"):
        DerivativeExportFlavour(
            "test-flavour",
            "Test",
            DerivativeFormat.PNG,
            resize_mode=ResizeMode.WIDTH,
        )


def test_derivative_export_flavour_requires_original_metadata_for_byte_copy() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="requires Original metadata mode"):
        DerivativeExportFlavour(
            "test-flavour",
            "Original",
            DerivativeFormat.ORIGINAL,
        )