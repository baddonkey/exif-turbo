from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import numpy as np
import pytest

from exif_turbo.data.ai_search_session import AiSearchSession
from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.data.ai_vector_storage import AiVectorAuthenticationError, AiVectorStorage


class _RepositoryFactory:
    def __init__(self) -> None:
        self.created = 0

    def __call__(self, *paths: Path, key: str) -> AiVectorRepository:
        self.created += 1
        return AiVectorRepository(*paths, key=key)


def _session(tmp_path: Path, factory: _RepositoryFactory) -> AiSearchSession:
    return AiSearchSession(
        tmp_path / "ai_index.faiss", tmp_path / "ai_id_map.json",
        tmp_path / "ai_index_meta.json", repository_factory=factory,
    )


def _save(tmp_path: Path, paths: list[str], key: str = "test-passphrase") -> None:
    repository = AiVectorRepository(tmp_path / "ai_index.faiss", tmp_path / "ai_id_map.json", key=key)
    repository.load()
    repository.reset()
    if paths:
        repository.add_images(np.ones((len(paths), 512), dtype=np.float32), paths)
    repository.save()


def test_ai_search_session_unchanged_generation_reuses_validated_snapshot(tmp_path: Path) -> None:
    # Arrange
    _save(tmp_path, ["/photos/a.jpg"])
    factory = _RepositoryFactory()
    session = _session(tmp_path, factory)

    # Act
    with session.repository("test-passphrase") as first:
        expected = first.get_vector("/photos/a.jpg")
    with session.repository("test-passphrase") as second:
        actual = second.get_vector("/photos/a.jpg")

    # Assert
    assert first is second
    assert factory.created == 1
    assert np.allclose(actual, expected)
    session.close()


def test_ai_search_session_published_scan_preserves_active_snapshot_and_refreshes_next_search(tmp_path: Path) -> None:
    # Arrange
    _save(tmp_path, ["/photos/a.jpg"])
    factory = _RepositoryFactory()
    session = _session(tmp_path, factory)

    # Act
    with session.repository("test-passphrase") as original:
        _save(tmp_path, ["/photos/b.jpg"])
        original_paths = original.get_indexed_paths()
    with session.repository("test-passphrase") as updated:
        updated_paths = updated.get_indexed_paths()

    # Assert
    assert original_paths == {"/photos/a.jpg"}
    assert updated_paths == {"/photos/b.jpg"}
    assert factory.created == 2
    session.close()


def test_ai_search_session_deleted_snapshot_drops_cached_paths(tmp_path: Path) -> None:
    # Arrange
    _save(tmp_path, ["/photos/a.jpg"])
    session = _session(tmp_path, _RepositoryFactory())
    with session.repository("test-passphrase"):
        pass
    (tmp_path / "ai_index.faiss.enc").unlink()

    # Act
    with session.repository("test-passphrase") as repository:
        actual = repository.get_indexed_paths()

    # Assert
    assert actual == set()
    session.close()


def test_ai_search_session_key_rewrap_rejects_old_password(tmp_path: Path) -> None:
    # Arrange
    _save(tmp_path, ["/photos/a.jpg"])
    session = _session(tmp_path, _RepositoryFactory())
    with session.repository("test-passphrase"):
        pass
    AiVectorStorage(tmp_path / "ai_index.faiss", "test-passphrase").change_password("new-passphrase")

    # Act / Assert
    with pytest.raises(AiVectorAuthenticationError):
        with session.repository("test-passphrase"):
            pass
    with session.repository("new-passphrase") as repository:
        assert repository.get_indexed_paths() == {"/photos/a.jpg"}
    session.close()


def test_ai_search_session_corrupt_generation_never_serves_cached_results(tmp_path: Path) -> None:
    # Arrange
    _save(tmp_path, ["/photos/a.jpg"])
    session = _session(tmp_path, _RepositoryFactory())
    with session.repository("test-passphrase"):
        pass
    encrypted = tmp_path / "ai_index.faiss.enc"
    encrypted.write_bytes(b"corrupt snapshot")

    # Act / Assert
    with pytest.raises(AiVectorAuthenticationError):
        with session.repository("test-passphrase"):
            pass
    session.close()


def test_ai_search_session_invalidation_reloads_unchanged_generation(tmp_path: Path) -> None:
    # Arrange
    _save(tmp_path, ["/photos/a.jpg"])
    factory = _RepositoryFactory()
    session = _session(tmp_path, factory)
    with session.repository("test-passphrase"):
        pass

    # Act
    session.invalidate()
    with session.repository("test-passphrase") as repository:
        actual = repository.get_indexed_paths()

    # Assert
    assert actual == {"/photos/a.jpg"}
    assert factory.created == 2
    session.close()


def test_ai_search_session_close_waits_for_active_lease_and_rejects_late_search(tmp_path: Path) -> None:
    # Arrange
    session = _session(tmp_path, _RepositoryFactory())
    started, closed = Event(), Event()

    def close_session() -> None:
        started.set()
        session.close()
        closed.set()

    # Act
    with session.repository(""):
        thread = Thread(target=close_session)
        thread.start()
        assert started.wait(5)
        assert not closed.is_set()
    thread.join(5)

    # Assert
    assert closed.is_set()
    with pytest.raises(RuntimeError, match="closed"):
        with session.repository(""):
            pass