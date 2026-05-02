from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository

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
        self._cancel_event = threading.Event()

        # Output fields — read by the controller in the finished slot
        self.result_paths: List[str] = []
        self.result_export_count: int = 0

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
        # Step 1: discover matching paths (total unknown yet → indeterminate)
        self.progress.emit(0, 0)

        paths = repo.get_matching_paths(
            self._query,
            ext_filter=self._ext_filter,
            path_filter=self._path_filter,
            restrict_to_enabled_folders=self._restrict_to_enabled_folders,
            marked_only=self._marked_only,
        )

        if self._is_canceled():
            self.canceled.emit()
            return

        total = len(paths)
        self.progress.emit(0, total)

        # Step 2: write marks in batches so the progress bar advances
        val = 1 if self._mark_value else 0
        done = 0
        with repo.conn:
            for i in range(0, total, _BATCH_SIZE):
                if self._is_canceled():
                    self.canceled.emit()
                    return
                batch = paths[i : i + _BATCH_SIZE]
                repo.conn.executemany(
                    "UPDATE images SET marked = ? WHERE path = ?",
                    ((val, p) for p in batch),
                )
                done += len(batch)
                self.progress.emit(done, total)

        # Step 3: read back full marked set
        self.result_paths = repo.get_marked_paths()
        self.finished.emit()

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
