from __future__ import annotations

import json

import pytest

from exif_turbo.indexing.indexer_service import metadata_to_text


def test_metadata_to_text_includes_key_and_value() -> None:
    result = metadata_to_text({"Make": "Canon", "Model": "EOS R5"})

    assert "Make" in result
    assert "Canon" in result
    assert "Model" in result
    assert "EOS R5" in result


def test_metadata_to_text_includes_json_blob() -> None:
    metadata = {"ISO": "800", "FNumber": "2.8"}
    result = metadata_to_text(metadata)

    # The JSON blob must be present so FTS5 can match key:value pairs
    parsed = json.loads(result[result.index("{"):result.rindex("}") + 1])
    assert parsed["ISO"] == "800"
    assert parsed["FNumber"] == "2.8"


def test_metadata_to_text_empty_metadata_returns_empty_json() -> None:
    result = metadata_to_text({})

    assert "{}" in result


def test_metadata_to_text_special_characters_do_not_raise() -> None:
    metadata = {"Description": "Café & Co. — 100%"}
    result = metadata_to_text(metadata)

    assert "Café" in result
