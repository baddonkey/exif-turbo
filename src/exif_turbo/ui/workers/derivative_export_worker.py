from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...models.derivative_export_flavour import DerivativeExportFlavour
from ...tagging.derivative_export_service import (
    DerivativeExportItemResult,
    DerivativeExportResult,
    DerivativeExportService,
    MetadataWriter,
)
from ...tagging.media_conversion import DerivativeMediaConverter


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
        matching_results: bool = False,
        query: str = "",
        ext_filter: str = "",
        path_filter: Iterable[str] | None = None,
        restrict_to_enabled_folders: bool = False,
        marked_only: bool = False,
        date_from: int | None = None,
        date_to: int | None = None,
        image_set_id: int | None = None,
        metadata_writer: MetadataWriter | None = None,
        media_converter: DerivativeMediaConverter | None = None,
        auto_repair_tags: bool = True,
        write_description_to_xpcomment: bool = True,
        flavours: Sequence[DerivativeExportFlavour] | None = None,
        preserve_folder_structure: bool = True,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._indexed_roots = dict(indexed_roots)
        self._output_root = output_root
        self._image_paths = None if image_paths is None else tuple(image_paths)
        self._matching_results = matching_results
        self._query = query
        self._ext_filter = ext_filter
        self._path_filter = None if path_filter is None else list(path_filter)
        self._restrict_to_enabled_folders = restrict_to_enabled_folders
        self._marked_only = marked_only
        self._date_from = date_from
        self._date_to = date_to
        self._image_set_id = image_set_id
        self._metadata_writer = metadata_writer
        self._media_converter = media_converter
        self._auto_repair_tags = auto_repair_tags
        self._write_description_to_xpcomment = write_description_to_xpcomment
        self._flavours = None if flavours is None else tuple(flavours)
        self._preserve_folder_structure = preserve_folder_structure
        self._cancel_event = threading.Event()
        self.result: DerivativeExportResult | None = None

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        repository: ImageIndexRepository | None = None
        try:
            repository = ImageIndexRepository(self._db_path, key=self._key)
            service = DerivativeExportService(
                repository,
                self._metadata_writer,
                auto_repair_tags=self._auto_repair_tags,
                write_description_to_xpcomment=self._write_description_to_xpcomment,
                media_converter=self._media_converter,
            )
            image_paths = self._image_paths
            if image_paths is None and self._matching_results:
                image_paths = repository.get_matching_paths(
                    self._query,
                    ext_filter=self._ext_filter,
                    path_filter=self._path_filter,
                    restrict_to_enabled_folders=self._restrict_to_enabled_folders,
                    marked_only=self._marked_only,
                    date_from=self._date_from,
                    date_to=self._date_to,
                    image_set_id=self._image_set_id,
                )
            plan = service.create_plan(
                self._indexed_roots,
                self._output_root,
                image_paths=image_paths,
                flavours=self._flavours,
                preserve_folder_structure=self._preserve_folder_structure,
            )
            self.progress.emit(0, len(plan.items), None)
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