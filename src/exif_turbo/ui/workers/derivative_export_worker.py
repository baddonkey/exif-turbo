from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable, Mapping

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...tagging.derivative_export_service import (
    DerivativeExportItemResult,
    DerivativeExportResult,
    DerivativeExportService,
    MetadataWriter,
)


class DerivativeExportWorker(QThread):
    progress = Signal(int, int, object)
    result_ready = Signal(object)
    canceled = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        key: str,
        indexed_roots: Mapping[Path | str, str],
        output_root: Path,
        *,
        image_paths: Iterable[Path | str] | None = None,
        metadata_writer: MetadataWriter | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._indexed_roots = dict(indexed_roots)
        self._output_root = output_root
        self._image_paths = None if image_paths is None else tuple(image_paths)
        self._metadata_writer = metadata_writer
        self._cancel_event = threading.Event()
        self.result: DerivativeExportResult | None = None

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        repository: ImageIndexRepository | None = None
        try:
            repository = ImageIndexRepository(self._db_path, key=self._key)
            service = DerivativeExportService(repository, self._metadata_writer)
            plan = service.create_plan(
                self._indexed_roots,
                self._output_root,
                image_paths=self._image_paths,
            )
            self.result = service.export(
                plan,
                on_progress=self._emit_progress,
                cancel_check=self._cancel_event.is_set,
            )
            if self.result.canceled_count:
                self.canceled.emit(self.result)
            else:
                self.result_ready.emit(self.result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if repository is not None:
                repository.close()

    def _emit_progress(
        self,
        done: int,
        total: int,
        item: DerivativeExportItemResult,
    ) -> None:
        self.progress.emit(done, total, item)