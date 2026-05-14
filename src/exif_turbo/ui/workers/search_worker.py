from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository


class SearchWorker(QThread):
    """Run a search query off the GUI thread.

    Opens its own DB connection so the main thread's event loop is never
    blocked by WAL reads — critical when the IndexWorker is scanning a NAS
    and saturating the SMB connection with directory-listing I/O.

    Signals
    -------
    results_ready(rows, total, format_counts, serial)
        Emitted with the query results when the search completes.
        ``serial`` matches the value passed to the constructor so the
        controller can discard stale results if a newer search was
        already submitted.
    failed(str)
        Emitted if the query raises an exception.
    """

    results_ready: Signal = Signal(list, int, list, int)
    failed:         Signal = Signal(str)

    def __init__(
        self,
        db_path: Path,
        key: str,
        *,
        query: str,
        page_size: int,
        offset: int,
        sort_by: str,
        ext_filter: str,
        path_filter: List[str] | None,
        restrict_to_enabled_folders: bool,
        marked_only: bool,
        serial: int,
        date_from: int | None = None,
        date_to: int | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._query = query
        self._page_size = page_size
        self._offset = offset
        self._sort_by = sort_by
        self._ext_filter = ext_filter
        self._path_filter = path_filter
        self._restrict = restrict_to_enabled_folders
        self._marked_only = marked_only
        self._serial = serial
        self._date_from = date_from
        self._date_to = date_to

    def run(self) -> None:
        try:
            repo = ImageIndexRepository(self._db_path, key=self._key)
            rows: list = repo.search_images(
                self._query, self._page_size, self._offset,
                sort_by=self._sort_by,
                ext_filter=self._ext_filter,
                path_filter=self._path_filter,
                restrict_to_enabled_folders=self._restrict,
                marked_only=self._marked_only,
                date_from=self._date_from,
                date_to=self._date_to,
            )
            total: int = repo.count_images(
                self._query,
                ext_filter=self._ext_filter,
                path_filter=self._path_filter,
                restrict_to_enabled_folders=self._restrict,
                marked_only=self._marked_only,
                date_from=self._date_from,
                date_to=self._date_to,
            )
            format_counts: list = repo.get_format_counts(
                query=self._query,
                path_filter=self._path_filter,
                restrict_to_enabled_folders=self._restrict,
            )
            repo.close()
            self.results_ready.emit(rows, total, format_counts, self._serial)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
