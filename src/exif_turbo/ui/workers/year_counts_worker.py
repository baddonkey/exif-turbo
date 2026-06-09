from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository


class YearCountsWorker(QThread):
    """Load timeline year counts off the GUI thread."""

    results_ready: Signal = Signal(list, int)
    failed: Signal = Signal(str, int)

    def __init__(
        self,
        db_path: Path,
        key: str,
        *,
        serial: int,
        query: str,
        ext_filter: str,
        path_filter: List[str] | None,
        restrict_to_enabled_folders: bool,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._serial = serial
        self._query = query
        self._ext_filter = ext_filter
        self._path_filter = path_filter
        self._restrict = restrict_to_enabled_folders

    def run(self) -> None:
        try:
            repo = ImageIndexRepository(self._db_path, key=self._key)
            counts = repo.get_year_counts(
                query=self._query,
                ext_filter=self._ext_filter,
                path_filter=self._path_filter,
                restrict_to_enabled_folders=self._restrict,
            )
            repo.close()
            self.results_ready.emit(counts, self._serial)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc), self._serial)
