"""Coordinate AI index writers for one database."""
from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Self

from PySide6.QtCore import QLockFile

from ..config import database_data_dir


class AiIndexWriteLock:
    """Prevent AI scans, backend switches, and password changes from overlapping."""

    def __init__(self, db_path: Path) -> None:
        directory = database_data_dir(db_path)
        directory.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(directory / ".ai-index-write.lock"))
        self._lock.setStaleLockTime(0)

    def __enter__(self) -> Self:
        if not self._lock.tryLock(0):
            raise RuntimeError("Another AI index operation is already running")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._lock.unlock()
