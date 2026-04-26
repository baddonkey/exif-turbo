from __future__ import annotations

import binascii
import os
import time
from pathlib import Path
from typing import List

import sqlcipher3

from ..models.indexed_folder import IndexedFolder


class IndexedFolderRepository:
    def __init__(self, db_path: Path, key: str = "") -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlcipher3.connect(str(self.db_path))
        if key:
            hex_key = binascii.hexlify(key.encode("utf-8")).decode("ascii")
            self.conn.execute(f"PRAGMA key=\"x'{hex_key}'\"")
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA temp_store=MEMORY;")
        self.conn.execute("PRAGMA cache_size=-4000;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS indexed_folders (
                id              INTEGER PRIMARY KEY,
                path            TEXT UNIQUE NOT NULL,
                display_name    TEXT NOT NULL,
                enabled         INTEGER NOT NULL DEFAULT 1,
                recursive       INTEGER NOT NULL DEFAULT 1,
                status          TEXT NOT NULL DEFAULT 'new',
                image_count     INTEGER NOT NULL DEFAULT 0,
                last_scanned_at REAL,
                error_message   TEXT
            );
            """
        )

    # ── Mapping ───────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_folder(row: tuple) -> IndexedFolder:
        return IndexedFolder(
            id=row[0],
            path=row[1],
            display_name=row[2],
            enabled=bool(row[3]),
            recursive=bool(row[4]),
            status=row[5],
            image_count=row[6],
            last_scanned_at=row[7],
            error_message=row[8],
        )

    # ── Queries ───────────────────────────────────────────────────────────

    def get_all(self) -> List[IndexedFolder]:
        cur = self.conn.execute(
            "SELECT id, path, display_name, enabled, recursive, status, "
            "image_count, last_scanned_at, error_message "
            "FROM indexed_folders ORDER BY path"
        )
        return [self._row_to_folder(r) for r in cur.fetchall()]

    def get_by_id(self, folder_id: int) -> IndexedFolder | None:
        cur = self.conn.execute(
            "SELECT id, path, display_name, enabled, recursive, status, "
            "image_count, last_scanned_at, error_message "
            "FROM indexed_folders WHERE id = ?",
            (folder_id,),
        )
        row = cur.fetchone()
        return self._row_to_folder(row) if row else None

    def exists(self, path: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM indexed_folders WHERE path = ?",
            (os.path.normpath(path),),
        )
        return cur.fetchone() is not None

    def get_disabled_paths(self) -> List[str]:
        cur = self.conn.execute(
            "SELECT path FROM indexed_folders WHERE enabled = 0"
        )
        return [row[0] for row in cur.fetchall()]

    def get_enabled_folders(self) -> List[IndexedFolder]:
        cur = self.conn.execute(
            "SELECT id, path, display_name, enabled, recursive, status, "
            "image_count, last_scanned_at, error_message "
            "FROM indexed_folders WHERE enabled = 1 ORDER BY path"
        )
        return [self._row_to_folder(r) for r in cur.fetchall()]

    def get_pending_folders(self) -> List[IndexedFolder]:
        """Return enabled folders interrupted (scanning/queued) from a previous session."""
        cur = self.conn.execute(
            "SELECT id, path, display_name, enabled, recursive, status, "
            "image_count, last_scanned_at, error_message "
            "FROM indexed_folders "
            "WHERE status IN ('queued', 'scanning') AND enabled = 1 ORDER BY path"
        )
        return [self._row_to_folder(r) for r in cur.fetchall()]

    # ── Mutations ─────────────────────────────────────────────────────────

    def add(
        self,
        path: str,
        display_name: str = "",
        recursive: bool = True,
    ) -> IndexedFolder:
        normalised = os.path.normpath(path)
        name = display_name or Path(normalised).name
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO indexed_folders "
                "(path, display_name, enabled, recursive, status) "
                "VALUES (?, ?, 1, ?, 'new')",
                (normalised, name, int(recursive)),
            )
        cur = self.conn.execute(
            "SELECT id, path, display_name, enabled, recursive, status, "
            "image_count, last_scanned_at, error_message "
            "FROM indexed_folders WHERE path = ?",
            (normalised,),
        )
        return self._row_to_folder(cur.fetchone())

    def remove(self, folder_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM indexed_folders WHERE id = ?", (folder_id,)
            )

    def set_enabled(self, folder_id: int, enabled: bool) -> None:
        status = "disabled" if not enabled else "indexed"
        with self.conn:
            self.conn.execute(
                "UPDATE indexed_folders SET enabled = ?, status = ? WHERE id = ?",
                (int(enabled), status, folder_id),
            )

    def update_status(
        self,
        folder_id: int,
        status: str,
        image_count: int = 0,
        last_scanned_at: float | None = None,
        error_message: str | None = None,
    ) -> None:
        ts = last_scanned_at if last_scanned_at is not None else time.time()
        with self.conn:
            self.conn.execute(
                "UPDATE indexed_folders "
                "SET status = ?, image_count = ?, last_scanned_at = ?, error_message = ? "
                "WHERE id = ?",
                (status, image_count, ts, error_message, folder_id),
            )

    def close(self) -> None:
        self.conn.close()

    def clear_all(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM indexed_folders")
