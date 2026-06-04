"""Background worker that builds the CLIP vector index for a single folder."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...config import ai_id_map_path, ai_index_path, thumb_cache_dir
from ...data.ai_vector_repository import AiVectorRepository
from ...data.image_index_repository import ImageIndexRepository
from ...indexing.ai_indexer_service import AiIndexerService, image_paths_for_folder


class AiScanWorker(QThread):
    """Encode all images in a folder with CLIP and persist to the FAISS index.

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

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            # 1. Collect image paths for the folder from the regular index DB.
            repo = ImageIndexRepository(self._db_path, key=self._key)
            stamps = repo.get_folder_stamps(self._folder_id)
            repo.close()
            image_paths = image_paths_for_folder(stamps)

            if not image_paths or self._cancel_event.is_set():
                self.canceled.emit(0)
                return

            # 2. Load (or create) the FAISS index.
            idx_path = ai_index_path(self._db_path)
            map_path = ai_id_map_path(self._db_path)
            vector_repo = AiVectorRepository(idx_path, map_path)
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

            if self._cancel_event.is_set():
                self.canceled.emit(indexed)
            else:
                self.finished.emit(indexed, errors)

        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
