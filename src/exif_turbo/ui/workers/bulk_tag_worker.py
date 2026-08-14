from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...config import tgm_snapshot_path
from ...data.image_index_repository import ImageIndexRepository
from ...tagging.sidecar_repository import FilesystemSidecarRepository
from ...tagging.tagging_service import TaggingService
from ...tagging.tgm_snapshot_repository import TgmSnapshotRepository


class BulkTagWorker(QThread):
    progress = Signal(int, int, object)
    result_ready = Signal(object)
    failed = Signal(str)
    canceled = Signal(object)

    def __init__(
        self,
        db_path: Path,
        key: str,
        operation: str,
        concept_reference: str,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._operation = operation
        self._concept_reference = concept_reference
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        image_repository: ImageIndexRepository | None = None
        try:
            image_repository = ImageIndexRepository(self._db_path, key=self._key)
            service = TaggingService(
                image_repository,
                FilesystemSidecarRepository(),
                TgmSnapshotRepository(tgm_snapshot_path(self._db_path)),
            )
            if self._operation == "add":
                result = service.add_concept_to_marked(
                    self._concept_reference,
                    on_progress=self.progress.emit,
                    cancel_check=self._cancel_event.is_set,
                )
            elif self._operation == "remove":
                result = service.remove_concept_from_marked(
                    self._concept_reference,
                    on_progress=self.progress.emit,
                    cancel_check=self._cancel_event.is_set,
                )
            else:
                raise ValueError(f"unknown bulk tag operation: {self._operation}")
            if result.cancelled:
                self.canceled.emit(result)
            else:
                self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if image_repository is not None:
                image_repository.close()