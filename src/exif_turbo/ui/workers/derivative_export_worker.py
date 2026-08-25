from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable, Mapping

from PySide6.QtCore import QThread, Signal

from ...config import (
    tgm_localization_pack_path,
    tgm_snapshot_path,
)
from ...data.image_index_repository import ImageIndexRepository
from ...tagging.derivative_export_service import (
    DerivativeExportItemResult,
    DerivativeExportResult,
    DerivativeExportService,
    MetadataWriter,
)
from ...tagging.tgm_localization_repository import TgmLocalizationRepository
from ...tagging.tgm_localization_service import TgmLocalizationService
from ...tagging.tgm_snapshot_repository import TgmSnapshotRepository
from ...tagging.composite_vocabulary_repository import (
    bundled_controlled_vocabulary_repository,
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
        matching_results: bool = False,
        query: str = "",
        ext_filter: str = "",
        path_filter: Iterable[str] | None = None,
        restrict_to_enabled_folders: bool = False,
        marked_only: bool = False,
        date_from: int | None = None,
        date_to: int | None = None,
        metadata_writer: MetadataWriter | None = None,
        tag_export_mode: str = "canonical",
        interface_locale: str = "en",
        selected_locales: tuple[str, ...] = (),
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
        self._metadata_writer = metadata_writer
        self._tag_export_mode = tag_export_mode
        self._interface_locale = interface_locale
        self._selected_locales = selected_locales
        self._cancel_event = threading.Event()
        self.result: DerivativeExportResult | None = None

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        repository: ImageIndexRepository | None = None
        try:
            repository = ImageIndexRepository(self._db_path, key=self._key)
            localization_service = None
            if (
                tgm_snapshot_path(self._db_path).exists()
                and tgm_localization_pack_path(self._db_path).exists()
            ):
                localization_service = TgmLocalizationService(
                    TgmSnapshotRepository(tgm_snapshot_path(self._db_path)),
                    TgmLocalizationRepository(tgm_localization_pack_path(self._db_path)),
                )
            service = DerivativeExportService(
                repository,
                self._metadata_writer,
                localization_service=localization_service,
                vocabulary_repository=bundled_controlled_vocabulary_repository(),
                tag_export_mode=self._tag_export_mode,
                interface_locale=self._interface_locale,
                selected_locales=self._selected_locales,
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
                )
            plan = service.create_plan(
                self._indexed_roots,
                self._output_root,
                image_paths=image_paths,
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