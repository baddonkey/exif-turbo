"""Read the AI index revision without loading the native extension."""
from __future__ import annotations

from pathlib import Path

import sqlcipher3

from ._connection import open_encrypted_connection
from .ai_vector_backend import AiVectorIndexError


class AiIndexRevision:
    """Read the durable AI index revision."""

    def __init__(self, db_path: Path, key: str) -> None:
        self._db_path = db_path
        self._key = key

    def state(self) -> tuple[str, int]:
        conn = open_encrypted_connection(self._db_path, self._key)
        try:
            return self.state_for_connection(conn)
        finally:
            conn.close()

    @staticmethod
    def state_for_connection(conn: sqlcipher3.Connection) -> tuple[str, int]:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ai_vector_backend'"
        ).fetchone()
        if exists is None:
            raise AiVectorIndexError("The AI index revision is missing")
        row = conn.execute(
            "SELECT active, revision FROM ai_vector_backend WHERE singleton = 1"
        ).fetchone()
        if (
            row is None or row[0] != "vec1"
            or not isinstance(row[1], int) or row[1] < 0
        ):
            raise AiVectorIndexError("The AI index revision is invalid")
        return ("vec1", row[1])
