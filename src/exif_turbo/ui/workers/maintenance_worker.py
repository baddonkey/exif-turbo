"""Background worker for long-running database-maintenance operations.

Removing a large indexed folder or resetting the whole database can take a
noticeable amount of time (preview-cache file deletes, orphan-row purges and
a VACUUM that reclaims disk space).  Running them on the GUI thread would
freeze the window, so this worker performs the heavy lifting on its own
SQLite connections and reports progress back to :class:`AppController`, which
drives the shared busy overlay.

Progress is *determinate* for the cache-clearing phase (the number of files
is known up front) and *indeterminate* for the database phases, where the
work happens inside single atomic SQL statements that cannot report partial
progress.  The VACUUM step is explicitly flagged non-cancelable.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...data.indexed_folder_repository import IndexedFolderRepository
from ...config import bundled_vocabulary_path, tgm_snapshot_path
from ...i18n import _
from ...tagging.sidecar_synchronizer import SidecarSynchronizer
from ...tagging.tgm_snapshot_repository import TgmSnapshotRepository
from ...tagging.vocabulary_snapshot_repository import VocabularySnapshotRepository
from ...utils.preview_cache import expected_preview_filenames, preview_dir
from ._macos_activity import AppNapAssertion


class MaintenanceWorker(QThread):
    """Run database maintenance operations off the GUI thread.

    Emits:
        progress(done, total, message): ``total == 0`` requests an
            indeterminate spinner; ``message`` is a localised sub-step label.
        cancelable(flag): whether the *current* step may be safely canceled.
        finished(): the operation completed.
        failed(message): an unexpected error aborted the operation.
        canceled(): the user canceled during a safe step.
    """

    progress = Signal(int, int, str)   # (done, total, message)
    cancelable = Signal(bool)
    finished = Signal()
    failed = Signal(str)
    canceled = Signal()

    def __init__(
        self,
        db_path: Path,
        key: str,
        operation: str,
        *,
        folder_id: int | None = None,
        folder_path: str | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._operation = operation
        self._folder_id = folder_id
        self._folder_path = folder_path
        self._cache_dir = cache_dir
        self._cancel_event = threading.Event()
        self._last_emit = 0.0
        self.sidecar_image_count = 0
        self.sidecar_error_count = 0

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        self._cancel_event.set()

    def _is_canceled(self) -> bool:
        return self._cancel_event.is_set()

    def _emit_progress(
        self, done: int, total: int, message: str, *, force: bool = False
    ) -> None:
        """Throttle progress emits to ~20 Hz to keep the event loop free."""
        now = time.monotonic()
        if force or done >= total or now - self._last_emit >= 0.05:
            self._last_emit = now
            self.progress.emit(done, total, message)

    # ------------------------------------------------------------------
    def run(self) -> None:
        nap = AppNapAssertion("Database maintenance")
        try:
            if self._operation == "remove_folder":
                self._run_remove_folder()
            elif self._operation == "reset_database":
                self._run_reset_database()
            elif self._operation == "refresh_sidecars":
                self._run_refresh_sidecars()
            else:
                self.failed.emit(f"Unknown operation: {self._operation!r}")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            nap.release()

    # ------------------------------------------------------------------
    def _run_remove_folder(self) -> None:
        if self._folder_id is None or self._folder_path is None:
            self.failed.emit("folder_id and folder_path are required")
            return

        repo = ImageIndexRepository(self._db_path, key=self._key)
        folder_repo = IndexedFolderRepository(self._db_path, key=self._key)
        try:
            # Phase 1 — clear this folder's cached previews (safe to cancel).
            self.cancelable.emit(True)
            self._emit_progress(0, 0, _("Clearing preview cache\u2026"), force=True)
            if self._cache_dir is not None:
                stamps = repo.get_folder_stamps(self._folder_id)
                if self._clear_previews(stamps) is False:
                    self.canceled.emit()
                    return

            # Phase 2 — purge index rows (atomic; cannot be canceled).
            self.cancelable.emit(False)
            self._emit_progress(0, 0, _("Deleting index entries\u2026"), force=True)
            repo.delete_folder_associations(self._folder_id)
            repo.delete_orphans_under_prefix(self._folder_path)
            folder_repo.remove(self._folder_id)

            self.finished.emit()
        finally:
            repo.close()
            folder_repo.close()

    def _run_reset_database(self) -> None:
        repo = ImageIndexRepository(self._db_path, key=self._key)
        folder_repo = IndexedFolderRepository(self._db_path, key=self._key)
        try:
            # Phase 1 — wipe the whole on-disk cache (safe to cancel).
            self.cancelable.emit(True)
            self._emit_progress(0, 0, _("Clearing preview cache\u2026"), force=True)
            if self._cache_dir is not None:
                if self._wipe_cache_dir() is False:
                    self.canceled.emit()
                    return

            # Phase 2 — delete every index row (atomic; cannot be canceled).
            self.cancelable.emit(False)
            self._emit_progress(0, 0, _("Deleting index rows\u2026"), force=True)
            repo.clear_all_rows()
            folder_repo.clear_all()
            shutil.rmtree(tgm_snapshot_path(self._db_path).parent, ignore_errors=True)

            # Phase 3 — reclaim disk space (cannot be canceled).
            self._emit_progress(0, 0, _("Vacuuming database\u2026"), force=True)
            repo.vacuum()

            self.finished.emit()
        finally:
            repo.close()
            folder_repo.close()

    def _run_refresh_sidecars(self) -> None:
        if self._folder_id is None:
            self.failed.emit("folder_id is required")
            return
        repo = ImageIndexRepository(self._db_path, key=self._key)
        try:
            image_paths = tuple(repo.get_folder_stamps(self._folder_id))
            total = len(image_paths)
            self.sidecar_image_count = total
            message = _("Re-reading sidecar tags\u2026")
            self.cancelable.emit(True)
            self._emit_progress(0, total, message, force=True)

            def on_progress(done: int, count: int, _path: str) -> None:
                self._emit_progress(done, count, message)

            legacy_snapshot_path = tgm_snapshot_path(self._db_path)
            result = SidecarSynchronizer(
                repo,
                vocabulary_repository=VocabularySnapshotRepository(
                    bundled_vocabulary_path()
                ),
                tgm_repository=(
                    TgmSnapshotRepository(legacy_snapshot_path)
                    if legacy_snapshot_path.exists()
                    else None
                ),
            ).synchronize(
                image_paths,
                cancel_check=self._is_canceled,
                on_progress=on_progress,
                force=True,
            )
            self.sidecar_error_count = result.error_count
            if result.canceled:
                self.canceled.emit()
            else:
                self._emit_progress(total, total, message, force=True)
                self.finished.emit()
        finally:
            repo.close()

    # ------------------------------------------------------------------
    def _clear_previews(self, stamps: dict[str, tuple[float, int]]) -> bool:
        """Delete cached previews for *stamps*.  Returns ``False`` if canceled."""
        assert self._cache_dir is not None
        names = sorted(
            expected_preview_filenames(stamps, encrypted=bool(self._key))
        )
        total = len(names)
        pdir = preview_dir(self._cache_dir)
        message = _("Clearing preview cache\u2026")
        for i, name in enumerate(names):
            if self._is_canceled():
                return False
            try:
                (pdir / name).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
            self._emit_progress(i + 1, total, message)
        self._emit_progress(total, total, message, force=True)
        return True

    def _wipe_cache_dir(self) -> bool:
        """Delete every file under the cache dir.  Returns ``False`` if canceled."""
        assert self._cache_dir is not None
        files: list[str] = []
        for root, _dirs, names in os.walk(self._cache_dir):
            for name in names:
                files.append(os.path.join(root, name))
        total = len(files)
        message = _("Clearing preview cache\u2026")
        self._emit_progress(0, total, message, force=True)
        for i, fpath in enumerate(files):
            if self._is_canceled():
                return False
            try:
                os.unlink(fpath)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            self._emit_progress(i + 1, total, message)
        # Drop now-empty preview subdirectory so the tree stays tidy; the cache
        # root itself is left in place (and recreated by the controller).
        pdir = preview_dir(self._cache_dir)
        try:
            pdir.rmdir()
        except OSError:
            pass
        self._emit_progress(total, total, message, force=True)
        return True
