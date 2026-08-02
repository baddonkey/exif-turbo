from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.utils.preview_render import (
    DEFAULT_VIPS_ALLOWED_EXTENSIONS,
    configure_vips_allowed_extensions,
)


@pytest.fixture(autouse=True)
def default_vips_allowed_extensions() -> None:
    configure_vips_allowed_extensions(DEFAULT_VIPS_ALLOWED_EXTENSIONS)
    yield
    configure_vips_allowed_extensions(DEFAULT_VIPS_ALLOWED_EXTENSIONS)


def test_libvips_extensions_defaults_to_common_image_formats(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange / Act
    model = SettingsModel(tmp_path / "settings.json")

    # Assert
    assert model.libvipsExtensions == list(DEFAULT_VIPS_ALLOWED_EXTENSIONS)


def test_add_libvips_extension_normalizes_and_persists(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)

    # Act
    model.addLibvipsExtension("  BMP  ")
    reloaded = SettingsModel(settings_path)

    # Assert
    assert reloaded.libvipsExtensions[-1] == ".bmp"


def test_add_libvips_extension_rejects_paths_and_wildcards(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    model = SettingsModel(tmp_path / "settings.json")
    original = model.libvipsExtensions

    # Act
    model.addLibvipsExtension("*.bmp")
    model.addLibvipsExtension("folder/image.jpg")

    # Assert
    assert model.libvipsExtensions == original


def test_remove_libvips_extension_persists_empty_allowlist(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"libvipsExtensions": [".tiff"]}), encoding="utf-8")
    model = SettingsModel(settings_path)

    # Act
    model.removeLibvipsExtension(0)
    reloaded = SettingsModel(settings_path)

    # Assert
    assert reloaded.libvipsExtensions == []