from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import sqlcipher3

from exif_turbo.config import database_data_dir
from exif_turbo.data.ai_vec1_repository import AiVec1Repository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.workers.password_change_worker import PasswordChangeWorker
from exif_turbo.utils.thumb_crypto import ThumbCrypto


def _vec1_extension() -> Path:
    extension_value = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not extension_value:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")
    extension = Path(extension_value)
    if not extension.is_file():
        pytest.fail("EXIF_TURBO_VEC1_EXTENSION does not point to a file")
    return extension


def _seed_vec1_index(
    db_path: Path,
    extension: Path,
    password: str,
    image_path: str,
) -> None:
    index = ImageIndexRepository(db_path, key=password)
    index.upsert_image(
        image_path,
        Path(image_path).name,
        1.0,
        1,
        {},
        "",
    )
    index.close()

    repository = AiVec1Repository(db_path, password, extension)
    repository.load()
    vector = np.ones(repository.dimension, dtype=np.float32)
    repository.add_images(vector, [image_path])
    repository.save()
    repository.close()


def _load_vec1_paths(
    db_path: Path,
    extension: Path,
    password: str,
) -> set[str]:
    repository = AiVec1Repository(db_path, password, extension)
    repository.load()
    try:
        return repository.get_indexed_paths()
    finally:
        repository.close()


def _write_obsolete_faiss_sidecars(db_path: Path) -> dict[Path, bytes]:
    sidecars = {
        database_data_dir(db_path) / "ai_index.faiss": b"obsolete faiss index bytes",
        database_data_dir(db_path) / "ai_id_map.json": b"obsolete faiss mapping bytes",
        database_data_dir(db_path) / "ai_index_meta.json": b"obsolete faiss metadata bytes",
    }
    for path, content in sidecars.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return sidecars


def test_password_change_worker_rekeys_vec1_and_preserves_sidecars_and_thumbnails(
    tmp_path: Path,
) -> None:
    # Arrange
    extension = _vec1_extension()
    db_path = tmp_path / "index.db"
    old_password, new_password = "old-ai-passphrase", "new-ai-passphrase"
    image_path = str(tmp_path / "private-photo.jpg")
    _seed_vec1_index(db_path, extension, old_password, image_path)
    obsolete_sidecars = _write_obsolete_faiss_sidecars(db_path)
    cache_dir = tmp_path / "thumbs"
    thumbnail = ThumbCrypto(old_password, cache_dir).encrypt(b"thumbnail")
    worker = PasswordChangeWorker(db_path, old_password, new_password, cache_dir)
    failures: list[str] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert finished == [True]
    assert _load_vec1_paths(db_path, extension, new_password) == {image_path}
    assert all(
        path.read_bytes() == content
        for path, content in obsolete_sidecars.items()
    )
    assert ThumbCrypto(new_password, cache_dir).decrypt(thumbnail) == b"thumbnail"
    assert worker._old_password == worker._new_password == ""
    with pytest.raises(sqlcipher3.DatabaseError):
        ImageIndexRepository(db_path, key=old_password)


def test_password_change_worker_failed_rekey_preserves_vec1_under_old_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    extension = _vec1_extension()
    db_path = tmp_path / "index.db"
    old_password, new_password = "old-ai-passphrase", "new-ai-passphrase"
    image_path = str(tmp_path / "photo.jpg")
    _seed_vec1_index(db_path, extension, old_password, image_path)
    obsolete_sidecars = _write_obsolete_faiss_sidecars(db_path)
    worker = PasswordChangeWorker(db_path, old_password, new_password, None)
    failures: list[str] = []
    worker.failed.connect(failures.append)

    def fail_rekey(self: ImageIndexRepository, password: str) -> None:
        del self, password
        raise OSError("simulated rekey failure")

    monkeypatch.setattr(ImageIndexRepository, "change_password", fail_rekey)

    # Act
    worker.run()

    # Assert
    assert failures == ["simulated rekey failure"]
    assert _load_vec1_paths(db_path, extension, old_password) == {image_path}
    assert all(
        path.read_bytes() == content
        for path, content in obsolete_sidecars.items()
    )
    with pytest.raises(sqlcipher3.DatabaseError):
        ImageIndexRepository(db_path, key=new_password)


def test_password_change_worker_encrypts_plaintext_vec1_index(tmp_path: Path) -> None:
    # Arrange
    extension = _vec1_extension()
    db_path = tmp_path / "index.db"
    image_path = str(tmp_path / "photo.jpg")
    _seed_vec1_index(db_path, extension, "", image_path)
    worker = PasswordChangeWorker(db_path, "", "new-ai-passphrase", None)
    failures: list[str] = []
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert _load_vec1_paths(db_path, extension, "new-ai-passphrase") == {image_path}
    assert db_path.read_bytes()[:16] != b"SQLite format 3\x00"
