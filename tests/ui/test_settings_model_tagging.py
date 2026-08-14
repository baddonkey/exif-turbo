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
    assert model.proposalThreshold == 0.24
    assert model.autoAcceptEnabled is False
    assert model.autoAcceptThreshold == 0.32


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
    reloaded = SettingsModel(settings_path)

    # Assert
    assert reloaded.taggingEnabled is True
    assert reloaded.proposalThreshold == 0.4
    assert reloaded.autoAcceptEnabled is True
    assert reloaded.autoAcceptThreshold == 0.8


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