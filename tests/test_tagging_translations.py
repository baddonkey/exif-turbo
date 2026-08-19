from __future__ import annotations

import json
from pathlib import Path
import re

from babel.messages.pofile import read_po  # type: ignore[import-untyped]
import pytest

from scripts.populate_translations import TRANSLATIONS


_ROOT = Path(__file__).resolve().parents[1]
_QML_DIR = _ROOT / "src" / "exif_turbo" / "ui" / "qml"
_LOCALES_DIR = _ROOT / "src" / "exif_turbo" / "i18n" / "locales"
_QSTR_RE = re.compile(r'qsTr\("((?:[^"\\]|\\.)*)"\)')


def _qml_messages(filename: str) -> set[str]:
    text = (_QML_DIR / filename).read_text(encoding="utf-8")
    return {
        json.loads(f'"{match.group(1)}"')
        for match in _QSTR_RE.finditer(text)
    }


_TAGGING_MESSAGES = (
    _qml_messages("TaggingDrawer.qml")
    | _qml_messages("TaggingSettings.qml")
    | {
        "%1 / %2 images",
        "Choose Derivative Target Folder",
        "Derivative Generation Complete",
        "Generate Tagged Derivatives for &Marked Images (%1 selected)",
        "Generate Tagged Derivatives for Current &Results...",
        "Generating Tagged Derivatives",
        "Open tagging (Ctrl+T)",
        "Close",
        "Choose whether to add or replace tags.",
        "Choose a folder in Browse first.",
        "Choose a valid copy target.",
        "Copied tags to {} image(s). Unchanged: {}. Problems: {}.",
        "Added to {} image(s). Already tagged: {}. Problems: {}.",
        "Removed from {} image(s). Already absent: {}. Problems: {}.",
        "Canceled. {}",
        "Created derivative: {}",
        "Created 1 derivative.",
        "Created {} derivatives in {}.",
        "Created {} derivatives.",
        "No derivatives were created.",
        "{} image(s) had no accepted tags.",
        "{} destination file(s) already existed.",
        "{} derivative(s) failed.",
        "First failure ({}): {}",
        "{} derivative(s) canceled.",
        "Refresh Tags",
        "Re-read sidecar tag files for indexed images in this folder",
        "Re-reading sidecar tags\u2026",
        "Refreshing sidecar tags\u2026",
        "Refreshed sidecar tags for {count} images.",
        "Refreshed tags for {count} images; {errors} sidecars had errors.",
    }
)


@pytest.mark.parametrize("language", ("de", "fr", "it", "rm"))
def test_tagging_catalog_supported_locale_has_no_missing_translations(
    language: str,
) -> None:
    # Arrange
    po_path = _LOCALES_DIR / language / "LC_MESSAGES" / "exif_turbo.po"
    with po_path.open(encoding="utf-8") as stream:
        catalog = read_po(stream)

    # Act
    missing = sorted(
        message_id
        for message_id in _TAGGING_MESSAGES
        if (message := catalog.get(message_id)) is None or not message.string
    )

    # Assert
    assert missing == []


@pytest.mark.parametrize("language", ("de", "fr", "it", "rm"))
def test_tagging_population_source_supported_locale_has_all_qml_messages(
    language: str,
) -> None:
    # Arrange
    translations = TRANSLATIONS[language]
    qml_messages = _qml_messages("TaggingDrawer.qml") | _qml_messages(
        "TaggingSettings.qml"
    )

    # Act
    missing = sorted(message for message in qml_messages if not translations.get(message))

    # Assert
    assert missing == []