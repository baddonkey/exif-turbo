from __future__ import annotations

import json
import os
from os.path import commonpath
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import sqlcipher3

from ._connection import open_encrypted_connection, rekey_connection

# Width/height key-pairs tried in priority order (exiftool -g1 format).
_DIM_KEY_PAIRS: tuple[tuple[str, str], ...] = (
    ("File:ImageWidth", "File:ImageHeight"),
    ("ExifIFD:ExifImageWidth", "ExifIFD:ExifImageHeight"),
    ("IFD0:ImageWidth", "IFD0:ImageHeight"),
    ("PNG:ImageWidth", "PNG:ImageHeight"),
)


def _pixel_count_from_meta(meta_json: str) -> int:
    """Parse width * height from stored exiftool JSON metadata.

    Returns 0 when no recognised dimension keys are found.
    """
    try:
        meta = json.loads(meta_json)
        for w_key, h_key in _DIM_KEY_PAIRS:
            w = meta.get(w_key)
            h = meta.get(h_key)
            if w and h:
                return int(float(w)) * int(float(h))
    except Exception:  # noqa: BLE001
        pass
    return 0


class ImageIndexRepository:
    def __init__(self, db_path: Path, key: str = "") -> None:
        self.db_path = db_path
        self.conn = open_encrypted_connection(
            db_path,
            key,
            cache_size_kb=32_000,
            extra_pragmas=("PRAGMA mmap_size=268435456;",),
        )
        self.init_db()

    def change_password(self, new_password: str) -> None:
        """Re-encrypt the SQLCipher database under *new_password*.

        The repository must already be unlocked (i.e. opened with the
        correct current key in :py:meth:`__init__`).  Raises
        :class:`sqlcipher3.DatabaseError` if SQLCipher refuses the rekey.

        SQLCipher silently no-ops ``PRAGMA rekey`` while the database is in
        WAL journal mode, so we checkpoint, switch to DELETE, rekey, and
        switch back to WAL.  We also verify the new key is in effect by
        running a query under it before returning.
        """
        if not new_password:
            raise ValueError("new_password must not be empty")
        # Drain & remove the WAL so rekey can rewrite every page.
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.execute("PRAGMA journal_mode=DELETE")
        rekey_connection(self.conn, new_password)
        self.conn.commit()
        # Restore WAL for normal operation on the now-rekeyed database.
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Sanity check: a query must succeed under the new key.  If the rekey
        # silently failed this will raise sqlcipher3.DatabaseError.
        self.conn.execute("SELECT count(*) FROM sqlite_master").fetchone()

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

            CREATE INDEX IF NOT EXISTS idx_images_filename  ON images(filename COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_images_path_nocase ON images(path COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_images_mtime      ON images(mtime DESC);
            CREATE INDEX IF NOT EXISTS idx_images_size       ON images(size DESC);

            CREATE TABLE IF NOT EXISTS image_folders (
                image_id  INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                folder_id INTEGER NOT NULL,
                PRIMARY KEY (image_id, folder_id)
            );

            CREATE INDEX IF NOT EXISTS idx_image_folders_folder ON image_folders(folder_id);
            """
        )
        # Add marked column for existing databases (one-time migration).
        existing_cols = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(images)").fetchall()
        }
        if "marked" not in existing_cols:
            self.conn.execute(
                "ALTER TABLE images ADD COLUMN marked INTEGER NOT NULL DEFAULT 0"
            )
            self.conn.commit()
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_marked ON images(marked)"
        )
        if "captured_at" not in existing_cols:
            self.conn.execute(
                "ALTER TABLE images ADD COLUMN captured_at INTEGER"
            )
            self.conn.commit()
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_captured_at ON images(captured_at)"
        )
        self.conn.commit()
        # Backfill image_folders for images indexed before this join table was
        # introduced (one-time migration, idempotent via INSERT OR IGNORE).
        cur = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='indexed_folders'"
        )
        if cur.fetchone():
            self.conn.execute(
                "INSERT OR IGNORE INTO image_folders (image_id, folder_id) "
                "SELECT i.id, f.id FROM images i, indexed_folders f "
                "WHERE i.path LIKE (f.path || ? || '%')",
                (os.sep,),
            )
            self.conn.commit()

    def upsert_image(
        self,
        path: str,
        filename: str,
        mtime: float,
        size: int,
        metadata: dict,
        metadata_text: str,
        *,
        folder_id: int | None = None,
        captured_at: float | None = None,
    ) -> None:
        self.upsert_images_batch([(path, filename, mtime, size, metadata, metadata_text, folder_id, captured_at)])

    def upsert_images_batch(
        self,
        items: list[tuple[str, str, float, int, dict, str, int | None, float | None]],
    ) -> None:
        """Write multiple images in a single transaction for bulk-insert efficiency."""
        if not items:
            return
        with self.conn:
            for path, filename, mtime, size, metadata, metadata_text, folder_id, captured_at in items:
                metadata_json = json.dumps(metadata, ensure_ascii=False)
                self.conn.execute(
                    """
                    INSERT INTO images (path, filename, mtime, size, metadata_json, captured_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        filename=excluded.filename,
                        mtime=excluded.mtime,
                        size=excluded.size,
                        metadata_json=excluded.metadata_json,
                        captured_at=excluded.captured_at
                    """,
                    (path, filename, mtime, size, metadata_json, captured_at),
                )
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO images_fts (rowid, path, filename, metadata_text)
                    VALUES ((SELECT id FROM images WHERE path = ?), ?, ?, ?)
                    """,
                    (path, path, filename, metadata_text),
                )
                if folder_id is not None:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO image_folders (image_id, folder_id) "
                        "VALUES ((SELECT id FROM images WHERE path = ?), ?)",
                        (path, folder_id),
                    )

    def delete_missing(
        self,
        existing_paths: Iterable[str],
        folder_roots: List[str] | None = None,
        folder_id: int | None = None,
    ) -> None:
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
            if folder_id is not None:
                # n:m model: remove this folder's associations for images that
                # were not found during the scan, then delete images that have
                # no remaining folder associations (orphans) scoped to this
                # folder's path so images from other scopes are not touched.
                self.conn.execute(
                    "DELETE FROM image_folders "
                    "WHERE folder_id = ? "
                    "AND image_id IN ("
                    "  SELECT id FROM images "
                    "  WHERE path NOT IN (SELECT path FROM _keep_paths)"
                    ")",
                    (folder_id,),
                )
                if folder_roots:
                    prefixes = [
                        r if r.endswith(os.sep) else r + os.sep
                        for r in folder_roots
                    ]
                    self.conn.execute(
                        "CREATE TEMPORARY TABLE IF NOT EXISTS _scan_roots"
                        " (prefix TEXT PRIMARY KEY)"
                    )
                    self.conn.execute("DELETE FROM _scan_roots")
                    self.conn.executemany(
                        "INSERT OR IGNORE INTO _scan_roots (prefix) VALUES (?)",
                        ((p,) for p in prefixes),
                    )
                    self.conn.execute(
                        "DELETE FROM images_fts WHERE path IN ("
                        "  SELECT i.path FROM images i"
                        "  WHERE i.path NOT IN (SELECT path FROM _keep_paths)"
                        "  AND i.id NOT IN (SELECT image_id FROM image_folders)"
                        "  AND EXISTS"
                        "    (SELECT 1 FROM _scan_roots WHERE i.path LIKE prefix || '%')"
                        ")"
                    )
                    self.conn.execute(
                        "DELETE FROM images"
                        " WHERE path NOT IN (SELECT path FROM _keep_paths)"
                        " AND id NOT IN (SELECT image_id FROM image_folders)"
                        " AND EXISTS"
                        "   (SELECT 1 FROM _scan_roots WHERE images.path LIKE prefix || '%')"
                    )
                    self.conn.execute("DROP TABLE IF EXISTS _scan_roots")
            elif folder_roots:
                # Legacy / CLI path: scope deletions to rows under the scanned
                # folder roots.  Rows from other folders are left untouched.
                prefixes = [
                    r if r.endswith(os.sep) else r + os.sep
                    for r in folder_roots
                ]
                self.conn.execute(
                    "CREATE TEMPORARY TABLE IF NOT EXISTS _scan_roots"
                    " (prefix TEXT PRIMARY KEY)"
                )
                self.conn.execute("DELETE FROM _scan_roots")
                self.conn.executemany(
                    "INSERT OR IGNORE INTO _scan_roots (prefix) VALUES (?)",
                    ((p,) for p in prefixes),
                )
                self.conn.execute(
                    "DELETE FROM images_fts WHERE path IN ("
                    "  SELECT i.path FROM images i"
                    "  WHERE i.path NOT IN (SELECT path FROM _keep_paths)"
                    "  AND EXISTS"
                    "    (SELECT 1 FROM _scan_roots WHERE i.path LIKE prefix || '%')"
                    ")"
                )
                self.conn.execute(
                    "DELETE FROM images"
                    " WHERE path NOT IN (SELECT path FROM _keep_paths)"
                    " AND EXISTS"
                    "   (SELECT 1 FROM _scan_roots WHERE images.path LIKE prefix || '%')"
                )
                self.conn.execute("DROP TABLE IF EXISTS _scan_roots")
            else:
                self.conn.execute(
                    "DELETE FROM images_fts WHERE path IN "
                    "(SELECT path FROM images WHERE path NOT IN (SELECT path FROM _keep_paths))"
                )
                self.conn.execute(
                    "DELETE FROM images WHERE path NOT IN (SELECT path FROM _keep_paths)"
                )
            self.conn.execute("DROP TABLE IF EXISTS _keep_paths")

    # ── Marks ────────────────────────────────────────────────────────────────

    def mark_image(self, path: str, marked: bool) -> None:
        """Set or clear the mark on a single image path."""
        with self.conn:
            self.conn.execute(
                "UPDATE images SET marked = ? WHERE path = ?",
                (1 if marked else 0, path),
            )

    def mark_images(self, paths: Iterable[str], marked: bool) -> None:
        """Set or clear the mark on a collection of image paths."""
        val = 1 if marked else 0
        with self.conn:
            self.conn.executemany(
                "UPDATE images SET marked = ? WHERE path = ?",
                ((val, p) for p in paths),
            )

    def get_marked_paths(self) -> List[str]:
        """Return all currently marked image paths."""
        cur = self.conn.execute("SELECT path FROM images WHERE marked = 1")
        return [row[0] for row in cur.fetchall()]

    def get_marked_metadata(self, sort_by: str = "path_asc") -> List[dict]:
        """Return export records for all marked images in the requested order."""
        order = self._resolve_sort(sort_by, "images.path COLLATE NOCASE ASC")
        cur = self.conn.execute(
            f"SELECT path, filename, metadata_json FROM images WHERE marked = 1 ORDER BY {order}"
        )
        result: List[dict] = []
        for path, filename, metadata_json in cur.fetchall():
            try:
                meta = json.loads(metadata_json or "{}")
            except Exception:
                meta = {}
            result.append({"path": path, "filename": filename, "metadata": meta})
        return result

    def clear_all_marks(self) -> None:
        """Remove all marks from every image in the database."""
        with self.conn:
            self.conn.execute("UPDATE images SET marked = 0")

    def clear_all(self) -> None:
        # DROP + recreate the FTS5 virtual table to fully purge its shadow tables
        # (images_fts_data, images_fts_idx, etc.).  A plain DELETE leaves
        # tombstone entries that keep the file large even after VACUUM.
        self.conn.execute("DELETE FROM image_folders")
        self.conn.execute("DELETE FROM images")
        self.conn.execute("DROP TABLE IF EXISTS images_fts")
        self.conn.execute(
            "CREATE VIRTUAL TABLE images_fts"
            " USING fts5(path, filename, metadata_text)"
        )
        self.conn.commit()
        # Reclaim disk space — VACUUM must run outside any transaction.
        self.conn.execute("VACUUM")
        # In WAL mode, VACUUM writes compacted pages into the WAL file; the
        # main database file only shrinks after a checkpoint.  Force an
        # immediate full checkpoint so the file is small right away.
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    _SORT_MAP: Dict[str, str] = {
        "filename_asc":       "images.filename COLLATE NOCASE ASC",
        "filename_desc":      "images.filename COLLATE NOCASE DESC",
        "path_asc":           "images.path COLLATE NOCASE ASC",
        "path_desc":          "images.path COLLATE NOCASE DESC",
        "size_desc":          "images.size DESC",
        "size_asc":           "images.size ASC",
        "captured_desc":      "images.captured_at DESC NULLS LAST",
        "captured_asc":       "images.captured_at ASC NULLS LAST",
    }

    _DEFAULT_SORT_SQL = "images.filename COLLATE NOCASE ASC"

    @classmethod
    def _resolve_sort(cls, sort_by: str, default: str | None = None) -> str:
        """Return a known-safe ``ORDER BY`` SQL fragment for *sort_by*.

        Only values present in :pyattr:`_SORT_MAP` are accepted.  Anything
        else falls back to *default* (or ``_DEFAULT_SORT_SQL``), which makes
        SQL injection through the ``sort_by`` parameter impossible by
        construction.
        """
        return cls._SORT_MAP.get(sort_by, default or cls._DEFAULT_SORT_SQL)

    # SQL fragment used when restrict_to_enabled_folders=True.
    # Short-circuits to "show all" when image_folders is empty (CLI-indexed DBs
    # or first-run before any indexing job has run through the GUI).
    _ENABLED_CLAUSE = (
        "AND ("
        "  NOT EXISTS (SELECT 1 FROM image_folders LIMIT 1)"
        "  OR EXISTS ("
        "    SELECT 1 FROM image_folders imf"
        "    JOIN indexed_folders f ON f.id = imf.folder_id"
        "    WHERE imf.image_id = images.id AND f.enabled = 1"
        "  )"
        ")"
    )

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize a user query for FTS5 MATCH.

        FTS5's query parser raises a syntax error for characters that are
        neither alphanumeric nor a recognised FTS5 operator character (e.g.
        a bare '.' or '-' triggers "fts5: syntax error near '.'").

        Strategy: replace every character that is not part of valid FTS5 query
        syntax with a space.  Valid characters are:
          - word characters (\\w — letters, digits, underscore)
          - whitespace (token separators)
          - '"'  — phrase literal delimiter
          - '*'  — prefix wildcard (e.g. ``Fuji*``)
          - '^'  — relevance boost
          - '(' ')' — grouping

        ':' is intentionally excluded so that ExifTool group-prefixed keys such
        as ``GPS:GPSLatitude`` or ``ExifIFD:FocalLength`` can be typed verbatim
        without quoting.  The colon is converted to a token separator, turning
        ``GPS:GPSLatitude`` into the implicit-AND query ``GPS GPSLatitude``.

        This preserves FTS5 operators (AND, OR, NOT), phrase literals, prefix
        queries, and boost expressions while silently converting characters like
        '.', '-', and ':' into token separators.  A query such as
        ``img004.png`` becomes the implicit-AND query ``img004 png``, which
        correctly matches images whose FTS5 document contains both tokens.
        """
        import re
        sanitized = re.sub(r'[^\w\s"*^()]', ' ', query)
        return ' '.join(sanitized.split())

    def search_images(
        self,
        query: str,
        limit: int,
        offset: int,
        sort_by: str = "",
        ext_filter: str = "",
        path_filter: List[str] | None = None,
        restrict_to_enabled_folders: bool = False,
        marked_only: bool = False,
        date_from: int | None = None,
        date_to: int | None = None,
    ) -> List[Tuple[int, str, str, str, int, float]]:
        order = self._resolve_sort(sort_by)
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
            if len(path_filter) == 1:
                prefix = os.path.normpath(path_filter[0]) + os.sep
                path_clause = "AND images.path LIKE ?"
                path_args = (prefix + "%",)
            else:
                parts = " OR ".join("images.path LIKE ?" for _ in path_filter)
                path_clause = f"AND ({parts})"
                path_args = tuple(os.path.normpath(p) + os.sep + "%" for p in path_filter)

        date_clause, date_args = self._build_date_clause(date_from, date_to)
        marks_clause = "AND images.marked = 1" if marked_only else ""
        enabled_clause = self._ENABLED_CLAUSE if restrict_to_enabled_folders else ""

        if query.strip():
            fts_query = self._sanitize_fts_query(query)
            # When user picks an explicit sort keep it; otherwise use relevance.
            order_expr = f"ORDER BY {order}" if sort_by else "ORDER BY bm25(images_fts)"
            sql = (
                "SELECT images.id, images.path, images.filename, images.metadata_json, images.size, images.mtime "
                "FROM images_fts "
                "JOIN images ON images_fts.rowid = images.id "
                f"WHERE images_fts MATCH ? {ext_clause} {path_clause} {date_clause} {marks_clause} {enabled_clause} "
                f"{order_expr} "
                "LIMIT ? OFFSET ?"
            )
            args = (fts_query,) + ext_args + path_args + date_args + (limit, offset)
        else:
            sql = (
                "SELECT id, path, filename, metadata_json, size, mtime "
                "FROM images "
                f"WHERE 1=1 {ext_clause} {path_clause} {date_clause} {marks_clause} {enabled_clause} "
                f"ORDER BY {order} "
                "LIMIT ? OFFSET ?"
            )
            args = ext_args + path_args + date_args + (limit, offset)

        cur = self.conn.execute(sql, args)
        return cur.fetchall()

    def count_images(
        self,
        query: str,
        ext_filter: str = "",
        path_filter: List[str] | None = None,
        restrict_to_enabled_folders: bool = False,
        marked_only: bool = False,
        date_from: int | None = None,
        date_to: int | None = None,
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
            if len(path_filter) == 1:
                prefix = os.path.normpath(path_filter[0]) + os.sep
                path_clause = "AND images.path LIKE ?"
                path_args = (prefix + "%",)
            else:
                parts = " OR ".join("images.path LIKE ?" for _ in path_filter)
                path_clause = f"AND ({parts})"
                path_args = tuple(os.path.normpath(p) + os.sep + "%" for p in path_filter)

        date_clause, date_args = self._build_date_clause(date_from, date_to)
        marks_clause = "AND images.marked = 1" if marked_only else ""
        enabled_clause = self._ENABLED_CLAUSE if restrict_to_enabled_folders else ""

        if query.strip():
            fts_query = self._sanitize_fts_query(query)
            sql = (
                "SELECT COUNT(*) FROM images_fts "
                "JOIN images ON images_fts.rowid = images.id "
                f"WHERE images_fts MATCH ? {ext_clause} {path_clause} {date_clause} {marks_clause} {enabled_clause}"
            )
            args = (fts_query,) + ext_args + path_args + date_args
        else:
            sql = (
                f"SELECT COUNT(*) FROM images "
                f"WHERE 1=1 {ext_clause} {path_clause} {date_clause} {marks_clause} {enabled_clause}"
            )
            args = ext_args + path_args + date_args

        cur = self.conn.execute(sql, args)
        return int(cur.fetchone()[0])

    def get_matching_paths(
        self,
        query: str,
        ext_filter: str = "",
        path_filter: List[str] | None = None,
        restrict_to_enabled_folders: bool = False,
        marked_only: bool = False,
        date_from: int | None = None,
        date_to: int | None = None,
    ) -> List[str]:
        """Return all paths matching the current filter — no LIMIT."""
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
            if len(path_filter) == 1:
                prefix = os.path.normpath(path_filter[0]) + os.sep
                path_clause = "AND images.path LIKE ?"
                path_args = (prefix + "%",)
            else:
                parts = " OR ".join("images.path LIKE ?" for _ in path_filter)
                path_clause = f"AND ({parts})"
                path_args = tuple(os.path.normpath(p) + os.sep + "%" for p in path_filter)

        date_clause, date_args = self._build_date_clause(date_from, date_to)
        marks_clause = "AND images.marked = 1" if marked_only else ""
        enabled_clause = self._ENABLED_CLAUSE if restrict_to_enabled_folders else ""

        if query.strip():
            fts_query = self._sanitize_fts_query(query)
            sql = (
                "SELECT images.path FROM images_fts "
                "JOIN images ON images_fts.rowid = images.id "
                f"WHERE images_fts MATCH ? {ext_clause} {path_clause} {date_clause} {marks_clause} {enabled_clause}"
            )
            args = (fts_query,) + ext_args + path_args + date_args
        else:
            sql = (
                "SELECT path FROM images "
                f"WHERE 1=1 {ext_clause} {path_clause} {date_clause} {marks_clause} {enabled_clause}"
            )
            args = ext_args + path_args + date_args

        cur = self.conn.execute(sql, args)
        return [row[0] for row in cur.fetchall()]

    @staticmethod
    def _build_date_clause(
        date_from: int | None,
        date_to: int | None,
    ) -> tuple[str, tuple]:
        """Build a SQL clause and args tuple for captured_at range filtering.

        Images with NULL captured_at are excluded when either bound is set
        (they have no known capture date, so they can't satisfy a date range).
        """
        parts: list[str] = []
        args: list[int] = []
        if date_from is not None:
            parts.append("AND images.captured_at IS NOT NULL AND images.captured_at >= ?")
            args.append(date_from)
        if date_to is not None:
            parts.append("AND images.captured_at IS NOT NULL AND images.captured_at <= ?")
            args.append(date_to)
        return " ".join(parts), tuple(args)

    def get_year_counts(
        self,
        query: str = "",
        ext_filter: str = "",
        path_filter: List[str] | None = None,
        restrict_to_enabled_folders: bool = False,
    ) -> List[Tuple[int, int]]:
        """Return [(year, count)] for all images that have a captured_at value.

        Results are scoped to the current query / folder / ext context so the
        timeline histogram reflects only the visible search results.
        """
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
            if len(path_filter) == 1:
                prefix = os.path.normpath(path_filter[0]) + os.sep
                path_clause = "AND images.path LIKE ?"
                path_args = (prefix + "%",)
            else:
                parts = " OR ".join("images.path LIKE ?" for _ in path_filter)
                path_clause = f"AND ({parts})"
                path_args = tuple(os.path.normpath(p) + os.sep + "%" for p in path_filter)

        enabled_clause = self._ENABLED_CLAUSE if restrict_to_enabled_folders else ""

        if query.strip():
            fts_query = self._sanitize_fts_query(query)
            sql = (
                "SELECT CAST(strftime('%Y', datetime(images.captured_at, 'unixepoch')) AS INTEGER) AS yr, "
                "COUNT(*) AS cnt "
                "FROM images_fts "
                "JOIN images ON images_fts.rowid = images.id "
                f"WHERE images_fts MATCH ? AND images.captured_at IS NOT NULL {ext_clause} {path_clause} {enabled_clause} "
                "GROUP BY yr ORDER BY yr"
            )
            args = (fts_query,) + ext_args + path_args
        else:
            sql = (
                "SELECT CAST(strftime('%Y', datetime(captured_at, 'unixepoch')) AS INTEGER) AS yr, "
                "COUNT(*) AS cnt "
                "FROM images "
                f"WHERE captured_at IS NOT NULL {ext_clause} {path_clause} {enabled_clause} "
                "GROUP BY yr ORDER BY yr"
            )
            args = ext_args + path_args

        cur = self.conn.execute(sql, args)
        return [(int(row[0]), int(row[1])) for row in cur.fetchall()]

    # Extensions that should be merged into a single facet key.
    _EXT_ALIASES: Dict[str, str] = {"jpeg": "jpg"}

    def get_format_counts(
        self,
        query: str = "",
        path_filter: List[str] | None = None,
        restrict_to_enabled_folders: bool = False,
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
            if len(path_filter) == 1:
                prefix = os.path.normpath(path_filter[0]) + os.sep
                path_clause = "AND images.path LIKE ?"
                path_args = (prefix + "%",)
            else:
                parts = " OR ".join("images.path LIKE ?" for _ in path_filter)
                path_clause = f"AND ({parts})"
                path_args = tuple(os.path.normpath(p) + os.sep + "%" for p in path_filter)

        enabled_clause = self._ENABLED_CLAUSE if restrict_to_enabled_folders else ""

        # Fetch only filenames and group in Python so that rsplit('.', 1) correctly
        # extracts the extension after the *last* dot — INSTR finds the first dot,
        # which breaks files like "cb-01.07.16-name-.jpg".
        if query.strip():
            fts_query = self._sanitize_fts_query(query)
            sql = (
                "SELECT images.filename FROM images_fts"
                " JOIN images ON images_fts.rowid = images.id"
                f" WHERE images_fts MATCH ? AND images.filename LIKE '%.%'"
                f" {path_clause} {enabled_clause}"
            )
            args = (fts_query,) + path_args
        else:
            sql = (
                "SELECT filename FROM images"
                f" WHERE filename LIKE '%.%' {path_clause} {enabled_clause}"
            )
            args = path_args

        cur = self.conn.execute(sql, args)
        counts: Dict[str, int] = {}
        for (filename,) in cur.fetchall():
            parts = filename.rsplit(".", 1)
            if len(parts) == 2:
                ext = self._EXT_ALIASES.get(parts[1].lower(), parts[1].lower())
                if ext:
                    counts[ext] = counts.get(ext, 0) + 1
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

    def delete_orphans_under_prefix(self, folder_path: str) -> None:
        """Delete images under folder_path that have no remaining folder associations.

        Used when removing an indexed folder: images that are also covered by a
        child (or other) indexed folder still have rows in image_folders and must
        not be deleted.
        """
        prefix = os.path.normpath(folder_path) + os.sep + "%"
        with self.conn:
            self.conn.execute(
                "DELETE FROM images_fts WHERE path IN ("
                "  SELECT path FROM images"
                "  WHERE path LIKE ?"
                "  AND id NOT IN (SELECT image_id FROM image_folders)"
                ")",
                (prefix,),
            )
            self.conn.execute(
                "DELETE FROM images"
                " WHERE path LIKE ?"
                " AND id NOT IN (SELECT image_id FROM image_folders)",
                (prefix,),
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

    def get_enabled_stamps(self) -> dict[str, tuple[float, int]]:
        """Return {path: (mtime, size)} restricted to images in enabled folders.

        Falls back to get_all_stamps() when image_folders is empty (e.g. a
        CLI-only database with no folder tracking).
        """
        cur = self.conn.execute("SELECT COUNT(*) FROM image_folders")
        if cur.fetchone()[0] == 0:
            return self.get_all_stamps()
        result: dict[str, tuple[float, int]] = {}
        cur = self.conn.execute(
            "SELECT i.path, i.mtime, i.size FROM images i "
            "WHERE EXISTS ("
            "  SELECT 1 FROM image_folders imf "
            "  JOIN indexed_folders f ON f.id = imf.folder_id "
            "  WHERE imf.image_id = i.id AND f.enabled = 1"
            ")"
        )
        while True:
            rows = cur.fetchmany(2000)
            if not rows:
                break
            for row in rows:
                result[row[0]] = (row[1], row[2])
        return result

    def get_folder_stamps(self, folder_id: int) -> dict[str, tuple[float, int]]:
        """Return {path: (mtime, size)} for every image associated with *folder_id*.

        Used by the preview-cache builder to render previews for a single
        managed folder rather than the full DB.
        """
        result: dict[str, tuple[float, int]] = {}
        cur = self.conn.execute(
            "SELECT i.path, i.mtime, i.size FROM images i "
            "JOIN image_folders imf ON imf.image_id = i.id "
            "WHERE imf.folder_id = ?",
            (folder_id,),
        )
        while True:
            rows = cur.fetchmany(2000)
            if not rows:
                break
            for row in rows:
                result[row[0]] = (row[1], row[2])
        return result

    def _get_pixel_counts_query(
        self, sql: str, params: tuple = ()
    ) -> dict[str, int]:
        result: dict[str, int] = {}
        cur = self.conn.execute(sql, params)
        while True:
            rows = cur.fetchmany(2000)
            if not rows:
                break
            for path, meta_json in rows:
                px = _pixel_count_from_meta(meta_json)
                if px:
                    result[path] = px
        return result

    def get_enabled_image_pixel_counts(self) -> dict[str, int]:
        """Return {path: pixel_count} for images in enabled folders.

        Uses File:ImageWidth/Height (and fallback keys) from the stored
        exiftool metadata so thumbnail/preview workers can skip the
        file-probe step.
        """
        cur = self.conn.execute("SELECT COUNT(*) FROM image_folders")
        if cur.fetchone()[0] == 0:
            return self._get_pixel_counts_query(
                "SELECT path, metadata_json FROM images"
            )
        return self._get_pixel_counts_query(
            "SELECT i.path, i.metadata_json FROM images i "
            "WHERE EXISTS ("
            "  SELECT 1 FROM image_folders imf "
            "  JOIN indexed_folders f ON f.id = imf.folder_id "
            "  WHERE imf.image_id = i.id AND f.enabled = 1"
            ")"
        )

    def get_folder_image_pixel_counts(self, folder_id: int) -> dict[str, int]:
        """Return {path: pixel_count} for images in *folder_id*."""
        return self._get_pixel_counts_query(
            "SELECT i.path, i.metadata_json FROM images i "
            "JOIN image_folders imf ON imf.image_id = i.id "
            "WHERE imf.folder_id = ?",
            (folder_id,),
        )

    def delete_folder_associations(self, folder_id: int) -> None:
        """Remove all image_folders rows for the given folder_id."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM image_folders WHERE folder_id = ?",
                (folder_id,),
            )

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
