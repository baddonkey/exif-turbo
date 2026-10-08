from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, QUrl, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...data.indexed_folder_repository import IndexedFolderRepository
from ...i18n import _
from ...tagging.derivative_export_service import merge_keyword_labels
from ...tagging.sidecar_repository import FilesystemSidecarRepository
from ...tagging.tagging_service import TaggingService
from ..models.embedded_tag_list_model import EmbeddedTagListModel
from ..models.free_tag_list_model import FreeTagListModel
from ..models.settings_model import SettingsModel
from ..workers.copy_tags_worker import CopyTagsWorker
from ..workers.derivative_export_worker import DerivativeExportWorker


class TaggingController(QObject):
    taggingStateChanged = Signal()
    bulkTagOperationChanged = Signal()
    derivativeOperationChanged = Signal()

    def __init__(
        self,
        *,
        db_path: Path,
        settings: SettingsModel | None,
        get_key: Callable[[], str],
        is_locked: Callable[[], bool],
        get_repository: Callable[[], ImageIndexRepository | None],
        get_folder_repository: Callable[[], IndexedFolderRepository | None],
        selected_path: Callable[[], str | None],
        refresh_after_mutation: Callable[[], None],
        copy_worker_factory: Callable[..., CopyTagsWorker] = CopyTagsWorker,
        derivative_worker_factory: Callable[..., DerivativeExportWorker] = DerivativeExportWorker,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._settings = settings
        self._get_key = get_key
        self._is_locked = is_locked
        self._get_repository = get_repository
        self._get_folder_repository = get_folder_repository
        self._selected_path = selected_path
        self._refresh_after_mutation = refresh_after_mutation
        self._copy_worker_factory = copy_worker_factory
        self._derivative_worker_factory = derivative_worker_factory
        self._service: TaggingService | None = None
        self.embedded_tags_model = EmbeddedTagListModel()
        self.derivative_tags_model = FreeTagListModel()
        self.free_tags_model = FreeTagListModel()
        self.free_tag_suggestions_model = FreeTagListModel()
        self._embedded_tags: tuple[str, ...] = ()
        self._excluded_embedded_tags: tuple[str, ...] = ()
        self._exclude_all_embedded_tags = False
        self._selected_error = ""
        self._bulk_operation = False
        self._bulk_progress = (0, 0)
        self._bulk_summary = ""
        self._derivative_operation = False
        self._derivative_progress = (0, 0)
        self._derivative_summary = ""
        self._copy_worker: CopyTagsWorker | None = None
        self._derivative_worker: DerivativeExportWorker | None = None

    @property
    def tagging_enabled(self) -> bool:
        return self._settings.tagging_enabled if self._settings else False

    @property
    def free_tagging_available(self) -> bool:
        return self.tagging_enabled and not self._is_locked()

    @property
    def exclude_all_embedded_tags(self) -> bool:
        return self._exclude_all_embedded_tags

    @property
    def selected_error(self) -> str:
        return self._selected_error

    @property
    def is_bulk_operation(self) -> bool:
        return self._bulk_operation

    @property
    def bulk_progress(self) -> tuple[int, int]:
        return self._bulk_progress

    @property
    def bulk_summary(self) -> str:
        return self._bulk_summary

    @property
    def is_derivative_operation(self) -> bool:
        return self._derivative_operation

    @property
    def derivative_progress(self) -> tuple[int, int]:
        return self._derivative_progress

    @property
    def derivative_summary(self) -> str:
        return self._derivative_summary

    @property
    def workers(self) -> tuple[QThread | None, QThread | None]:
        return self._copy_worker, self._derivative_worker

    def initialize(self, repository: ImageIndexRepository | None) -> None:
        if repository is not None:
            self._service = TaggingService(repository, FilesystemSidecarRepository())

    def clear(self) -> None:
        self.cancel_workers(wait=True)
        self._service = None
        self.free_tags_model.set_rows([])
        self.free_tag_suggestions_model.set_rows([])
        self.embedded_tags_model.set_rows([])
        self.derivative_tags_model.set_rows([])
        self._embedded_tags = ()
        self._excluded_embedded_tags = ()
        self._exclude_all_embedded_tags = False
        self._selected_error = ""
        self.taggingStateChanged.emit()

    def close(self) -> None:
        self.cancel_workers(wait=True)
        self._copy_worker = None
        self._derivative_worker = None
        self._service = None

    def set_enabled(self, enabled: bool) -> None:
        if self._settings is not None:
            self._settings.setTaggingEnabled(enabled)
            self.taggingStateChanged.emit()

    def set_embedded_tags(self, labels: tuple[str, ...]) -> None:
        self._embedded_tags = labels
        self._refresh_embedded_tag_rows()
        self.derivative_tags_model.set_rows(labels)

    def clear_embedded_tags(self) -> None:
        self._embedded_tags = ()
        self._excluded_embedded_tags = ()
        self._exclude_all_embedded_tags = False
        self.embedded_tags_model.set_rows([])
        self.derivative_tags_model.set_rows([])

    def search_free_tags(self, query: str) -> None:
        repository = self._get_repository()
        if repository is None or not self.free_tagging_available:
            self.free_tag_suggestions_model.set_rows([])
            return
        try:
            path = self._selected_path()
            assigned = {
                tag.casefold()
                for tag in (() if path is None else repository.get_free_tags(path))
            }
            self.free_tag_suggestions_model.set_rows(
                tag
                for tag in repository.search_free_tags(query)
                if tag.casefold() not in assigned
            )
            self._selected_error = ""
        except Exception as exc:  # noqa: BLE001
            self.free_tag_suggestions_model.set_rows([])
            self._selected_error = str(exc)
        self.taggingStateChanged.emit()

    def refresh_selected_state(self) -> None:
        path = self._selected_path()
        if not path or self._service is None:
            self.free_tags_model.set_rows([])
            self._excluded_embedded_tags = ()
            self._exclude_all_embedded_tags = False
            self._refresh_embedded_tag_rows()
            self.derivative_tags_model.set_rows(self._embedded_tags if path else ())
            return
        try:
            state = self._service.get_image_tagging_state(path)
            self.free_tags_model.set_rows(state.free_tags)
            sidecar = state.sidecar
            self._excluded_embedded_tags = (
                () if sidecar is None else sidecar.excluded_embedded_tags
            )
            self._exclude_all_embedded_tags = (
                False if sidecar is None else sidecar.exclude_all_embedded_tags
            )
            self._refresh_embedded_tag_rows()
            self.derivative_tags_model.set_rows(
                merge_keyword_labels(
                    (), state.free_tags, self._included_embedded_tags()
                )
            )
            self._selected_error = ""
        except Exception as exc:  # noqa: BLE001
            self.free_tags_model.set_rows([])
            self.derivative_tags_model.set_rows(self._included_embedded_tags())
            self._selected_error = str(exc)
        self.taggingStateChanged.emit()

    def set_embedded_tag_excluded(self, label: str, excluded: bool) -> None:
        path = self._selected_path()
        if path is None or self._service is None or not self.free_tagging_available:
            return
        try:
            self._service.set_embedded_tag_excluded(path, label, excluded)
            self._selected_error = ""
            self.refresh_selected_state()
        except Exception as exc:  # noqa: BLE001
            self._selected_error = str(exc)
            self.taggingStateChanged.emit()

    def set_all_embedded_tags_excluded(self, excluded: bool) -> None:
        path = self._selected_path()
        if path is None or self._service is None or not self.free_tagging_available:
            return
        try:
            self._service.set_all_embedded_tags_excluded(path, excluded)
            self._selected_error = ""
            self.refresh_selected_state()
        except Exception as exc:  # noqa: BLE001
            self._selected_error = str(exc)
            self.taggingStateChanged.emit()

    def mutate_selected_free_tag(self, label: str, *, remove: bool) -> None:
        if not self.free_tagging_available:
            return
        path = self._selected_path()
        if path is None or self._service is None:
            return
        try:
            if remove:
                self._service.remove_free_tag(path, label)
            else:
                self._service.add_free_tag(path, label)
            self._selected_error = ""
            self._refresh_after_mutation()
            self.search_free_tags("")
        except Exception as exc:  # noqa: BLE001
            self._selected_error = str(exc)
            self.taggingStateChanged.emit()

    def can_copy_tags(self, source_path: str | None) -> bool:
        return (
            source_path is not None
            and self.free_tagging_available
            and self._get_repository() is not None
            and self._copy_worker is None
        )

    def show_copy_error(self, message: str) -> None:
        self._bulk_summary = message
        self.bulkTagOperationChanged.emit()

    def copy_selected_tags(
        self,
        source_path: str,
        mode: str,
        worker_options: dict[str, object],
    ) -> None:
        if not self.can_copy_tags(source_path):
            return
        worker = self._copy_worker_factory(
            self._db_path,
            self._get_key(),
            source_path,
            mode,
            **worker_options,
        )
        self._copy_worker = worker
        worker.progress.connect(self._on_bulk_progress)
        worker.result_ready.connect(self._on_bulk_result)
        worker.failed.connect(self._on_bulk_failed)
        worker.canceled.connect(self._on_bulk_result)
        worker.finished.connect(lambda: self._release_worker("_copy_worker", worker))
        self._bulk_operation = True
        self._bulk_progress = (0, 0)
        self._bulk_summary = ""
        self.bulkTagOperationChanged.emit()
        worker.start()

    def _on_bulk_progress(self, done: int, total: int, _item: object) -> None:
        self._bulk_progress = (done, total)
        self.bulkTagOperationChanged.emit()

    def _on_bulk_result(self, result: object) -> None:
        self._bulk_operation = False
        changed_count = getattr(result, "succeeded_count", 0)
        unchanged_count = getattr(result, "skipped_count", 0)
        problem_count = (
            getattr(result, "conflicted_count", 0)
            + getattr(result, "failed_count", 0)
        )
        summary = _("Copied tags to {} image(s). Unchanged: {}. Problems: {}.").format(
            changed_count, unchanged_count, problem_count
        )
        if getattr(result, "cancelled", False):
            summary = _("Canceled. {}").format(summary)
        self._bulk_summary = summary.strip()
        self._refresh_after_mutation()
        self.bulkTagOperationChanged.emit()

    def _on_bulk_failed(self, error: str) -> None:
        self._bulk_operation = False
        self._bulk_summary = error
        self.bulkTagOperationChanged.emit()

    def cancel_bulk_tagging(self) -> None:
        if self._copy_worker is not None:
            self._copy_worker.cancel()

    def start_derivative_export(
        self,
        output_url: str,
        **worker_options: object,
    ) -> None:
        folder_repository = self._get_folder_repository()
        if (
            not self.free_tagging_available
            or folder_repository is None
            or self._derivative_worker is not None
        ):
            return
        output_root = Path(QUrl(output_url).toLocalFile())
        roots = {
            Path(folder.path): folder.display_name
            for folder in folder_repository.get_all()
        }
        worker = self._derivative_worker_factory(
            self._db_path,
            self._get_key(),
            roots,
            output_root,
            **worker_options,
        )
        self._derivative_worker = worker
        worker.progress.connect(self._on_derivative_progress)
        worker.result_ready.connect(self.handle_derivative_result)
        worker.canceled.connect(self.handle_derivative_result)
        worker.failed.connect(self._on_derivative_failed)
        worker.finished.connect(
            lambda: self._release_worker("_derivative_worker", worker)
        )
        self._derivative_operation = True
        self._derivative_summary = ""
        self.derivativeOperationChanged.emit()
        worker.start()

    def _on_derivative_progress(self, done: int, total: int, _item: object) -> None:
        self._derivative_progress = (done, total)
        self.derivativeOperationChanged.emit()

    def handle_derivative_result(self, result: object) -> None:
        self._derivative_operation = False
        copied_count = getattr(result, "copied_count", 0)
        untagged_count = getattr(result, "skipped_untagged_count", 0)
        existing_count = getattr(result, "skipped_existing_count", 0)
        failed_count = getattr(result, "failed_count", 0)
        canceled_count = getattr(result, "canceled_count", 0)
        items = getattr(result, "items", ())
        copied_destinations = [
            str(item.destination)
            for item in items
            if getattr(getattr(item, "status", None), "value", None) == "copied"
        ]
        parts = []
        if copied_count == 1 and copied_destinations:
            parts.append(_("Created derivative: {}").format(copied_destinations[0]))
        elif copied_count == 1:
            parts.append(_("Created 1 derivative."))
        elif copied_count and copied_destinations:
            common_destination = os.path.commonpath(copied_destinations)
            parts.append(
                _("Created {} derivatives in {}.").format(
                    copied_count, common_destination
                )
            )
        elif copied_count:
            parts.append(_("Created {} derivatives.").format(copied_count))
        else:
            parts.append(_("No derivatives were created."))
        if untagged_count:
            parts.append(_("{} image(s) had no tags.").format(untagged_count))
        if existing_count:
            parts.append(_("{} destination file(s) already existed.").format(existing_count))
        if failed_count:
            parts.append(_("{} derivative(s) failed.").format(failed_count))
            failed_item = next(
                (
                    item
                    for item in items
                    if getattr(getattr(item, "status", None), "value", None)
                    == "failed"
                ),
                None,
            )
            if failed_item is not None:
                source_name = Path(str(getattr(failed_item, "source", ""))).name
                detail = str(getattr(failed_item, "message", "") or "unknown error")
                parts.append(_("First failure ({}): {}").format(source_name, detail))
        if canceled_count:
            parts.append(_("{} derivative(s) canceled.").format(canceled_count))
        self._derivative_summary = " ".join(parts)
        self.derivativeOperationChanged.emit()

    def _on_derivative_failed(self, error: str) -> None:
        self._derivative_operation = False
        self._derivative_summary = error
        self.derivativeOperationChanged.emit()

    def cancel_derivative_export(self) -> None:
        if self._derivative_worker is not None:
            self._derivative_worker.cancel()

    def cancel_workers(self, *, wait: bool) -> None:
        for worker in self.workers:
            if worker is not None and worker.isRunning():
                worker.cancel()
                if wait:
                    worker.wait(5000)

    def release_workers(self) -> None:
        self._copy_worker = None
        self._derivative_worker = None

    def _release_worker(self, attribute: str, worker: QThread) -> None:
        if getattr(self, attribute) is worker:
            setattr(self, attribute, None)

    def _included_embedded_tags(self) -> tuple[str, ...]:
        if self._exclude_all_embedded_tags:
            return ()
        excluded_keys = {label.casefold() for label in self._excluded_embedded_tags}
        return tuple(
            label for label in self._embedded_tags if label.casefold() not in excluded_keys
        )

    def _refresh_embedded_tag_rows(self) -> None:
        excluded_keys = {label.casefold() for label in self._excluded_embedded_tags}
        self.embedded_tags_model.set_rows(
            (label, label.casefold() in excluded_keys) for label in self._embedded_tags
        )