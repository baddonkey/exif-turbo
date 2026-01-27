from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, List, Tuple


class ImageIndexRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA temp_store=MEMORY;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self.init_db()

    def init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                metadata_json TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS images_fts
            USING fts5(path, filename, metadata_text);
            """
        )

    def upsert_image(
        self,
        path: str,
        filename: str,
        mtime: float,
        size: int,
        metadata: dict,
        metadata_text: str,
    ) -> None:
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO images (path, filename, mtime, size, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename,
                mtime=excluded.mtime,
                size=excluded.size,
                metadata_json=excluded.metadata_json
            """,
            (path, filename, mtime, size, metadata_json),
        )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO images_fts (rowid, path, filename, metadata_text)
            VALUES ((SELECT id FROM images WHERE path = ?), ?, ?, ?)
            """,
            (path, path, filename, metadata_text),
        )

    def delete_missing(self, existing_paths: Iterable[str]) -> None:
        existing = set(existing_paths)
        cur = self.conn.execute("SELECT path FROM images")
        to_delete = [row[0] for row in cur.fetchall() if row[0] not in existing]
        for path in to_delete:
            self.conn.execute("DELETE FROM images WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM images_fts WHERE path = ?", (path,))

    def clear_all(self) -> None:
        self.conn.execute("DELETE FROM images_fts")
        self.conn.execute("DELETE FROM images")

    def search_images(self, query: str, limit: int, offset: int) -> List[Tuple[int, str, str, str]]:
        if query.strip():
            sql = (
                "SELECT images.id, images.path, images.filename, images.metadata_json "
                "FROM images_fts "
                "JOIN images ON images_fts.rowid = images.id "
                "WHERE images_fts MATCH ? "
                "ORDER BY bm25(images_fts) "
                "LIMIT ? OFFSET ?"
            )
            args = (query, limit, offset)
        else:
            sql = (
                "SELECT id, path, filename, metadata_json "
                "FROM images "
                "ORDER BY filename "
                "LIMIT ? OFFSET ?"
            )
            args = (limit, offset)

        cur = self.conn.execute(sql, args)
        return cur.fetchall()

    def count_images(self, query: str) -> int:
        if query.strip():
            cur = self.conn.execute(
                "SELECT COUNT(*) FROM images_fts WHERE images_fts MATCH ?",
                (query,),
            )
        else:
            cur = self.conn.execute("SELECT COUNT(*) FROM images")
        return int(cur.fetchone()[0])

    def all_images(self) -> List[Tuple[str, str, float, int, str]]:
        cur = self.conn.execute(
            "SELECT path, filename, mtime, size, metadata_json FROM images"
        )
        return cur.fetchall()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
