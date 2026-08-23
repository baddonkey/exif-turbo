from __future__ import annotations

import json
from pathlib import Path

from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.settings_model import SettingsModel


def test_tagging_settings_defaults_are_conservative(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange / Act
    model = SettingsModel(tmp_path / "settings.json")

    # Assert
    assert model.taggingEnabled is False
    assert model.proposalThreshold == 0.20
    assert model.autoAcceptEnabled is False
    assert model.autoAcceptThreshold == 0.28
    assert model.showRawTagCandidates is False
    assert model.metadataLanguage == "en"
    assert model.metadataLanguageCodes == ["en", "de", "fr", "it"]
    assert model.tagExportMode == "canonical"
    assert model.tagExportLanguages == ["en"]


def test_tagging_settings_persist_across_reload(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)

    # Act
    model.setTaggingEnabled(True)
    model.setProposalThreshold(0.4)
    model.setAutoAcceptEnabled(True)
    model.setAutoAcceptThreshold(0.8)
    model.setShowRawTagCandidates(True)
    model.setMetadataLanguage("de")
    model.setTagExportMode("selected")
    model.setTagExportLanguageEnabled("es", True)
    reloaded = SettingsModel(settings_path)

    # Assert
    assert reloaded.taggingEnabled is True
    assert reloaded.proposalThreshold == 0.4
    assert reloaded.autoAcceptEnabled is True
    assert reloaded.autoAcceptThreshold == 0.8
    assert reloaded.showRawTagCandidates is True
    assert reloaded.metadataLanguage == "de"
    assert reloaded.tagExportMode == "selected"
    assert reloaded.tagExportLanguages == ["en", "es"]


def test_metadata_language_rejects_locale_outside_vocabulary_contract(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"metadataLanguage":"es"}', encoding="utf-8")
    model = SettingsModel(settings_path)

    # Act
    model.setMetadataLanguage("es")

    # Assert
    assert model.metadataLanguage == "en"


def test_proposal_threshold_clamps_and_keeps_auto_accept_stricter(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    model = SettingsModel(tmp_path / "settings.json")

    # Act
    model.setProposalThreshold(5.0)

    # Assert
    assert model.proposalThreshold == 0.99
    assert model.autoAcceptThreshold == 1.0


def test_auto_accept_threshold_clamps_above_proposal_threshold(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    model = SettingsModel(tmp_path / "settings.json")
    model.setProposalThreshold(0.5)

    # Act
    model.setAutoAcceptThreshold(0.2)

    # Assert
    assert model.autoAcceptThreshold == 0.51


def test_loaded_tagging_thresholds_are_clamped_and_reconciled(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "proposalThreshold": 2.0,
                "autoAcceptThreshold": -1.0,
            }
        ),
        encoding="utf-8",
    )

    # Act
    model = SettingsModel(settings_path)

    # Assert
    assert model.proposalThreshold == 0.99
    assert model.autoAcceptThreshold == 1.0


def test_legacy_default_thresholds_migrate_to_multilingual_calibration(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "proposalThreshold": 0.24,
                "autoAcceptThreshold": 0.32,
            }
        ),
        encoding="utf-8",
    )

    # Act
    model = SettingsModel(settings_path)
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))

    # Assert
    assert model.proposalThreshold == 0.20
    assert model.autoAcceptThreshold == 0.28
    assert persisted["proposalThresholdCalibration"] == (
        "openclip-xlm-r-b32-laion5b-v1"
    )


def test_legacy_custom_thresholds_are_preserved_during_calibration_migration(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "proposalThreshold": 0.18,
                "autoAcceptThreshold": 0.30,
            }
        ),
        encoding="utf-8",
    )

    # Act
    model = SettingsModel(settings_path)

    # Assert
    assert model.proposalThreshold == 0.18
    assert model.autoAcceptThreshold == 0.30