from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from ..utils.vec1_extension import bundled_vec1_extension
from .ai_index_revision import AiIndexRevision
from .ai_vec1_repository import AiVec1Repository
from .ai_vector_backend import AiVectorBackend, AiVectorIndexError


class AiSearchSession:
    """Serialize local searches and reject results from a changed AI index."""

    def __init__(
        self, db_path: Path, *, extension_resolver: Callable[[], Path] | None = None
    ) -> None:
        self._db_path = db_path
        self._extension_resolver = extension_resolver
        self._lock = RLock()
        self._closed = False

    def disk_generation(self) -> tuple[tuple[int, int, int, int] | None, ...]:
        """Return the database and WAL file identities for cached hybrid results."""
        generation: list[tuple[int, int, int, int] | None] = []
        for path in (self._db_path, self._db_path.with_name(self._db_path.name + "-wal")):
            try:
                stat = path.stat()
            except FileNotFoundError:
                generation.append(None)
            else:
                generation.append((stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        return tuple(generation)

    @contextmanager
    def repository(self, key: str) -> Generator[AiVectorBackend]:
        with self._lock:
            if self._closed:
                raise RuntimeError("AI search session is closed")
            resolver = self._extension_resolver or bundled_vec1_extension
            candidate = AiVec1Repository(self._db_path, key, resolver())
            candidate.load()
            try:
                revision = AiIndexRevision(self._db_path, key)
                state = revision.state()
                yield candidate
                if revision.state() != state:
                    raise AiVectorIndexError("AI index changed during search; retry the search")
            finally:
                candidate.close()

    def invalidate(self) -> None:
        """Wait for any active lease to finish."""
        with self._lock:
            pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
