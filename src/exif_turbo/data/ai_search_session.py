from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from .ai_vector_repository import AiVectorIndexError, AiVectorRepository


class AiSearchSession:
    """Own one validated search snapshot; scans publish separate repositories."""

    def __init__(
        self, index_path: Path, map_path: Path, metadata_path: Path,
        *, repository_factory: Callable[..., AiVectorRepository] = AiVectorRepository,
    ) -> None:
        self._paths = (index_path, map_path, metadata_path)
        self._factory = repository_factory
        self._lock = RLock()
        self._repository: AiVectorRepository | None = None
        self._generation: tuple[tuple[int, int, int, int] | None, ...] | None = None
        self._key = ""
        self._closed = False

    def _disk_generation(self) -> tuple[tuple[int, int, int, int] | None, ...]:
        index_path = self._paths[0]
        encrypted_path = index_path.with_name(index_path.name + ".enc")
        key_dir = index_path.with_name(index_path.name + ".keys")
        paths = (*self._paths, encrypted_path, key_dir / ".thumb_key", key_dir / "password.pending")
        generation: list[tuple[int, int, int, int] | None] = []
        for path in paths:
            try:
                stat = path.stat()
            except FileNotFoundError:
                generation.append(None)
            else:
                generation.append((stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        return tuple(generation)

    @contextmanager
    def repository(self, key: str) -> Iterator[AiVectorRepository]:
        """Lease a read-only snapshot, serializing load/search against close."""
        with self._lock:
            if self._closed:
                raise RuntimeError("AI search session is closed")
            generation = self._disk_generation()
            if self._repository is None or self._generation != generation or self._key != key:
                self._repository = None
                self._generation = None
                self._key = ""
                candidate = self._factory(*self._paths, key=key)
                candidate.load()
                loaded_generation = self._disk_generation()
                if loaded_generation != generation:
                    candidate = self._factory(*self._paths, key=key)
                    candidate.load()
                    if self._disk_generation() != loaded_generation:
                        raise AiVectorIndexError("AI index changed while loading; retry the search")
                self._repository = candidate
                self._generation = loaded_generation
                self._key = key
            yield self._repository

    def invalidate(self) -> None:
        with self._lock:
            self._repository = None
            self._generation = None
            self._key = ""

    def close(self) -> None:
        with self._lock:
            self.invalidate()
            self._closed = True