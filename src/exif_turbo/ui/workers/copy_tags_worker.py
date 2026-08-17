from __future__ import annotations

import threading
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...config import tgm_snapshot_path
from ...data.image_index_repository import ImageIndexRepository
from ...tagging.sidecar_repository import FilesystemSidecarRepository
from ...tagging.tagging_service import CopyTagsMode, TaggingService
from ...tagging.tgm_snapshot_repository import TgmSnapshotRepository


class CopyTagsWorker(QThread):
    progress = Signal(int, int, object)
    result_ready = Signal(object)
    failed = Signal(str)
    canceled = Signal(object)

    def __init__(
        self,
        db_path: Path,
        key: str,
        source_image_path: str,
        mode: str,
        *,
        image_paths: Iterable[str] | None = None,
        marked_only: bool = False,
        query: str = "",
        ext_filter: str = "",
        path_filter: Iterable[str] | None = None,
        restrict_to_enabled_folders: bool = False,
        date_from: int | None = None,
        date_to: int | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._source_image_path = source_image_path
        self._mode = CopyTagsMode(mode)
        self._image_paths = None if image_paths is None else tuple(image_paths)
        self._marked_only = marked_only
        self._query = query
        self._ext_filter = ext_filter
        self._path_filter = None if path_filter is None else list(path_filter)
        self._restrict_to_enabled_folders = restrict_to_enabled_folders
        self._date_from = date_from
        self._date_to = date_to
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        image_repository: ImageIndexRepository | None = None
        try:
            image_repository = ImageIndexRepository(self._db_path, key=self._key)
            image_paths = self._image_paths
            if image_paths is None:
                if self._marked_only:
                    image_paths = image_repository.get_marked_paths(
                        restrict_to_enabled_folders=self._restrict_to_enabled_folders
                    )
                else:
                    image_paths = image_repository.get_matching_paths(
                        self._query,
                        ext_filter=self._ext_filter,
                        path_filter=self._path_filter,
                        restrict_to_enabled_folders=self._restrict_to_enabled_folders,
                        date_from=self._date_from,
                        date_to=self._date_to,
                    )
            result = TaggingService(
                image_repository,
                FilesystemSidecarRepository(),
                TgmSnapshotRepository(tgm_snapshot_path(self._db_path)),
            ).copy_tags_to_paths(
                self._source_image_path,
                image_paths,
                self._mode,
                on_progress=self.progress.emit,
                cancel_check=self._cancel_event.is_set,
            )
            if result.cancelled:
                self.canceled.emit(result)
            else:
                self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if image_repository is not None:
                image_repository.close()
