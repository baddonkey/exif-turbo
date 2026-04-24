from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...indexing.indexer_service import IndexerService


class IndexWorker(QThread):
    finished = Signal(int)
    failed = Signal(str)
    progress = Signal(int, int, str)
    canceled = Signal(int)

    def __init__(
        self,
        db_path: Path,
        folders: List[Path],
        workers: int = 12,
        key: str = "",
        force: bool = False,
        clear_cache_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.folders = folders
        self.workers = max(1, workers)
        self._key = key
        self._force = force
        self._clear_cache_dir = clear_cache_dir
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            if self._clear_cache_dir is not None:
                if self._clear_cache_dir.exists():
                    shutil.rmtree(self._clear_cache_dir, ignore_errors=True)
                self._clear_cache_dir.mkdir(parents=True, exist_ok=True)
            repo = ImageIndexRepository(self.db_path, key=self._key)
            indexer = IndexerService(repo)
            count = indexer.build_index(
                self.folders,
                None,
                on_progress=lambda current, total, p: self.progress.emit(
                    current,
                    total,
                    str(p),
                ),
                workers=self.workers,
                cancel_check=self._cancel_event.is_set,
                force=self._force,
            )
            repo.close()
            if self._cancel_event.is_set():
                self.canceled.emit(count)
            else:
                self.finished.emit(count)
        except Exception as exc:
            self.failed.emit(str(exc))
