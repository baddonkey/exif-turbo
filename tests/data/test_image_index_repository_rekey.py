from __future__ import annotations

import binascii
from pathlib import Path

import pytest
import sqlcipher3

from exif_turbo.data.image_index_repository import ImageIndexRepository
from tests.conftest import make_jpeg

_OLD_PASSWORD = "old-passphrase-for-test"
_NEW_PASSWORD = "new-passphrase-for-test"


def _open_keyed(db_path: Path, key: str) -> ImageIndexRepository:
    return ImageIndexRepository(db_path, key=key)


def test_repository_missing_key_fails_closed(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "test.db"

    # Act / Assert
    with pytest.raises(ValueError, match="key must not be None"):
        ImageIndexRepository(db_path)


@pytest.mark.parametrize("byte_length", [32, 48])
def test_legacy_raw_key_database_migrates_to_passphrase_mode(
    tmp_path: Path, byte_length: int
) -> None:
    # Arrange — build a DB using the historical x'…' key syntax.
    db_path = tmp_path / "legacy.db"
    password = "p" * byte_length
    legacy_hex = binascii.hexlify(password.encode("utf-8")).decode("ascii")
    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key=\"x'{legacy_hex}'\"")
    conn.execute("CREATE TABLE migration_probe (value TEXT)")
    conn.execute("INSERT INTO migration_probe VALUES ('preserved')")
    conn.commit()
    conn.close()

    # Act — opening with the password migrates the legacy DB in place.
    repo = ImageIndexRepository(db_path, key=password)
    value = repo.conn.execute(
        "SELECT value FROM migration_probe"
    ).fetchone()[0]
    repo.close()

    # Assert — data is intact and the canonical passphrase opens the DB.
    assert value == "preserved"
    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key='{password}'")
    assert conn.execute("SELECT value FROM migration_probe").fetchone()[0] == "preserved"
    conn.close()

    # The old raw-key interpretation no longer opens the migrated database.
    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key=\"x'{legacy_hex}'\"")
    with pytest.raises(sqlcipher3.DatabaseError):
        conn.execute("SELECT value FROM migration_probe").fetchone()
    conn.close()


def test_legacy_ordinary_key_database_migrates_to_passphrase_mode(
    tmp_path: Path,
) -> None:
    # Arrange — ordinary historical passwords also used x'…' syntax.
    db_path = tmp_path / "legacy-ordinary.db"
    password = "ordinary-passphrase"
    legacy_hex = binascii.hexlify(password.encode("utf-8")).decode("ascii")
    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key=\"x'{legacy_hex}'\"")
    conn.execute("CREATE TABLE migration_probe (value TEXT)")
    conn.execute("INSERT INTO migration_probe VALUES ('preserved')")
    conn.commit()
    conn.close()

    # Act
    repo = ImageIndexRepository(db_path, key=password)
    value = repo.conn.execute(
        "SELECT value FROM migration_probe"
    ).fetchone()[0]
    repo.close()

    # Assert
    assert value == "preserved"
    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key='{password}'")
    assert conn.execute("SELECT value FROM migration_probe").fetchone()[0] == "preserved"
    conn.close()


def test_plaintext_database_migrates_to_encrypted_database(tmp_path: Path) -> None:
    # Arrange — simulate a DB created by the old empty-password path.
    db_path = tmp_path / "plaintext.db"
    legacy_repo = ImageIndexRepository(db_path, key="")
    image_path = str(make_jpeg(tmp_path / "legacy-photo.jpg"))
    legacy_repo.upsert_image(
        image_path,
        "legacy-photo.jpg",
        1.0,
        100,
        {"Make": "Preserved"},
        "legacy migration keyword",
    )
    legacy_repo.conn.execute("CREATE TABLE migration_probe (value TEXT)")
    legacy_repo.conn.execute("INSERT INTO migration_probe VALUES ('preserved')")
    legacy_repo.commit()
    legacy_repo.close()
    assert db_path.read_bytes().startswith(b"SQLite format 3\x00")

    # Act — opening with a new passphrase migrates the DB in place.
    repo = ImageIndexRepository(db_path, key=_NEW_PASSWORD)
    value = repo.conn.execute(
        "SELECT value FROM migration_probe"
    ).fetchone()[0]
    rows = repo.search_images("migration keyword", limit=10, offset=0)
    image_count = repo.count_images("")
    repo.close()

    # Assert — data survived, the header is encrypted, and unkeyed reads fail.
    assert value == "preserved"
    assert image_count == 1
    assert rows[0][1] == image_path
    assert not db_path.read_bytes().startswith(b"SQLite format 3\x00")
    conn = sqlcipher3.connect(str(db_path))
    with pytest.raises(sqlcipher3.DatabaseError):
        conn.execute("SELECT value FROM migration_probe").fetchone()
    conn.close()

    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key='{_NEW_PASSWORD}'")
    assert conn.execute("SELECT value FROM migration_probe").fetchone()[0] == "preserved"
    conn.close()


@pytest.mark.parametrize("byte_length", [32, 48])
def test_new_database_boundary_length_uses_passphrase_kdf(
    tmp_path: Path, byte_length: int
) -> None:
    # Arrange
    db_path = tmp_path / "new.db"
    password = "p" * byte_length

    # Act
    repo = ImageIndexRepository(db_path, key=password)
    repo.close()

    # Assert — the standard passphrase form succeeds, raw-key form does not.
    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key='{password}'")
    assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone() is not None
    conn.close()

    conn = sqlcipher3.connect(str(db_path))
    legacy_hex = binascii.hexlify(password.encode("utf-8")).decode("ascii")
    conn.execute(f"PRAGMA key=\"x'{legacy_hex}'\"")
    with pytest.raises(sqlcipher3.DatabaseError):
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    conn.close()


def test_passphrase_with_sql_punctuation_roundtrips(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "quoted.db"
    password = "long ' quoted; passphrase"

    # Act
    repo = ImageIndexRepository(db_path, key=password)
    repo.close()
    reopened = ImageIndexRepository(db_path, key=password)

    # Assert
    assert reopened.count_images("") == 0
    reopened.close()


def test_change_password_persists_data_under_new_key(tmp_path: Path) -> None:
    # Arrange — create a keyed DB with one row
    db_path = tmp_path / "test.db"
    repo = _open_keyed(db_path, _OLD_PASSWORD)
    path = str(make_jpeg(tmp_path / "photo.jpg"))
    repo.upsert_image(path, "photo.jpg", 1.0, 100, {}, "photo")
    repo.commit()

    # Act
    repo.change_password(_NEW_PASSWORD)
    repo.close()

    # Assert — re-open with new password and the row is still there
    reopened = _open_keyed(db_path, _NEW_PASSWORD)
    try:
        assert reopened.count_images("") == 1
    finally:
        reopened.close()


def test_change_password_old_key_no_longer_opens(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    repo = _open_keyed(db_path, _OLD_PASSWORD)
    repo.change_password(_NEW_PASSWORD)
    repo.close()

    # Act / Assert — opening with the old key fails (HMAC check on first page)
    with pytest.raises(sqlcipher3.DatabaseError):
        _open_keyed(db_path, _OLD_PASSWORD)


def test_change_password_empty_new_raises(tmp_path: Path) -> None:
    # Arrange
    repo = _open_keyed(tmp_path / "test.db", _OLD_PASSWORD)

    # Act / Assert
    try:
        with pytest.raises(ValueError):
            repo.change_password("")
    finally:
        repo.close()


def test_change_password_short_new_raises(tmp_path: Path) -> None:
    # Arrange
    repo = _open_keyed(tmp_path / "test.db", _OLD_PASSWORD)

    # Act / Assert
    try:
        with pytest.raises(ValueError, match="at least 12 characters"):
            repo.change_password("short")
    finally:
        repo.close()


def test_new_database_short_password_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 12 characters"):
        ImageIndexRepository(tmp_path / "test.db", key="short")


def test_empty_database_file_still_requires_strong_password(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "empty.db"
    db_path.touch()

    # Act / Assert
    with pytest.raises(ValueError, match="at least 12 characters"):
        ImageIndexRepository(db_path, key="short")


def test_change_password_works_with_active_wal(tmp_path: Path) -> None:
    """Regression: SQLCipher silently no-ops PRAGMA rekey while in WAL mode.

    Build up real WAL activity (multiple writes + commits) so the journal is
    populated, then rekey.  Reopening with the new key must succeed.
    """
    # Arrange — create DB and push enough writes to populate the WAL file
    db_path = tmp_path / "wal.db"
    repo = _open_keyed(db_path, _OLD_PASSWORD)
    for i in range(50):
        path = str(make_jpeg(tmp_path / f"img_{i}.jpg"))
        repo.upsert_image(path, f"img_{i}.jpg", float(i), 100, {}, f"img_{i}")
        repo.commit()
    wal_path = db_path.with_name(db_path.name + "-wal")
    assert wal_path.exists(), "expected SQLCipher to have created a -wal file"

    # Act
    repo.change_password(_NEW_PASSWORD)
    repo.close()

    # Assert — old password is rejected, new password reads back all rows
    with pytest.raises(sqlcipher3.DatabaseError):
        _open_keyed(db_path, _OLD_PASSWORD)
    reopened = _open_keyed(db_path, _NEW_PASSWORD)
    try:
        assert reopened.count_images("") == 50
    finally:
        reopened.close()
