from __future__ import annotations

import binascii
import json
import os
from os.path import commonpath
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import sqlcipher3


class ImageIndexRepository:
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
        with self.conn:
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
        # Load the keep-set into a temporary table so the DELETE can be a
        # single set-difference operation instead of O(N) individual statements.
        with self.conn:
            self.conn.execute(
                "CREATE TEMPORARY TABLE IF NOT EXISTS _keep_paths (path TEXT PRIMARY KEY)"
            )
            self.conn.execute("DELETE FROM _keep_paths")
            self.conn.executemany(
                "INSERT OR IGNORE INTO _keep_paths (path) VALUES (?)",
                ((p,) for p in existing_paths),
            )
            self.conn.execute(
                "DELETE FROM images_fts WHERE path IN "
                "(SELECT path FROM images WHERE path NOT IN (SELECT path FROM _keep_paths))"
            )
            self.conn.execute(
                "DELETE FROM images WHERE path NOT IN (SELECT path FROM _keep_paths)"
            )
            self.conn.execute("DROP TABLE IF EXISTS _keep_paths")

    def clear_all(self) -> None:
        self.conn.execute("DELETE FROM images_fts")
        self.conn.execute("DELETE FROM images")

    _SORT_MAP: Dict[str, str] = {
        "filename_asc":  "images.filename COLLATE NOCASE ASC",
        "filename_desc": "images.filename COLLATE NOCASE DESC",
        "path_asc":      "images.path COLLATE NOCASE ASC",
        "path_desc":     "images.path COLLATE NOCASE DESC",
        "date_desc":     "images.mtime DESC",
        "date_asc":      "images.mtime ASC",
        "size_desc":     "images.size DESC",
    }

    def search_images(
        self,
        query: str,
        limit: int,
        offset: int,
        sort_by: str = "",
        ext_filter: str = "",
        path_filter: str = "",
        excluded_paths: List[str] | None = None,
    ) -> List[Tuple[int, str, str, str, int, float]]:
        order = self._SORT_MAP.get(sort_by, "images.filename COLLATE NOCASE ASC")
        ext_clause = ""
        ext_args: tuple = ()
        if ext_filter:
            canonical = ext_filter.lower().lstrip(".")
            # Collect all extensions that map to this canonical key
            aliases = [
                raw for raw, mapped in self._EXT_ALIASES.items() if mapped == canonical
            ]
            exts = [canonical] + aliases  # e.g. ["jpg", "jpeg"]
            placeholders = " OR ".join("LOWER(images.filename) LIKE ?" for _ in exts)
            ext_clause = f"AND ({placeholders})"
            ext_args = tuple(f"%.{e}" for e in exts)

        path_clause = ""
        path_args: tuple = ()
        if path_filter:
            prefix = os.path.normpath(path_filter) + os.sep
            path_clause = "AND images.path LIKE ?"
            path_args = (prefix + "%",)

        exclude_clause = ""
        exclude_args: tuple = ()
        if excluded_paths:
            parts = " AND ".join("images.path NOT LIKE ?" for _ in excluded_paths)
            exclude_clause = f"AND ({parts})"
            exclude_args = tuple(
                os.path.normpath(p) + os.sep + "%" for p in excluded_paths
            )

        if query.strip():
            # When user picks an explicit sort keep it; otherwise use relevance.
            order_expr = f"ORDER BY {order}" if sort_by else "ORDER BY bm25(images_fts)"
            sql = (
                "SELECT images.id, images.path, images.filename, images.metadata_json, images.size, images.mtime "
                "FROM images_fts "
                "JOIN images ON images_fts.rowid = images.id "
                f"WHERE images_fts MATCH ? {ext_clause} {path_clause} {exclude_clause} "
                f"{order_expr} "
                "LIMIT ? OFFSET ?"
            )
            args = (query,) + ext_args + path_args + exclude_args + (limit, offset)
        else:
            sql = (
                "SELECT id, path, filename, metadata_json, size, mtime "
                "FROM images "
                f"WHERE 1=1 {ext_clause} {path_clause} {exclude_clause} "
                f"ORDER BY {order} "
                "LIMIT ? OFFSET ?"
            )
            args = ext_args + path_args + exclude_args + (limit, offset)

        cur = self.conn.execute(sql, args)
        return cur.fetchall()

    def count_images(
        self,
        query: str,
        ext_filter: str = "",
        path_filter: str = "",
        excluded_paths: List[str] | None = None,
    ) -> int:
        ext_clause = ""
        ext_args: tuple = ()
        if ext_filter:
            canonical = ext_filter.lower().lstrip(".")
            aliases = [
                raw for raw, mapped in self._EXT_ALIASES.items() if mapped == canonical
            ]
            exts = [canonical] + aliases
            placeholders = " OR ".join("LOWER(images.filename) LIKE ?" for _ in exts)
            ext_clause = f"AND ({placeholders})"
            ext_args = tuple(f"%.{e}" for e in exts)

        path_clause = ""
        path_args: tuple = ()
        if path_filter:
            prefix = os.path.normpath(path_filter) + os.sep
            path_clause = "AND images.path LIKE ?"
            path_args = (prefix + "%",)

        exclude_clause = ""
        exclude_args: tuple = ()
        if excluded_paths:
            parts = " AND ".join("images.path NOT LIKE ?" for _ in excluded_paths)
            exclude_clause = f"AND ({parts})"
            exclude_args = tuple(
                os.path.normpath(p) + os.sep + "%" for p in excluded_paths
            )

        if query.strip():
            sql = (
                "SELECT COUNT(*) FROM images_fts "
                "JOIN images ON images_fts.rowid = images.id "
                f"WHERE images_fts MATCH ? {ext_clause} {path_clause} {exclude_clause}"
            )
            args = (query,) + ext_args + path_args + exclude_args
        else:
            sql = (
                f"SELECT COUNT(*) FROM images "
                f"WHERE 1=1 {ext_clause} {path_clause} {exclude_clause}"
            )
            args = ext_args + path_args + exclude_args

        cur = self.conn.execute(sql, args)
        return int(cur.fetchone()[0])

    # Extensions that should be merged into a single facet key.
    _EXT_ALIASES: Dict[str, str] = {"jpeg": "jpg"}

    def get_format_counts(
        self,
        query: str = "",
        path_filter: str = "",
        excluded_paths: List[str] | None = None,
    ) -> List[Tuple[str, int]]:
        """Return [(extension, count)] sorted by count descending.

        Aliased extensions (e.g. jpeg → jpg) are merged into one bucket.
        When *query* or *path_filter* are given, counts are scoped to the
        current search context (but never filtered by ext — that would be
        meaningless for a facet).
        """
        path_clause = ""
        path_args: tuple = ()
        if path_filter:
            prefix = os.path.normpath(path_filter) + os.sep
            path_clause = "AND images.path LIKE ?"
            path_args = (prefix + "%",)

        exclude_clause = ""
        exclude_args: tuple = ()
        if excluded_paths:
            parts = " AND ".join("images.path NOT LIKE ?" for _ in excluded_paths)
            exclude_clause = f"AND ({parts})"
            exclude_args = tuple(
                os.path.normpath(p) + os.sep + "%" for p in excluded_paths
            )

        if query.strip():
            sql = (
                "SELECT LOWER(SUBSTR(images.filename, INSTR(images.filename, '.') + 1)) AS ext,"
                " COUNT(*) AS cnt"
                " FROM images_fts"
                " JOIN images ON images_fts.rowid = images.id"
                f" WHERE images_fts MATCH ? AND images.filename LIKE '%.%'"
                f" {path_clause} {exclude_clause}"
                " GROUP BY ext"
            )
            args = (query,) + path_args + exclude_args
        else:
            sql = (
                "SELECT LOWER(SUBSTR(filename, INSTR(filename, '.') + 1)) AS ext,"
                " COUNT(*) AS cnt"
                " FROM images"
                f" WHERE filename LIKE '%.%' {path_clause} {exclude_clause}"
                " GROUP BY ext"
            )
            args = path_args + exclude_args

        cur = self.conn.execute(sql, args)
        counts: Dict[str, int] = {}
        for ext, cnt in cur.fetchall():
            ext = self._EXT_ALIASES.get(ext, ext)
            if ext:
                counts[ext] = counts.get(ext, 0) + cnt
        return sorted(counts.items(), key=lambda x: -x[1])

    def get_folder_tree(self) -> List[Dict[str, Any]]:
        """Return folder nodes for the tree browser, sorted by path.

        Each node: {"path": str, "name": str, "depth": int, "count": int}
        where count is the number of images directly inside that folder.
        Depth is relative to the deepest common ancestor of all indexed folders.
        """
        # Aggregate in SQL: derive parent dir from path/filename to avoid fetching
        # all image rows into Python (can be 20 K+).
        cur = self.conn.execute(
            "SELECT substr(path, 1, length(path) - length(filename) - 1) AS folder,"
            " COUNT(*) AS cnt"
            " FROM images"
            " GROUP BY folder"
        )
        folder_counts: Dict[str, int] = {row[0]: row[1] for row in cur.fetchall()}
        unique_parents: set[str] = set(folder_counts.keys())

        if not unique_parents:
            return []

        # Find deepest common ancestor of all parent folders
        try:
            common: str = commonpath(list(unique_parents))
        except ValueError:
            common = ""  # different drives on Windows

        # Build full folder set: each parent + its ancestors down to common
        all_folders: set[str] = set()
        for fp in unique_parents:
            p = Path(fp)
            while True:
                s = str(p)
                all_folders.add(s)
                if (common and s == common) or p.parent == p:
                    break
                p = p.parent
        if common:
            all_folders.add(common)

        # Depth relative to common (or minimum depth when drives differ)
        if common:
            base_depth = len(Path(common).parts)
        else:
            base_depth = min(len(Path(f).parts) for f in all_folders)

        nodes: List[Dict[str, Any]] = []
        for folder in sorted(all_folders):
            p = Path(folder)
            depth = len(p.parts) - base_depth
            name = p.name or str(p)  # drive roots have empty .name on Windows
            count = folder_counts.get(folder, 0)
            nodes.append({"path": folder, "name": name, "depth": depth, "count": count})

        return nodes

    def delete_by_path_prefix(self, folder_path: str) -> None:
        """Remove all images whose path starts with folder_path."""
        prefix = os.path.normpath(folder_path) + os.sep + "%"
        with self.conn:
            self.conn.execute(
                "DELETE FROM images_fts WHERE path IN "
                "(SELECT path FROM images WHERE path LIKE ?)",
                (prefix,),
            )
            self.conn.execute(
                "DELETE FROM images WHERE path LIKE ?", (prefix,)
            )

    def all_images(self) -> List[Tuple[str, str, float, int, str]]:
        cur = self.conn.execute(
            "SELECT path, filename, mtime, size, metadata_json FROM images"
        )
        return cur.fetchall()

    def get_all_stamps(self) -> dict[str, tuple[float, int]]:
        """Return {path: (mtime, size)} for every indexed image.

        Fetches in 2 000-row batches so the GIL is released between chunks,
        keeping the GUI event loop responsive on large collections.
        """
        result: dict[str, tuple[float, int]] = {}
        cur = self.conn.execute("SELECT path, mtime, size FROM images")
        while True:
            rows = cur.fetchmany(2000)
            if not rows:
                break
            for row in rows:
                result[row[0]] = (row[1], row[2])
        return result

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
