from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.settings_model import SettingsModel


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    """Path to a fresh per-database settings.json inside a temp dir."""
    return tmp_path / "settings.json"


def test_json_export_defaults_are_compact(qtbot: QtBot, settings_file: Path) -> None:
    # Arrange / Act
    model = SettingsModel(settings_file)

    # Assert
    fmt = model.json_export_format
    assert (fmt.pretty, fmt.indent_style, fmt.indent_size) == (False, "space", 2)


def test_set_json_export_pretty_persists_across_reload(qtbot: QtBot, settings_file: Path) -> None:
    # Arrange
    model = SettingsModel(settings_file)

    # Act
    model.setJsonExportPretty(True)
    reloaded = SettingsModel(settings_file)

    # Assert
    assert reloaded.jsonExportPretty is True


def test_set_json_indent_style_tab_persists(qtbot: QtBot, settings_file: Path) -> None:
    # Arrange
    model = SettingsModel(settings_file)

    # Act
    model.setJsonExportIndentStyle("tab")
    reloaded = SettingsModel(settings_file)

    # Assert
    assert reloaded.jsonExportIndentStyle == "tab"


def test_set_json_indent_style_rejects_unknown_value(qtbot: QtBot, settings_file: Path) -> None:
    # Arrange
    model = SettingsModel(settings_file)

    # Act
    model.setJsonExportIndentStyle("curly")

    # Assert
    assert model.jsonExportIndentStyle == "space"


def test_set_json_indent_size_clamps_to_supported_range(qtbot: QtBot, settings_file: Path) -> None:
    # Arrange
    model = SettingsModel(settings_file)

    # Act
    model.setJsonExportIndentSize(999)

    # Assert
    assert model.jsonExportIndentSize == 8


def test_corrupt_indent_size_falls_back_to_clamped_value(qtbot: QtBot, settings_file: Path) -> None:
    # Arrange
    settings_file.write_text(json.dumps({"jsonExportIndentSize": 0}), encoding="utf-8")

    # Act
    model = SettingsModel(settings_file)

    # Assert
    assert model.jsonExportIndentSize == 1
