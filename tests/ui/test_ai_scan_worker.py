from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image

from exif_turbo.config import database_data_dir
from exif_turbo.data.ai_vec1_repository import AiVec1Repository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository
from exif_turbo.ui.workers.ai_scan_worker import AiScanWorker


def _make_jpeg(path: Path, size: tuple[int, int] = (256, 192)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "blue").save(path, "JPEG")


def _vec1_extension(monkeypatch: pytest.MonkeyPatch) -> Path:
    extension_value = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not extension_value:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")
    extension = Path(extension_value)
    if not extension.is_file():
        pytest.fail("EXIF_TURBO_VEC1_EXTENSION does not point to a file")
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_scan_worker.bundled_vec1_extension",
        lambda: extension,
    )
    return extension


def _seed_db(db_path: Path, sources: list[Path], key: str = "") -> int:
    folder_repo = IndexedFolderRepository(db_path, key=key)
    folder = folder_repo.add(str(sources[0].parent))
    folder_repo.update_status(folder.id, "indexed", image_count=len(sources))
    folder_repo.close()

    repo = ImageIndexRepository(db_path, key=key)
    for src in sources:
        st = src.stat()
        repo.upsert_image(
            str(src), src.name, st.st_mtime, st.st_size, {}, "",
            folder_id=folder.id,
        )
    repo.commit()
    repo.close()
    return folder.id


def _seed_vec1_vectors(
    db_path: Path,
    extension: Path,
    paths: list[Path],
    key: str = "",
) -> None:
    repository = AiVec1Repository(db_path, key, extension)
    repository.load()
    vectors = np.ones(
        (len(paths), repository.dimension),
        dtype=np.float32,
    )
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    repository.add_images(vectors, [str(path) for path in paths])
    repository.save()
    repository.close()


def _load_indexed_paths(
    db_path: Path,
    extension: Path,
    key: str = "",
) -> set[str]:
    repository = AiVec1Repository(db_path, key, extension)
    repository.load()
    try:
        return repository.get_indexed_paths()
    finally:
        repository.close()


def _unique_db_path(tmp_path: Path) -> Path:
    return tmp_path / f"ai_scan_{uuid4().hex}.db"


class _FakeAiIndexerService:
    """Provide deterministic vectors without loading or downloading CLIP."""

    def __init__(
        self,
        vector_repo: AiVec1Repository,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        self._repo = vector_repo

    def build_index(
        self,
        image_paths: list[str],
        stamps: dict[str, tuple[float, int]] | None = None,
        on_progress=None,
        cancel_check=None,
    ) -> tuple[int, int]:
        del stamps
        pending = [
            path
            for path in image_paths
            if path not in self._repo.get_indexed_paths()
        ]
        available = [path for path in pending if Path(path).is_file()]
        errors = len(pending) - len(available)
        if available:
            vectors = np.ones(
                (len(available), self._repo.dimension),
                dtype=np.float32,
            )
            vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
            self._repo.add_images(vectors, available)
        if on_progress is not None and pending:
            on_progress(len(pending), len(pending), pending[-1])
        return len(available), errors


def _patch_indexer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_scan_worker.AiIndexerService",
        _FakeAiIndexerService,
    )


def test_ai_scan_worker_full_scan_builds_empty_vec1_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    extension = _vec1_extension(monkeypatch)
    db_path = _unique_db_path(tmp_path)
    image = tmp_path / "photos" / "photo.jpg"
    _make_jpeg(image)
    password = "test-database-password"
    folder_id = _seed_db(db_path, [image], password)
    _patch_indexer(monkeypatch)
    worker = AiScanWorker(
        db_path,
        folder_id,
        str(image.parent),
        password,
        force_rebuild=True,
    )
    errors: list[str] = []
    worker.failed.connect(errors.append)

    # Act
    worker.run()

    # Assert
    assert errors == []
    assert _load_indexed_paths(db_path, extension, password) == {str(image)}


def test_ai_scan_worker_incremental_scan_keeps_existing_folder_vectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    extension = _vec1_extension(monkeypatch)
    src_dir = tmp_path / "src"
    current = src_dir / "current.jpg"
    stale = src_dir / "stale.jpg"
    _make_jpeg(current)
    _make_jpeg(stale)
    db_path = _unique_db_path(tmp_path)
    folder_id = _seed_db(db_path, [current, stale])
    _seed_vec1_vectors(db_path, extension, [current, stale])
    stale.unlink()
    _patch_indexer(monkeypatch)
    worker = AiScanWorker(db_path, folder_id, str(src_dir), force_rebuild=False)

    # Act
    worker.run()

    # Assert
    assert _load_indexed_paths(db_path, extension) == {str(current), str(stale)}


def test_ai_scan_worker_full_rescan_replaces_folder_vectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    extension = _vec1_extension(monkeypatch)
    src_dir = tmp_path / "src"
    current = src_dir / "current.jpg"
    stale = src_dir / "stale.jpg"
    _make_jpeg(current)
    _make_jpeg(stale)
    db_path = _unique_db_path(tmp_path)
    folder_id = _seed_db(db_path, [current, stale])
    _seed_vec1_vectors(db_path, extension, [current, stale])
    stale.unlink()
    _patch_indexer(monkeypatch)
    worker = AiScanWorker(db_path, folder_id, str(src_dir), force_rebuild=True)

    # Act
    worker.run()

    # Assert
    assert _load_indexed_paths(db_path, extension) == {str(current)}


def test_ai_scan_worker_password_scan_encrypts_vec1_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    extension = _vec1_extension(monkeypatch)
    current = tmp_path / "src" / "private-image-name.jpg"
    _make_jpeg(current)
    db_path = _unique_db_path(tmp_path)
    key = "test-ai-passphrase"
    folder_id = _seed_db(db_path, [current], key)
    _patch_indexer(monkeypatch)
    worker = AiScanWorker(db_path, folder_id, str(current.parent), key)
    failures: list[str] = []
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert _load_indexed_paths(db_path, extension, key) == {str(current)}
    assert str(current).encode() not in db_path.read_bytes()
    assert not (database_data_dir(db_path) / "ai_index.faiss").exists()
    assert not (database_data_dir(db_path) / "ai_id_map.json").exists()
    assert not (database_data_dir(db_path) / "ai_index_meta.json").exists()
    assert worker._key == ""


def test_ai_scan_worker_wrong_password_preserves_obsolete_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _vec1_extension(monkeypatch)
    current = tmp_path / "src" / "photo.jpg"
    _make_jpeg(current)
    db_path = _unique_db_path(tmp_path)
    folder_id = _seed_db(db_path, [current], "correct-password")
    obsolete_sidecars = {
        database_data_dir(db_path) / "ai_index.faiss": b"obsolete faiss index",
        database_data_dir(db_path) / "ai_id_map.json": b"obsolete faiss mapping",
        database_data_dir(db_path) / "ai_index_meta.json": b"obsolete faiss metadata",
    }
    for path, content in obsolete_sidecars.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    worker = AiScanWorker(
        db_path,
        folder_id,
        str(current.parent),
        "wrong-password",
        force_rebuild=True,
    )
    failures: list[str] = []
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert len(failures) == 1
    assert all(path.read_bytes() == content for path, content in obsolete_sidecars.items())


def test_ai_scan_worker_cancellation_persists_partial_vec1_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    extension = _vec1_extension(monkeypatch)
    image = tmp_path / "src" / "photo.jpg"
    _make_jpeg(image)
    db_path = _unique_db_path(tmp_path)
    folder_id = _seed_db(db_path, [image])
    worker = AiScanWorker(db_path, folder_id, str(image.parent))

    class CancelAfterFirstVector:
        def __init__(self, vector_repo: AiVec1Repository, **_kwargs: object) -> None:
            self._repo = vector_repo

        def build_index(
            self,
            image_paths: list[str],
            stamps=None,
            on_progress=None,
            cancel_check=None,
        ) -> tuple[int, int]:
            del stamps, cancel_check
            vector = np.ones(self._repo.dimension, dtype=np.float32)
            self._repo.add_images(vector, [image_paths[0]])
            if on_progress is not None:
                on_progress(1, len(image_paths), image_paths[0])
            worker.cancel()
            return 1, 0

    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_scan_worker.bundled_vec1_extension",
        lambda: extension,
    )
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_scan_worker.AiIndexerService",
        CancelAfterFirstVector,
    )
    canceled: list[int] = []
    finished: list[tuple[int, int]] = []
    worker.canceled.connect(canceled.append)
    worker.finished.connect(lambda indexed, errors: finished.append((indexed, errors)))

    # Act
    worker.run()

    # Assert
    assert canceled == [1]
    assert finished == []
    assert _load_indexed_paths(db_path, extension) == {str(image)}


def test_ai_scan_worker_empty_folder_finishes_without_canceling(
    tmp_path: Path,
) -> None:
    # Arrange
    db_path = _unique_db_path(tmp_path)
    source_dir = tmp_path / "empty"
    source_dir.mkdir()
    folder_repo = IndexedFolderRepository(db_path, key="")
    folder = folder_repo.add(str(source_dir))
    folder_repo.close()
    ImageIndexRepository(db_path, key="").close()
    worker = AiScanWorker(db_path, folder.id, str(source_dir))
    finished: list[tuple[int, int]] = []
    canceled: list[int] = []
    worker.finished.connect(lambda indexed, errors: finished.append((indexed, errors)))
    worker.canceled.connect(canceled.append)

    # Act
    worker.run()

    # Assert
    assert finished == [(0, 0)]
    assert canceled == []
