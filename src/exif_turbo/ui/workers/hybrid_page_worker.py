from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...data.hybrid_search import HybridSearchResults
from ...data.image_index_repository import ImageIndexRepository


class HybridPageWorker(QThread):
    results_ready: Signal = Signal(list, int)
    failed: Signal = Signal(str, int)

    def __init__(
        self, db_path: Path, key: str, results: HybridSearchResults,
        position: int, page_size: int, serial: int,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._results = results
        self._position = position
        self._page_size = page_size
        self._serial = serial

    def run(self) -> None:
        try:
            repo = ImageIndexRepository(self._db_path, key=self._key)
            try:
                rows = self._results.hydrate_page(repo, self._position, self._page_size)
            finally:
                repo.close()
            if not self.isInterruptionRequested():
                self.results_ready.emit(rows, self._serial)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc), self._serial)
        finally:
            self._key = ""
