from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...utils.preview_cache import preview_cache_name_from_stamp, preview_dir
from ...utils.thumb_cache import thumb_cache_name_from_stamp

_BATCH_SIZE = 500  # rows per progress tick for mark operations


class BulkOpWorker(QThread):
    """Run a bulk mark or export operation on a background thread.

    The worker opens its own DB connection so the main thread remains
    responsive.  After *finished* is emitted the caller may read
    *result_paths* (select/deselect) or *result_export_count* (export).
    """

    progress = Signal(int, int)   # (done, total) — for a progress bar
    finished = Signal()
    failed = Signal(str)
    canceled = Signal()

    def __init__(
        self,
        db_path: Path,
        key: str,
        operation: str,
        *,
        # select_all / deselect_all
        query: str = "",
        ext_filter: str = "",
        path_filter: List[str] | None = None,
        restrict_to_enabled_folders: bool = False,
        marked_only: bool = False,
        mark_value: bool = True,
        # export_json
        file_path: Path | None = None,
        sort_by: str = "path_asc",
        # select_missing_thumbs
        cache_dir: Path | None = None,
        # date filter
        date_from: int | None = None,
        date_to: int | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._operation = operation
        self._query = query
        self._ext_filter = ext_filter
        self._path_filter = path_filter
        self._restrict_to_enabled_folders = restrict_to_enabled_folders
        self._marked_only = marked_only
        self._mark_value = mark_value
        self._file_path = file_path
        self._sort_by = sort_by
        self._cache_dir = cache_dir
        self._date_from = date_from
        self._date_to = date_to
        self._cancel_event = threading.Event()

        # Output fields — read by the controller in the finished slot
        self.result_paths: List[str] = []
        self.result_paths_added: List[str] = []
        self.result_paths_removed: List[str] = []
        self.result_export_count: int = 0
        self.result_deleted_count: int = 0
        self.result_missing_count: int = 0
        self.result_failed_count: int = 0

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        self._cancel_event.set()

    def _is_canceled(self) -> bool:
        return self._cancel_event.is_set()

    # ------------------------------------------------------------------
    def run(self) -> None:
        try:
            repo = ImageIndexRepository(self._db_path, key=self._key)
            if self._operation in ("select_all", "deselect_all"):
                self._run_mark(repo)
            elif self._operation == "invert":
                self._run_invert(repo)
            elif self._operation == "select_missing_thumbs":
                self._run_select_missing_thumbs(repo)
            elif self._operation == "delete_marked":
                self._run_delete_marked(repo)
            elif self._operation == "export_json":
                self._run_export(repo)
            else:
                self.failed.emit(f"Unknown operation: {self._operation!r}")
        except Exception as exc:
            self.failed.emit(str(exc))

    def _run_mark(self, repo: ImageIndexRepository) -> None:
        if self._is_canceled():
            self.canceled.emit()
            return
        self.progress.emit(0, 0)
        paths = repo.bulk_mark_images(
            self._mark_value,
            query=self._query,
            ext_filter=self._ext_filter,
            path_filter=self._path_filter,
            restrict_to_enabled_folders=self._restrict_to_enabled_folders,
            marked_only=self._marked_only,
            date_from=self._date_from,
            date_to=self._date_to,
        )
        self.progress.emit(len(paths), len(paths))
        self.result_paths = paths
        self.finished.emit()

    def _run_invert(self, repo: ImageIndexRepository) -> None:
        if self._is_canceled():
            self.canceled.emit()
            return
        self.progress.emit(0, 0)
        added, removed = repo.bulk_invert_images(
            query=self._query,
            ext_filter=self._ext_filter,
            path_filter=self._path_filter,
            restrict_to_enabled_folders=self._restrict_to_enabled_folders,
            marked_only=self._marked_only,
            date_from=self._date_from,
            date_to=self._date_to,
        )
        affected = len(added) + len(removed)
        self.progress.emit(affected, affected)
        self.result_paths_added = added
        self.result_paths_removed = removed
        self.finished.emit()

    def _run_select_missing_thumbs(self, repo: ImageIndexRepository) -> None:
        """Mark every matching image whose thumbnail is not cached on disk.

        ``.skip`` sentinels (files the thumbnailer gave up on — too large,
        decoder errors, etc.) are *not* treated as cached: from the user's
        point of view those images still have no thumbnail and should be
        surfaced so they can be acted on.
        """
        import os as _os

        if self._cache_dir is None:
            self.failed.emit("cache_dir is required for select_missing_thumbs")
            return
        if self._is_canceled():
            self.canceled.emit()
            return

        self.progress.emit(0, 0)

        paths = repo.get_matching_paths(
            self._query,
            ext_filter=self._ext_filter,
            path_filter=self._path_filter,
            restrict_to_enabled_folders=self._restrict_to_enabled_folders,
            marked_only=self._marked_only,
            date_from=self._date_from,
            date_to=self._date_to,
        )
        if self._is_canceled():
            self.canceled.emit()
            return

        # Pre-scan cache dir once.  Only real thumbnail files count as cached;
        # ``.skip`` sentinels mean "no thumbnail will ever exist" and are
        # therefore considered missing.
        encrypted = bool(self._key)
        thumb_suffix = ".enc" if encrypted else ".png"
        existing: set[str] = set()
        try:
            with _os.scandir(self._cache_dir) as it:
                for entry in it:
                    if entry.name.endswith(thumb_suffix):
                        existing.add(entry.name)
        except OSError:
            pass

        # Stamps drive the deterministic cache filename (no live os.stat).
        stamps = repo.get_all_stamps()

        total = len(paths)
        self.progress.emit(0, total)

        missing: list[str] = []
        for i, p in enumerate(paths):
            if self._is_canceled():
                self.canceled.emit()
                return
            stamp = stamps.get(p)
            if stamp is None:
                missing.append(p)
            else:
                base = thumb_cache_name_from_stamp(p, stamp[0], stamp[1])
                expected = base[:-4] + thumb_suffix
                if expected not in existing:
                    missing.append(p)
            if (i + 1) % _BATCH_SIZE == 0:
                self.progress.emit(i + 1, total)
        self.progress.emit(total, total)

        with repo.conn:
            for i in range(0, len(missing), _BATCH_SIZE):
                if self._is_canceled():
                    self.canceled.emit()
                    return
                batch = missing[i : i + _BATCH_SIZE]
                repo.conn.executemany(
                    "UPDATE images SET marked = 1 WHERE path = ?",
                    ((p,) for p in batch),
                )

        self.result_paths = repo.get_marked_paths()
        self.finished.emit()

    def _run_delete_marked(self, repo: ImageIndexRepository) -> None:
        """Delete every marked image from disk and from the index.

        Also removes any cached thumbnail / preview / .skip sentinel for the
        deleted images so the cache does not accumulate orphan entries.
        Reports progress per file so the busy overlay advances smoothly.
        """
        if self._is_canceled():
            self.canceled.emit()
            return

        self.progress.emit(0, 0)
        paths = repo.get_marked_paths()
        total = len(paths)
        self.progress.emit(0, total)

        if total == 0:
            self.finished.emit()
            return

        # Stamps drive the deterministic cache filenames \u2014 avoids live os.stat
        # on a file we may have just unlinked.
        stamps = repo.get_all_stamps()
        encrypted = bool(self._key)
        thumb_suffix = ".enc" if (encrypted and self._cache_dir is not None) else ".png"
        prev_suffix = ".jpg.enc" if encrypted else ".jpg"
        prev_dir = preview_dir(self._cache_dir) if self._cache_dir is not None else None

        deleted = 0
        missing = 0
        failed = 0
        deleted_paths: list[str] = []

        for i, path in enumerate(paths):
            if self._is_canceled():
                # Persist the partial deletion before stopping so DB and disk
                # stay in sync with what was actually removed.
                self._purge_db_rows(repo, deleted_paths)
                self.canceled.emit()
                return
            try:
                os.unlink(path)
                deleted += 1
                deleted_paths.append(path)
            except FileNotFoundError:
                # Already gone \u2014 still purge the DB row.
                missing += 1
                deleted_paths.append(path)
            except OSError:
                failed += 1
                # Skip cache cleanup and DB purge on failure so the user can retry.
                self.progress.emit(i + 1, total)
                continue

            # Best-effort cache cleanup.
            if self._cache_dir is not None:
                stamp = stamps.get(path)
                if stamp is not None:
                    base_thumb = thumb_cache_name_from_stamp(path, stamp[0], stamp[1])
                    base_prev = preview_cache_name_from_stamp(path, stamp[0], stamp[1])
                    cache_files = [
                        self._cache_dir / (base_thumb[:-4] + thumb_suffix),
                        self._cache_dir / (base_thumb[:-4] + ".skip"),
                    ]
                    if prev_dir is not None:
                        cache_files.append(prev_dir / (base_prev[:-4] + prev_suffix))
                    for cf in cache_files:
                        try:
                            cf.unlink()
                        except FileNotFoundError:
                            pass
                        except OSError:
                            pass

            self.progress.emit(i + 1, total)

        self._purge_db_rows(repo, deleted_paths)

        self.result_deleted_count = deleted
        self.result_missing_count = missing
        self.result_failed_count = failed
        # Refresh the marked set \u2014 only the rows we failed to delete remain.
        self.result_paths = repo.get_marked_paths()
        self.finished.emit()

    def _purge_db_rows(
        self, repo: ImageIndexRepository, paths: list[str]
    ) -> None:
        """Remove *paths* from images, images_fts and image_folders."""
        if not paths:
            return
        with repo.conn:
            for i in range(0, len(paths), _BATCH_SIZE):
                batch = paths[i : i + _BATCH_SIZE]
                placeholders = ",".join("?" * len(batch))
                repo.conn.execute(
                    f"DELETE FROM images_fts WHERE path IN ({placeholders})",
                    batch,
                )
                repo.conn.execute(
                    f"DELETE FROM image_folders WHERE image_id IN ("
                    f"  SELECT id FROM images WHERE path IN ({placeholders})"
                    f")",
                    batch,
                )
                repo.conn.execute(
                    f"DELETE FROM images WHERE path IN ({placeholders})",
                    batch,
                )

    def _run_export(self, repo: ImageIndexRepository) -> None:
        if self._is_canceled():
            self.canceled.emit()
            return
        # Step 1: fetch records (total unknown yet → indeterminate)
        self.progress.emit(0, 0)

        records = repo.get_marked_metadata(self._sort_by)

        if self._is_canceled():
            self.canceled.emit()
            return

        total = len(records)
        self.progress.emit(0, total)

        # Step 2: write JSON one record at a time so the progress bar advances
        assert self._file_path is not None
        with open(self._file_path, "w", encoding="utf-8") as fh:
            fh.write("[\n")
            for idx, record in enumerate(records):
                if self._is_canceled():
                    self.canceled.emit()
                    return
                fh.write(json.dumps(record, ensure_ascii=False))
                if idx < total - 1:
                    fh.write(",\n")
                else:
                    fh.write("\n")
                self.progress.emit(idx + 1, total)
            fh.write("]\n")

        self.result_export_count = total
        self.finished.emit()
