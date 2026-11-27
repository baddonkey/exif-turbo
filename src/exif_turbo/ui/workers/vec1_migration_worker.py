"""Stage authenticated FAISS vectors in the encrypted metadata database."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...config import ai_id_map_path, ai_index_path, ai_vector_metadata_path
from ...data.ai_search_session import AiSearchSession
from ...data.ai_vec1_repository import AiVec1MigrationCanceled, AiVec1Repository
from ...data.ai_vector_repository import AiVectorIndexError, AiVectorRepository


class Vec1MigrationWorker(QThread):
    """Stage a stable authenticated snapshot without activating it."""

    progress = Signal(int, int)
    completed = Signal(object)
    canceled = Signal()
    failed = Signal(str)

    def __init__(self, db_path: Path, key: str, extension_path: Path) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._extension_path = extension_path

    def cancel(self) -> None:
        self.requestInterruption()

    def run(self) -> None:
        index_path = ai_index_path(self._db_path)
        map_path = ai_id_map_path(self._db_path)
        metadata_path = ai_vector_metadata_path(self._db_path)
        session = AiSearchSession(index_path, map_path, metadata_path)
        source = AiVectorRepository(index_path, map_path, metadata_path, key=self._key)
        target = AiVec1Repository(self._db_path, self._key, self._extension_path)
        try:
            generation = session.disk_generation()
            source.load_migration_source()
            if session.disk_generation() != generation:
                raise AiVectorIndexError("The AI snapshot changed while loading")
            if self.isInterruptionRequested():
                raise AiVec1MigrationCanceled("AI vector staging canceled")
            target.load()
            target.stage_faiss_snapshot(
                source,
                cancel_check=self.isInterruptionRequested,
                source_is_current=lambda: session.disk_generation() == generation,
                on_progress=self.progress.emit,
            )
            target.close()
            target.load()
            result = target.verify_staged_snapshot(
                source,
                cancel_check=self.isInterruptionRequested,
                source_is_current=lambda: session.disk_generation() == generation,
            )
            self.completed.emit(result)
        except AiVec1MigrationCanceled:
            self.canceled.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            source.close()
            target.close()
            session.close()
            self._key = ""
