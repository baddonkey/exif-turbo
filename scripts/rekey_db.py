"""One-shot CLI to rekey the SQLCipher index DB.

Use this if a previous Change Password attempt left the database under the
old password while the thumb cache was already migrated to the new one.
This script ONLY touches the database file — it does not modify the thumb
cache.  Run it from the project venv:

    python scripts/rekey_db.py
"""
from __future__ import annotations

import binascii
import getpass
import sys
from pathlib import Path

import sqlcipher3


def rekey(db_path: Path, old_password: str, new_password: str) -> None:
    if not new_password:
        raise SystemExit("New password must not be empty.")
    conn = sqlcipher3.connect(str(db_path))
    try:
        old_hex = binascii.hexlify(old_password.encode("utf-8")).decode("ascii")
        new_hex = binascii.hexlify(new_password.encode("utf-8")).decode("ascii")
        conn.execute(f"PRAGMA key=\"x'{old_hex}'\"")
        # Verify old key actually opens the DB.
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        # Switch out of WAL so rekey is not silently no-op'd.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute(f"PRAGMA rekey=\"x'{new_hex}'\"")
        conn.commit()
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()
    # Verify by reopening with the new password.
    conn = sqlcipher3.connect(str(db_path))
    try:
        new_hex = binascii.hexlify(new_password.encode("utf-8")).decode("ascii")
        conn.execute(f"PRAGMA key=\"x'{new_hex}'\"")
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
    except sqlcipher3.DatabaseError as exc:
        print(f"\nFAILED — SQLCipher rejected an operation: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print("\nDatabase successfully rekeyed. The new password now opens the DB.")


if __name__ == "__main__":
    main()
