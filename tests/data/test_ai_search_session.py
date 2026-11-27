from __future__ import annotations

import os
from pathlib import Path
from threading import Event, Thread

import numpy as np
import pytest

from exif_turbo.data.ai_search_session import AiSearchSession
from exif_turbo.data.ai_vec1_repository import AiVec1Repository
from exif_turbo.data.ai_vector_backend import AiVectorIndexError
from exif_turbo.data.image_index_repository import ImageIndexRepository


@pytest.fixture
def extension_path() -> Path:
    value = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not value:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")
    path = Path(value)
    if not path.is_file():
        pytest.fail("EXIF_TURBO_VEC1_EXTENSION does not point to a file")
    return path


def _seed(db_path: Path, image_paths: list[str]) -> None:
    repo = ImageIndexRepository(db_path, key="")
    try:
        for path in image_paths:
            repo.upsert_image(path, Path(path).name, 1.0, 100, {}, "")
    finally:
        repo.close()


def test_ai_search_session_reopened_lease_observes_new_vectors(
    tmp_path: Path, extension_path: Path
) -> None:
    # Arrange
    db_path = tmp_path / "index.db"
    first, second = str(tmp_path / "first.jpg"), str(tmp_path / "second.jpg")
    _seed(db_path, [first, second])
    session = AiSearchSession(db_path, extension_resolver=lambda: extension_path)
    writer = AiVec1Repository(db_path, "", extension_path)
    writer.load()
    vector = np.ones(512, dtype=np.float32)
    writer.add_images(vector, [first])

    # Act
    with session.repository("") as original:
        original_paths = original.get_indexed_paths()
    writer.add_images(vector, [second])
    with session.repository("") as updated:
        updated_paths = updated.get_indexed_paths()
    writer.close()
    session.close()

    # Assert
    assert original_paths == {first}
    assert updated_paths == {first, second}


def test_ai_search_session_concurrent_index_change_rejects_stale_results(
    tmp_path: Path, extension_path: Path
) -> None:
    # Arrange
    db_path = tmp_path / "index.db"
    image = str(tmp_path / "image.jpg")
    _seed(db_path, [image])
    session = AiSearchSession(db_path, extension_resolver=lambda: extension_path)

    # Act / Assert
    with pytest.raises(AiVectorIndexError, match="changed during search"), session.repository(""):
        writer = AiVec1Repository(db_path, "", extension_path)
        try:
            writer.load()
            writer.add_images(np.ones(512, dtype=np.float32), [image])
        finally:
            writer.close()
    session.close()


def test_ai_search_session_close_waits_for_lease_and_rejects_late_search(
    tmp_path: Path, extension_path: Path
) -> None:
    # Arrange
    db_path = tmp_path / "index.db"
    _seed(db_path, [])
    session = AiSearchSession(db_path, extension_resolver=lambda: extension_path)
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
    with pytest.raises(RuntimeError, match="closed"), session.repository(""):
        pass
