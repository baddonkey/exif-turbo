"""Shared SQLCipher connection helper.

Centralises:
    * The SQLCipher ``PRAGMA key`` invocation.  Passphrases use SQLCipher's
        passphrase/KDF syntax with SQL string escaping. Legacy 32- and 48-byte
        keys are opened using the historical raw-key syntax and immediately
        migrated to passphrase mode.
  * The standard pragma tuning applied to every database connection.

Used by :class:`ImageIndexRepository` and :class:`IndexedFolderRepository`.
"""

from __future__ import annotations

import binascii
import os
import re
from pathlib import Path
from typing import Iterable
from uuid import uuid4

import sqlcipher3
from .password_policy import validate_new_database_password

_HEX_RE = re.compile(r"\A[0-9a-f]+\Z")
_SQLITE_HEADER = b"SQLite format 3\x00"


def _hex_for_pragma(key: str) -> str:
    hex_key = binascii.hexlify(key.encode("utf-8")).decode("ascii")
    # ``binascii.hexlify`` only ever produces ``[0-9a-f]+``, but assert the
    # invariant explicitly so a future change cannot smuggle in a bare
    # quote / semicolon and break the SQL string we interpolate it into.
    if not _HEX_RE.fullmatch(hex_key):
        raise ValueError("hex_key contains characters outside [0-9a-f]")
    return hex_key


def _passphrase_for_pragma(key: str) -> str:
    return "'" + key.replace("'", "''") + "'"


def is_plaintext_database(db_path: Path) -> bool:
    try:
        with db_path.open("rb") as database_file:
            return database_file.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except FileNotFoundError:
        return False


def _remove_sqlite_sidecars(db_path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _migrate_plaintext_database(db_path: Path, key: str) -> None:
    validate_new_database_password(key)
    temp_path = db_path.with_name(f".{db_path.name}.{uuid4().hex}.encrypted")
    conn = sqlcipher3.connect(str(db_path))
    try:
        escaped_path = str(temp_path).replace("'", "''")
        conn.execute(
            f"ATTACH DATABASE '{escaped_path}' AS encrypted KEY "
            f"{_passphrase_for_pragma(key)}"
        )
        conn.execute("SELECT sqlcipher_export('encrypted')").fetchone()
        conn.execute("DETACH DATABASE encrypted")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    except BaseException:
        conn.close()
        temp_path.unlink(missing_ok=True)
        _remove_sqlite_sidecars(temp_path)
        raise
    conn.close()

    try:
        verify_conn = sqlcipher3.connect(str(temp_path))
        try:
            verify_conn.execute(f"PRAGMA key={_passphrase_for_pragma(key)}")
            integrity_result = verify_conn.execute(
                "PRAGMA integrity_check"
            ).fetchone()
            if integrity_result != ("ok",):
                raise RuntimeError("Plaintext database export failed integrity check")
            verify_conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            verify_conn.close()

        _remove_sqlite_sidecars(db_path)
        os.replace(temp_path, db_path)
    finally:
        temp_path.unlink(missing_ok=True)
        _remove_sqlite_sidecars(temp_path)


def open_encrypted_connection(
    db_path: Path,
    key: str | None,
    *,
    cache_size_kb: int = 32_000,
    extra_pragmas: Iterable[str] = (),
) -> sqlcipher3.Connection:
    """Open a SQLCipher connection with the project's standard pragma set.

    ``extra_pragmas`` may carry tuning statements that don't take untrusted
    input (e.g. ``PRAGMA mmap_size=268435456``).

    Pass ``key=""`` explicitly only when opening a known plaintext database.
    """
    if key is None:
        raise ValueError("key must not be None; pass an explicit key")
    if key and (not db_path.exists() or db_path.stat().st_size == 0):
        validate_new_database_password(key)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if key and is_plaintext_database(db_path):
        _migrate_plaintext_database(db_path, key)
    conn = sqlcipher3.connect(str(db_path))
    try:
        if key:
            conn.execute(f"PRAGMA key={_passphrase_for_pragma(key)}")
            try:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            except sqlcipher3.DatabaseError:
                conn.close()
                conn = sqlcipher3.connect(str(db_path))
                legacy_hex_key = _hex_for_pragma(key)
                conn.execute(f"PRAGMA key=\"x'{legacy_hex_key}'\"")
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA journal_mode=DELETE")
                rekey_connection(conn, key)
                conn.commit()
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute(f"PRAGMA cache_size=-{int(cache_size_kb)};")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        for pragma in extra_pragmas:
            conn.execute(pragma)
    except BaseException:
        conn.close()
        raise
    return conn


def rekey_connection(conn: sqlcipher3.Connection, new_key: str) -> None:
    """Re-encrypt the database under *new_key* using ``PRAGMA rekey``.

    Caller is responsible for any journal-mode dance required around the
    rekey (SQLCipher silently no-ops ``PRAGMA rekey`` while in WAL mode).
    """
    if not new_key:
        raise ValueError("new_key must not be empty")
    conn.execute(f"PRAGMA rekey={_passphrase_for_pragma(new_key)}")
