from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.merge_wikidata_entities import (
    WikidataEntityMergeError,
    merge_wikidata_entities,
)


def test_merge_wikidata_entities_sorts_qids_and_is_deterministic(
    tmp_path: Path,
) -> None:
    # Arrange
    first_input = tmp_path / "first.jsonl"
    first_input.write_text(
        json.dumps({"id": "Q20", "labels": {"en": "twenty"}}) + "\n",
        encoding="utf-8",
    )
    second_input = tmp_path / "second.jsonl"
    second_input.write_text(
        json.dumps({"labels": {"en": "three"}, "id": "Q3"}) + "\n",
        encoding="utf-8",
    )
    first_output = tmp_path / "first-output.jsonl"
    second_output = tmp_path / "second-output.jsonl"

    # Act
    merge_wikidata_entities([first_input, second_input], first_output)
    merge_wikidata_entities([first_input, second_input], second_output)

    # Assert
    assert first_output.read_bytes() == second_output.read_bytes()
    entities = [
        json.loads(line)
        for line in first_output.read_text(encoding="utf-8").splitlines()
    ]
    assert [entity["id"] for entity in entities] == ["Q3", "Q20"]


def test_merge_wikidata_entities_duplicate_qid_raises(tmp_path: Path) -> None:
    # Arrange
    first_input = tmp_path / "first.jsonl"
    second_input = tmp_path / "second.jsonl"
    entity = json.dumps({"id": "Q3"}) + "\n"
    first_input.write_text(entity, encoding="utf-8")
    second_input.write_text(entity, encoding="utf-8")

    # Act / Assert
    with pytest.raises(WikidataEntityMergeError, match="duplicate entity ID: Q3"):
        merge_wikidata_entities(
            [first_input, second_input],
            tmp_path / "output.jsonl",
        )
