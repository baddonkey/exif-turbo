from __future__ import annotations

from pathlib import Path

import pytest
import sqlcipher3

from exif_turbo.data.image_index_repository import ImageIndexRepository
from tests.conftest import make_jpeg


def _open_keyed(db_path: Path, key: str) -> ImageIndexRepository:
    return ImageIndexRepository(db_path, key=key)


def test_change_password_persists_data_under_new_key(tmp_path: Path) -> None:
    # Arrange — create a keyed DB with one row
    db_path = tmp_path / "test.db"
    repo = _open_keyed(db_path, "old-pw")
    path = str(make_jpeg(tmp_path / "photo.jpg"))
    repo.upsert_image(path, "photo.jpg", 1.0, 100, {}, "photo")
    repo.commit()

    # Act
    repo.change_password("new-pw")
    repo.close()

    # Assert — re-open with new password and the row is still there
    reopened = _open_keyed(db_path, "new-pw")
    try:
        assert reopened.count_images("") == 1
    finally:
        reopened.close()


def test_change_password_old_key_no_longer_opens(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    repo = _open_keyed(db_path, "old-pw")
    repo.change_password("new-pw")
    repo.close()

    # Act / Assert — opening with the old key fails (HMAC check on first page)
    with pytest.raises(sqlcipher3.DatabaseError):
        _open_keyed(db_path, "old-pw")


def test_change_password_empty_new_raises(tmp_path: Path) -> None:
    # Arrange
    repo = _open_keyed(tmp_path / "test.db", "old-pw")

    # Act / Assert
    try:
        with pytest.raises(ValueError):
            repo.change_password("")
    finally:
        repo.close()


def test_change_password_works_with_active_wal(tmp_path: Path) -> None:
    """Regression: SQLCipher silently no-ops PRAGMA rekey while in WAL mode.

    Build up real WAL activity (multiple writes + commits) so the journal is
    populated, then rekey.  Reopening with the new key must succeed.
    """
    # Arrange — create DB and push enough writes to populate the WAL file
    db_path = tmp_path / "wal.db"
    repo = _open_keyed(db_path, "old-pw")
    for i in range(50):
        path = str(make_jpeg(tmp_path / f"img_{i}.jpg"))
        repo.upsert_image(path, f"img_{i}.jpg", float(i), 100, {}, f"img_{i}")
        repo.commit()
    wal_path = db_path.with_name(db_path.name + "-wal")
    assert wal_path.exists(), "expected SQLCipher to have created a -wal file"

    # Act
    repo.change_password("new-pw")
    repo.close()

    # Assert — old password is rejected, new password reads back all rows
    with pytest.raises(sqlcipher3.DatabaseError):
        _open_keyed(db_path, "old-pw")
    reopened = _open_keyed(db_path, "new-pw")
    try:
        assert reopened.count_images("") == 50
    finally:
        reopened.close()
