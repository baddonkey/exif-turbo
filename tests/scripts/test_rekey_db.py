from __future__ import annotations

import binascii
from pathlib import Path

import sqlcipher3

from scripts.rekey_db import rekey


def test_rekey_db_migrates_legacy_raw_key_database(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "legacy.db"
    old_password = "o" * 32
    new_password = "new-passphrase-for-script-test"
    old_hex = binascii.hexlify(old_password.encode("utf-8")).decode("ascii")
    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key=\"x'{old_hex}'\"")
    conn.execute("CREATE TABLE migration_probe (value TEXT)")
    conn.execute("INSERT INTO migration_probe VALUES ('preserved')")
    conn.commit()
    conn.close()

    # Act
    rekey(db_path, old_password, new_password)

    # Assert
    conn = sqlcipher3.connect(str(db_path))
    conn.execute(f"PRAGMA key='{new_password}'")
    assert conn.execute("SELECT value FROM migration_probe").fetchone()[0] == "preserved"
    conn.close()
