from __future__ import annotations

from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """A database file holding two indexed images."""
    db_path = tmp_path / "index.db"
    repo = ImageIndexRepository(db_path, key="")
    repo.upsert_image("/a.jpg", "a.jpg", 1.0, 10, {"Make": "Canon"}, "Canon")
    repo.upsert_image("/b.jpg", "b.jpg", 2.0, 20, {"Make": "Nikon"}, "Nikon")
    repo.commit()
    repo.close()
    return db_path


def test_clear_all_rows_removes_every_image(populated_db: Path) -> None:
    # Arrange
    repo = ImageIndexRepository(populated_db, key="")

    # Act
    repo.clear_all_rows()

    # Assert
    count = repo.conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    repo.close()
    assert count == 0


def test_clear_all_rows_purges_fts_shadow_index(populated_db: Path) -> None:
    # Arrange
    repo = ImageIndexRepository(populated_db, key="")

    # Act
    repo.clear_all_rows()

    # Assert — the FTS table is queryable and empty after the DROP+recreate
    matches = repo.conn.execute(
        "SELECT COUNT(*) FROM images_fts WHERE images_fts MATCH ?", ("Canon",)
    ).fetchone()[0]
    repo.close()
    assert matches == 0


def test_vacuum_runs_without_open_transaction(populated_db: Path) -> None:
    # Arrange
    repo = ImageIndexRepository(populated_db, key="")
    repo.clear_all_rows()

    # Act / Assert — VACUUM must not raise when run after the row deletes
    repo.vacuum()
    repo.close()


def test_clear_all_still_empties_database(populated_db: Path) -> None:
    # Arrange
    repo = ImageIndexRepository(populated_db, key="")

    # Act
    repo.clear_all()

    # Assert
    count = repo.conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    repo.close()
    assert count == 0
