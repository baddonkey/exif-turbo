from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...config import tgm_snapshot_path, tgm_work_dir
from ...data.image_index_repository import ImageIndexRepository
from ...tagging.tgm_snapshot_repository import TgmSnapshotRepository
from ...tagging.tgm_update_service import TgmUpdateService


class TgmUpdateWorker(QThread):
    progress = Signal(int, int, str)
    result_ready = Signal(object)
    failed = Signal(str)
    canceled = Signal()

    def __init__(self, db_path: Path, key: str) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        image_repository: ImageIndexRepository | None = None
        try:
            if self._cancel_event.is_set():
                self.canceled.emit()
                return
            self.progress.emit(0, 0, "Downloading TGM")
            image_repository = ImageIndexRepository(self._db_path, key=self._key)
            service = TgmUpdateService(
                TgmSnapshotRepository(tgm_snapshot_path(self._db_path)),
                work_dir=tgm_work_dir(self._db_path),
                image_repository=image_repository,
            )
            snapshot = service.update()
            if self._cancel_event.is_set():
                self.canceled.emit()
                return
            self.progress.emit(1, 1, "TGM installed")
            self.result_ready.emit(snapshot)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if image_repository is not None:
                image_repository.close()