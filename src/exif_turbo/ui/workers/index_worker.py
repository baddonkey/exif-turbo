from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...indexing.image_finder import ImageFinder
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
        blacklist: List[str] | None = None,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.folders = folders
        self.workers = max(1, workers)
        self._key = key
        self._force = force
        self._clear_cache_dir = clear_cache_dir
        self._blacklist: List[str] = list(blacklist) if blacklist else []
        self._cancel_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()  # starts unpaused

    def cancel(self) -> None:
        self._cancel_event.set()
        self._resume_event.set()  # unblock any thread waiting in pause

    def pause(self) -> None:
        """Temporarily suspend indexing I/O to yield bandwidth to the preview."""
        self._resume_event.clear()

    def resume(self) -> None:
        """Resume indexing after a preview has had time to load."""
        self._resume_event.set()

    def _cancel_or_pause(self) -> bool:
        """cancel_check callable: blocks while paused, then returns the canceled state."""
        if not self._resume_event.is_set():
            self._resume_event.wait(timeout=2.0)
        return self._cancel_event.is_set()

    def run(self) -> None:
        try:
            if self._clear_cache_dir is not None:
                if self._clear_cache_dir.exists():
                    shutil.rmtree(self._clear_cache_dir, ignore_errors=True)
                self._clear_cache_dir.mkdir(parents=True, exist_ok=True)
            repo = ImageIndexRepository(self.db_path, key=self._key)
            finder = ImageFinder(blacklist=self._blacklist)
            indexer = IndexerService(repo, finder=finder)
            _last_emit: list[float] = [0.0]  # mutable cell for the closure

            def _on_progress(current: int, total: int, p: Path) -> None:
                now = time.monotonic()
                # Emit at most ~20 Hz; always emit the final update.
                # This prevents flooding Qt's cross-thread signal queue and
                # keeps the GUI event loop free to handle user input.
                if now - _last_emit[0] >= 0.05 or current == total:
                    _last_emit[0] = now
                    self.progress.emit(current, total, str(p))

            count = indexer.build_index(
                self.folders,
                None,
                on_progress=_on_progress,
                workers=self.workers,
                cancel_check=self._cancel_or_pause,
                force=self._force,
            )
            repo.close()
            if self._cancel_event.is_set():
                self.canceled.emit(count)
            else:
                self.finished.emit(count)
        except Exception as exc:
            self.failed.emit(str(exc))

