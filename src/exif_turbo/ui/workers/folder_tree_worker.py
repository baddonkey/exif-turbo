from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository


class FolderTreeWorker(QThread):
    """Load the folder tree off the GUI thread.

    Opens its own DB connection so the main thread stays responsive.

    Signals
    -------
    results_ready(json_str)
        Emitted with the folder-tree JSON when the query completes.
    failed(error)
        Emitted if the query raises an exception.
    """

    results_ready: Signal = Signal(str)
    failed: Signal = Signal(str)

    def __init__(self, db_path: Path, key: str) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key

    def run(self) -> None:
        try:
            repo = ImageIndexRepository(self._db_path, key=self._key)
            nodes = repo.get_folder_tree()
            repo.close()
            self.results_ready.emit(json.dumps(nodes))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
