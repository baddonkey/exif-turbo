"""Background training for the experimental encrypted Vec1 index."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...data.ai_vec1_repository import AiVec1Repository, AiVec1TrainingCanceled


class Vec1TrainingWorker(QThread):
    """Train a Vec1 index without blocking the GUI thread."""

    progress = Signal(str)
    completed = Signal()
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
        repository = AiVec1Repository(self._db_path, self._key, self._extension_path)
        try:
            repository.load()
            repository.train_index(
                cancel_check=self.isInterruptionRequested,
                on_progress=self.progress.emit,
            )
            self.completed.emit()
        except AiVec1TrainingCanceled:
            self.canceled.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            repository.close()
            self._key = ""
