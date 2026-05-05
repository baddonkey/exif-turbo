"""Shared SQLCipher connection helper.

Centralises:
  * The SQLCipher ``PRAGMA key`` invocation.  SQLCipher does not accept
    bound parameters in pragma statements, so the key is hex-encoded and
    interpolated — but the hex string is asserted to contain only the
    characters ``[0-9a-f]`` before interpolation, which makes SQL injection
    through the key value impossible by construction.
  * The standard pragma tuning applied to every database connection.

Used by :class:`ImageIndexRepository` and :class:`IndexedFolderRepository`.
"""

from __future__ import annotations

import binascii
import re
from pathlib import Path
from typing import Iterable

import sqlcipher3

_HEX_RE = re.compile(r"\A[0-9a-f]+\Z")


def _hex_for_pragma(key: str) -> str:
    hex_key = binascii.hexlify(key.encode("utf-8")).decode("ascii")
    # ``binascii.hexlify`` only ever produces ``[0-9a-f]+``, but assert the
    # invariant explicitly so a future change cannot smuggle in a bare
    # quote / semicolon and break the SQL string we interpolate it into.
    if not _HEX_RE.fullmatch(hex_key):
        raise ValueError("hex_key contains characters outside [0-9a-f]")
    return hex_key


def open_encrypted_connection(
    db_path: Path,
    key: str,
    *,
    cache_size_kb: int = 32_000,
    extra_pragmas: Iterable[str] = (),
) -> sqlcipher3.Connection:
    """Open a SQLCipher connection with the project's standard pragma set.

    ``extra_pragmas`` may carry tuning statements that don't take untrusted
    input (e.g. ``PRAGMA mmap_size=268435456``).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlcipher3.connect(str(db_path))
    if key:
        hex_key = _hex_for_pragma(key)
        conn.execute(f"PRAGMA key=\"x'{hex_key}'\"")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute(f"PRAGMA cache_size=-{int(cache_size_kb)};")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    for pragma in extra_pragmas:
        conn.execute(pragma)
    return conn


def rekey_connection(conn: sqlcipher3.Connection, new_key: str) -> None:
    """Re-encrypt the database under *new_key* using ``PRAGMA rekey``.

    Caller is responsible for any journal-mode dance required around the
    rekey (SQLCipher silently no-ops ``PRAGMA rekey`` while in WAL mode).
    """
    if not new_key:
        raise ValueError("new_key must not be empty")
    new_hex = _hex_for_pragma(new_key)
    conn.execute(f"PRAGMA rekey=\"x'{new_hex}'\"")
