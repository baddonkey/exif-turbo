from __future__ import annotations

from pathlib import Path

import pytest
import sqlcipher3

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.hybrid_search_state import HybridSearchState


def test_hybrid_search_state_persists_without_changing_existing_set_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    repo = ImageIndexRepository(db_path, key="")
    original_filter = {"op": "and", "conditions": [
        {"field": "file_type", "operator": "equals", "value": "jpg"}
    ]}
    set_id = repo.create_image_set("Wildlife", original_filter)
    state = HybridSearchState(
        'tags:="wildlife" ai:="deer"', "fine", "filename_desc",
        ("photos",), "jpg", 1, 2, True, None,
    )
    repo.set_image_set_search_state(set_id, state)
    repo.close()

    reopened = ImageIndexRepository(db_path, key="")
    assert reopened.get_image_set_search_state(set_id) == state
    saved_set = reopened.list_image_sets()[0]
    assert saved_set["apply_filter"] == original_filter
    assert saved_set["apply_filter_version"] == 1
    reopened.close()


def test_hybrid_search_state_migrates_existing_image_set_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    connection = sqlcipher3.connect(str(db_path))
    connection.execute(
        "CREATE TABLE image_sets (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "normalized_name TEXT NOT NULL UNIQUE, apply_filter_json TEXT, "
        "apply_filter_version INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    connection.execute(
        "INSERT INTO image_sets (name, normalized_name) VALUES ('Old set', 'old set')"
    )
    connection.commit()
    connection.close()

    repo = ImageIndexRepository(db_path, key="")

    assert repo.list_image_sets()[0]["name"] == "Old set"
    assert repo.list_image_sets()[0]["saved_search"] is None
    repo.close()


def test_hybrid_search_state_rejects_unknown_version_and_invalid_precision() -> None:
    valid = HybridSearchState("", "normal", "", (), "", None, None, False, None).to_dict()

    with pytest.raises(ValueError, match="version"):
        HybridSearchState.from_dict({**valid, "version": 2})
    with pytest.raises(ValueError, match="precision"):
        HybridSearchState.from_dict({**valid, "precision": "unknown"})
