"""One-shot CLI to rekey the SQLCipher index DB.

Use this if a previous Change Password attempt left the database under the
old password while the thumb cache was already migrated to the new one.
This script ONLY touches the database file — it does not modify the thumb
cache.  Run it from the project venv:

    python scripts/rekey_db.py
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

import sqlcipher3

from exif_turbo.data._connection import open_encrypted_connection, rekey_connection
from exif_turbo.data.password_policy import validate_new_database_password


def rekey(db_path: Path, old_password: str, new_password: str) -> None:
    validate_new_database_password(new_password)
    conn = open_encrypted_connection(db_path, old_password)
    try:
        # Switch out of WAL so rekey is not silently no-op'd.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
        rekey_connection(conn, new_password)
        conn.commit()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    finally:
        conn.close()
    # Verify by reopening with the new password.
    conn = open_encrypted_connection(db_path, new_password)
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    finally:
        conn.close()


def main() -> None:
    db = Path.home() / ".exif-turbo" / "data" / "index" / "index.db"
    if not db.exists():
        raise SystemExit(f"Database not found: {db}")
    print(f"DB:   {db}")
    print(f"Size: {db.stat().st_size:,} bytes\n")
    old_pw = getpass.getpass("Current (old) password: ")
    new_pw = getpass.getpass("New password:           ")
    new_pw_confirm = getpass.getpass("Confirm new password:   ")
    if new_pw != new_pw_confirm:
        raise SystemExit("New password and confirmation do not match.")
    try:
        rekey(db, old_pw, new_pw)
    except (sqlcipher3.DatabaseError, ValueError) as exc:
        print(f"\nFAILED — SQLCipher rejected an operation: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print("\nDatabase successfully rekeyed. The new password now opens the DB.")


if __name__ == "__main__":
    main()
