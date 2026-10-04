from __future__ import annotations

import json
from pathlib import Path

from exif_turbo.ui.models.settings_model import SettingsModel


def test_tagging_settings_default_custom_tags_disabled(tmp_path: Path) -> None:
    # Arrange / Act
    model = SettingsModel(tmp_path / "settings.json")

    # Assert
    assert model.taggingEnabled is False


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