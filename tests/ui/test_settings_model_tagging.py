from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from exif_turbo.models.derivative_export_flavour import default_derivative_export_flavours
from exif_turbo.ui.models.settings_model import SettingsModel


def test_tagging_settings_default_custom_tags_disabled(tmp_path: Path) -> None:
    # Arrange / Act
    model = SettingsModel(tmp_path / "settings.json")

    # Assert
    assert model.taggingEnabled is False
    assert model.autoRepairDerivativeTags is True
    assert model.writeDescriptionToXpComment is True


def test_auto_repair_derivative_tags_persists_across_reload(tmp_path: Path) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)

    # Act
    model.setAutoRepairDerivativeTags(False)
    reloaded = SettingsModel(settings_path)

    # Assert
    assert reloaded.autoRepairDerivativeTags is False
    assert json.loads(settings_path.read_text(encoding="utf-8"))[
        "autoRepairDerivativeTags"
    ] is False


def test_write_description_to_xpcomment_setting_persists_across_reload(
    tmp_path: Path,
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)

    # Act
    model.setWriteDescriptionToXpComment(False)
    reloaded = SettingsModel(settings_path)

    # Assert
    assert reloaded.writeDescriptionToXpComment is False
    assert json.loads(settings_path.read_text(encoding="utf-8"))[
        "writeDescriptionToXpComment"
    ] is False


def test_tagging_settings_persist_custom_tag_switch_and_ignore_legacy_preferences(
    tmp_path: Path,
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "taggingEnabled": True,
                "proposalThreshold": 0.4,
                "showRawTagCandidates": True,
                "metadataLanguage": "de",
                "tagExportMode": "selected",
                "tagExportLanguages": ["en", "fr"],
            }
        ),
        encoding="utf-8",
    )
    model = SettingsModel(settings_path)

    # Act
    model.setTaggingEnabled(False)
    reloaded = SettingsModel(settings_path)
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))

    # Assert
    assert reloaded.taggingEnabled is False
    assert "taggingEnabled" in persisted
    assert "proposalThreshold" not in persisted
    assert "showRawTagCandidates" not in persisted
    assert "metadataLanguage" not in persisted
    assert "tagExportMode" not in persisted
    assert "tagExportLanguages" not in persisted


def test_derivative_export_flavours_default_and_persist_per_database(
    tmp_path: Path,
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)
    flavours = list(model.derivative_export_flavours)
    flavours[1] = replace(flavours[1], name="My Web JPEG")

    # Act
    model.setDerivativeExportFlavours(
        json.dumps([flavour.to_dict() for flavour in flavours])
    )
    reloaded = SettingsModel(settings_path)

    # Assert
    assert [flavour.name for flavour in reloaded.derivative_export_flavours] == [
        flavour.name for flavour in flavours
    ]
    assert len(default_derivative_export_flavours()) == 6
    assert json.loads(settings_path.read_text(encoding="utf-8"))[
        "derivativeExportFlavours"
    ][1]["name"] == "My Web JPEG"


def test_derivative_export_flavours_invalid_json_preserves_current_value(
    tmp_path: Path,
) -> None:
    # Arrange
    model = SettingsModel(tmp_path / "settings.json")
    before = model.derivativeExportFlavoursJson

    # Act
    model.setDerivativeExportFlavours("{")

    # Assert
    assert model.derivativeExportFlavoursJson == before
    assert model.derivativeExportSaveError


def test_derivative_export_flavours_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    # Arrange
    model = SettingsModel(tmp_path / "settings.json")
    flavours = [flavour.to_dict() for flavour in model.derivative_export_flavours]
    flavours.append(flavours[0])
    before = model.derivativeExportFlavoursJson

    # Act
    model.setDerivativeExportFlavours(json.dumps(flavours))

    # Assert
    assert model.derivativeExportFlavoursJson == before
    assert "IDs must be unique" in model.derivativeExportSaveError


def test_derivative_export_flavours_save_failure_keeps_edit_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)
    flavours = list(model.derivative_export_flavours)
    flavours[1] = replace(flavours[1], name="Unsaved Web JPEG")
    serialized = json.dumps([flavour.to_dict() for flavour in flavours])
    original_write_text = Path.write_text

    def fail_write_text(_path: Path, _data: str, **_kwargs: object) -> int:
        raise OSError("read-only settings directory")

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    # Act
    model.setDerivativeExportFlavours(serialized)

    # Assert
    assert model.derivative_export_flavours[1].name == "Unsaved Web JPEG"
    assert "read-only settings directory" in model.derivativeExportSaveError

    # A later valid autosave retries the retained value.
    monkeypatch.setattr(Path, "write_text", original_write_text)
    model.setDerivativeExportFlavours(model.derivativeExportFlavoursJson)

    assert model.derivativeExportSaveError == ""
    assert SettingsModel(settings_path).derivative_export_flavours[1].name == (
        "Unsaved Web JPEG"
    )