from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import (
    EmptyImageSetReplaceError,
    ImageIndexRepository,
    ImageSetFilterReapplyCanceled,
)

_BATCH_SIZE = 500


class ImageSetMembershipWorker(QThread):
    progress = Signal(int, int)
    result_ready = Signal(int, int, int)
    failed = Signal(str)
    canceled = Signal(int, int, int)
    empty_replace_confirmation_required = Signal()

    def __init__(
        self,
        db_path: Path,
        key: str,
        set_id: int,
        target_scope: str,
        add: bool,
        *,
        selected_path: str | None = None,
        image_paths: Sequence[str] | None = None,
        query: str = "",
        ext_filter: str = "",
        path_filter: Sequence[str] | None = None,
        restrict_to_enabled_folders: bool = False,
        marked_only: bool = False,
        date_from: int | None = None,
        date_to: int | None = None,
        browse_folder: str = "",
        filter_mode: str | None = None,
        confirm_empty_replace: bool = False,
        image_set_id: int | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._set_id = set_id
        self._target_scope = target_scope
        self._add = add
        self._selected_path = selected_path
        self._image_paths = None if image_paths is None else tuple(image_paths)
        self._query = query
        self._ext_filter = ext_filter
        self._path_filter = None if path_filter is None else tuple(path_filter)
        self._restrict_to_enabled_folders = restrict_to_enabled_folders
        self._marked_only = marked_only
        self._date_from = date_from
        self._date_to = date_to
        self._browse_folder = browse_folder
        self._filter_mode = filter_mode
        self._confirm_empty_replace = confirm_empty_replace
        self._image_set_filter_id = image_set_id
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _resolve_paths(self, repository: ImageIndexRepository) -> list[str]:
        if self._target_scope == "selected":
            if not self._selected_path:
                raise ValueError("Select an image first.")
            return [self._selected_path]
        if self._target_scope == "marked":
            return repository.get_marked_paths()
        if self._target_scope == "results":
            if self._image_paths is not None:
                return list(self._image_paths)
            return repository.get_matching_paths(
                self._query,
                ext_filter=self._ext_filter,
                path_filter=None if self._path_filter is None else list(self._path_filter),
                restrict_to_enabled_folders=self._restrict_to_enabled_folders,
                marked_only=self._marked_only,
                date_from=self._date_from,
                date_to=self._date_to,
                image_set_id=self._image_set_filter_id,
            )
        if self._target_scope == "folder":
            if not self._browse_folder:
                raise ValueError("Choose a folder in Browse first.")
            return repository.get_matching_paths(
                "", path_filter=[self._browse_folder]
            )
        raise ValueError("Choose a valid image scope.")

    def run(self) -> None:
        repository: ImageIndexRepository | None = None
        added = 0
        removed = 0
        completed = 0
        try:
            repository = ImageIndexRepository(self._db_path, key=self._key)
            if self._target_scope == "filter":
                if self._filter_mode is None:
                    raise ValueError("filter_mode is required for filter reapply.")
                try:
                    result = repository.reapply_image_set_filter_with_progress(
                        self._set_id,
                        mode=self._filter_mode,
                        confirm_empty_replace=self._confirm_empty_replace,
                        cancel_check=self._cancel_event.is_set,
                        on_progress=self.progress.emit,
                        batch_size=_BATCH_SIZE,
                    )
                except EmptyImageSetReplaceError:
                    self.empty_replace_confirmation_required.emit()
                    return
                except ImageSetFilterReapplyCanceled as exc:
                    self.canceled.emit(exc.processed, exc.added, exc.removed)
                    return
                self.result_ready.emit(
                    result["matched"], result["added"], result["removed"]
                )
                return
            paths = self._resolve_paths(repository)
            total = len(paths)
            self.progress.emit(0, total)
            for start in range(0, total, _BATCH_SIZE):
                if self._cancel_event.is_set():
                    self.canceled.emit(completed, added, removed)
                    return
                batch = paths[start : start + _BATCH_SIZE]
                if self._add:
                    added += repository.add_images_to_set(self._set_id, batch)
                else:
                    removed += repository.remove_images_from_set(self._set_id, batch)
                completed += len(batch)
                self.progress.emit(completed, total)
            self.result_ready.emit(total, added, removed)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if repository is not None:
                repository.close()