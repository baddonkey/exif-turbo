"""Background worker that builds the CLIP vector index for a single folder."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...config import thumb_cache_dir
from ...data.ai_vec1_repository import AiVec1Repository
from ...data.ai_vector_backend import AiVectorBackend
from ...data.image_index_repository import ImageIndexRepository
from ...indexing.ai_indexer_service import AiIndexerService, image_paths_for_folder
from ...utils.ai_index_write_lock import AiIndexWriteLock
from ...utils.vec1_extension import bundled_vec1_extension


class AiScanWorker(QThread):
    """Encode all images in a folder with CLIP and persist to the active AI index.

    Signals mirror those of IndexWorker for consistency:
      finished(indexed_count, error_count)
      failed(error_message)
      progress(done, total, current_path)
      canceled(indexed_count)
    """

    finished = Signal(int, int)   # (indexed_count, error_count)
    failed = Signal(str)
    progress = Signal(int, int, str)
    canceled = Signal(int)

    def __init__(
        self,
        db_path: Path,
        folder_id: int,
        folder_path: str,
        key: str = "",
        *,
        force_rebuild: bool = False,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._folder_id = folder_id
        self._folder_path = folder_path
        self._key = key
        self._force_rebuild = force_rebuild
        self._cancel_event = threading.Event()
        # macOS limits secondary thread stacks to 512 kB by default, which is
        # too small for the lazy torch + open_clip imports.  64 MB gives ample
        # headroom without measurable overhead.
        self.setStackSize(64 * 1024 * 1024)

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            with AiIndexWriteLock(self._db_path):
                self._run_locked()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self._key = ""

    def _run_locked(self) -> None:
        vector_repo: AiVectorBackend | None = None
        try:
            # 1. Collect image paths for the folder from the regular index DB.
            repo = ImageIndexRepository(self._db_path, key=self._key)
            stamps = repo.get_folder_stamps(self._folder_id)
            repo.close()
            image_paths = image_paths_for_folder(stamps)

            if self._cancel_event.is_set():
                self.canceled.emit(0)
                return
            if not image_paths:
                self.finished.emit(0, 0)
                return

            # 2. Load (or create) the active AI index.
            vector_repo = AiVec1Repository(
                self._db_path, self._key, bundled_vec1_extension(),
            )
            vector_repo.load()
            if self._force_rebuild:
                vector_repo.remove_folder(self._folder_path)

            # 3. Run the CLIP encoder.
            service = AiIndexerService(
                vector_repo,
                preview_cache_dir=thumb_cache_dir(self._db_path),
                preview_cache_key=self._key,
            )
            indexed_count = 0

            def _on_progress(done: int, total: int, path: str) -> None:
                nonlocal indexed_count
                indexed_count = done
                self.progress.emit(done, total, path)

            indexed, errors = service.build_index(
                image_paths,
                stamps=stamps,
                on_progress=_on_progress,
                cancel_check=lambda: self._cancel_event.is_set(),
            )

            # 4. Persist regardless of cancel so partial work is not lost.
            vector_repo.save()
            vector_repo.close()
            vector_repo = None

            if self._cancel_event.is_set():
                self.canceled.emit(indexed)
            else:
                self.finished.emit(indexed, errors)

        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if vector_repo is not None:
                vector_repo.close()
            self._key = ""
