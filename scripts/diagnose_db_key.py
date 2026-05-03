"""Probe the index DB with a password from the prompt and report which key
(if any) actually unlocks it.  Read-only — no rekey, no writes."""
from __future__ import annotations

import binascii
import getpass
from pathlib import Path

import sqlcipher3


def try_open(db_path: Path, password: str) -> tuple[bool, str]:
    conn = sqlcipher3.connect(str(db_path))
    try:
        hex_key = binascii.hexlify(password.encode("utf-8")).decode("ascii")
        conn.execute(f"PRAGMA key=\"x'{hex_key}'\"")
        # Force SQLCipher to actually read & decrypt page 1
        cur = conn.execute("SELECT count(*) FROM sqlite_master")
        n = cur.fetchone()[0]
        return True, f"OK — sqlite_master has {n} rows"
    except sqlcipher3.DatabaseError as exc:
        return False, f"REJECTED — {exc}"
    finally:
        conn.close()


def main() -> None:
    db = Path.home() / ".exif-turbo" / "data" / "index" / "index.db"
    print(f"DB: {db}")
    print(f"Size: {db.stat().st_size:,} bytes\n")
    while True:
        pw = getpass.getpass("Password to test (empty to quit): ")
        if not pw:
            return
        ok, msg = try_open(db, pw)
        marker = "✓" if ok else "✗"
        print(f"  {marker} {msg}\n")


if __name__ == "__main__":
    main()
