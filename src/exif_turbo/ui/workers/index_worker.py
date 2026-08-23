from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ...config import bundled_vocabulary_path, tgm_snapshot_path, thumb_cache_dir
from ...data.image_index_repository import ImageIndexRepository
from ...indexing.image_finder import ImageFinder
from ...indexing.indexer_service import IndexerService
from ...tagging.sidecar_synchronizer import SidecarSynchronizer
from ...tagging.tgm_snapshot_repository import TgmSnapshotRepository
from ...tagging.vocabulary_snapshot_repository import VocabularySnapshotRepository
from ...utils.preview_cache import preview_dir
from ._macos_activity import AppNapAssertion


class IndexWorker(QThread):
    finished = Signal(int, int)   # (indexed_count, error_count)
    failed = Signal(str)
    progress = Signal(int, int, str)
    canceled = Signal(int)

    def __init__(
        self,
        db_path: Path,
        folders: List[Path],
        workers: int = 12,
        key: str = "",
        force: bool = False,
        clear_cache_dir: Path | None = None,
        blacklist: List[str] | None = None,
        folder_id: int | None = None,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.folders = folders
        self.workers = max(1, workers)
        self._key = key
        self._force = force
        self._clear_cache_dir = clear_cache_dir
        self._blacklist: List[str] = list(blacklist) if blacklist else []
        self._folder_id = folder_id
        self._cancel_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()  # starts unpaused

    def cancel(self) -> None:
        self._cancel_event.set()
        self._resume_event.set()  # unblock any thread waiting in pause

    def pause(self) -> None:
        """Temporarily suspend indexing I/O to yield bandwidth to the preview."""
        self._resume_event.clear()

    def resume(self) -> None:
        """Resume indexing after a preview has had time to load."""
        self._resume_event.set()

    def _cancel_or_pause(self) -> bool:
        """cancel_check callable: blocks while paused, then returns the canceled state."""
        if not self._resume_event.is_set():
            self._resume_event.wait(timeout=2.0)
        return self._cancel_event.is_set()

    def run(self) -> None:
        _nap = AppNapAssertion("Indexing images")
        try:
            if self._clear_cache_dir is not None:
                if self._clear_cache_dir.exists():
                    shutil.rmtree(self._clear_cache_dir, ignore_errors=True)
                self._clear_cache_dir.mkdir(parents=True, exist_ok=True)
            repo = ImageIndexRepository(self.db_path, key=self._key)
            finder = ImageFinder(blacklist=self._blacklist)
            legacy_snapshot_path = tgm_snapshot_path(self.db_path)
            indexer = IndexerService(
                repo,
                finder=finder,
                sidecar_synchronizer=SidecarSynchronizer(
                    repo,
                    vocabulary_repository=VocabularySnapshotRepository(
                        bundled_vocabulary_path()
                    ),
                    tgm_repository=(
                        TgmSnapshotRepository(legacy_snapshot_path)
                        if legacy_snapshot_path.exists()
                        else None
                    ),
                ),
            )
            _last_emit: list[float] = [0.0]  # mutable cell for the closure

            def _on_progress(current: int, total: int, p: Path) -> None:
                now = time.monotonic()
                # Emit at most ~20 Hz; always emit the final update.
                # This prevents flooding Qt's cross-thread signal queue and
                # keeps the GUI event loop free to handle user input.
                if now - _last_emit[0] >= 0.05 or current == total:
                    _last_emit[0] = now
                    self.progress.emit(current, total, str(p))

            count, error_count = indexer.build_index(
                self.folders,
                None,
                on_progress=_on_progress,
                workers=self.workers,
                cancel_check=self._cancel_or_pause,
                force=self._force,
                folder_id=self._folder_id,
            )
            # Cache GC: remove orphaned thumb/preview files that no longer
            # correspond to any DB row.  Self-heals after crashes, file moves
            # and external deletions.  Skipped on cancel and on the cache-clear
            # path (which already wiped everything itself).
            if not self._cancel_event.is_set() and self._clear_cache_dir is None:
                # Sentinel progress emit (-1, -1, "") tells the controller to
                # show a translated "Cleaning up cache…" status.
                self.progress.emit(-1, -1, "")
                self._gc_orphaned_cache(repo)
            repo.close()
            if self._cancel_event.is_set():
                self.canceled.emit(count)
            else:
                self.finished.emit(count, error_count)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            _nap.release()

    def _gc_orphaned_cache(self, repo: ImageIndexRepository) -> None:
        """Delete cache files whose SHA-1 prefix isn't present in the DB.

        The on-disk filename is ``SHA1(path|mtime|size)`` followed by one of
        ``.png``, ``.enc``, ``.skip`` (thumbs) or ``.jpg``, ``.jpg.enc``
        (previews).  Anything in the cache directory whose 40-char SHA-1
        prefix isn't present in the current DB stamp set is an orphan and
        gets unlinked.
        """
        try:
            cache_dir = thumb_cache_dir(self.db_path)
            stamps = repo.get_all_stamps()
        except Exception:
            return
        # Build the expected SHA-1 set from current DB stamps.
        expected: set[str] = set()
        for ipath, (mtime, size) in stamps.items():
            key = f"{ipath}|{mtime}|{size}"
            expected.add(
                hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()
            )
        for directory in (cache_dir, preview_dir(cache_dir)):
            self._purge_orphans(directory, expected)

    @staticmethod
    def _purge_orphans(directory: Path, expected: set[str]) -> None:
        """Unlink every file in *directory* whose 40-char prefix isn't expected."""
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    name = entry.name
                    if len(name) <= 40 or name[:40] in expected:
                        continue
                    try:
                        os.unlink(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass

