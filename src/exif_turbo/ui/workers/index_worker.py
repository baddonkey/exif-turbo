from __future__ import annotations

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

    def __init__(self, db_path: Path, folders: List[Path], workers: int = 12) -> None:
        super().__init__()
        self.db_path = db_path
        self.folders = folders
        self.workers = max(1, workers)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            repo = ImageIndexRepository(self.db_path)
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
            )
            repo.close()
            if self._cancel_event.is_set():
                self.canceled.emit(count)
            else:
                self.finished.emit(count)
        except Exception as exc:
            self.failed.emit(str(exc))
