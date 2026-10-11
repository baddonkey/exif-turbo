from pathlib import Path

import numpy as np
import pytest

from exif_turbo.config import ai_id_map_path, ai_index_path
from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.data.ai_vector_storage import AiVectorAuthenticationError, AiVectorStorage
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.workers.password_change_worker import PasswordChangeWorker
from exif_turbo.utils.thumb_crypto import ThumbCrypto


def test_password_change_worker_success_preserves_ai_and_thumbnails(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "index.db"
    old_password, new_password = "old-ai-passphrase", "new-ai-passphrase"
    ImageIndexRepository(db_path, key=old_password).close()
    repository = AiVectorRepository(ai_index_path(db_path), ai_id_map_path(db_path), key=old_password)
    repository.load()
    repository.add_images(np.ones(512, dtype=np.float32), ["/private/photo.jpg"])
    repository.save()
    storage = AiVectorStorage(ai_index_path(db_path), old_password)
    original = storage.path.read_bytes()
    cache_dir = tmp_path / "thumbs"
    thumbnail = ThumbCrypto(old_password, cache_dir).encrypt(b"thumbnail")
    worker = PasswordChangeWorker(db_path, old_password, new_password, cache_dir)
    failures: list[str] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))

    # Act
    worker.run()
    loaded = AiVectorRepository(ai_index_path(db_path), ai_id_map_path(db_path), key=new_password)
    loaded.load()

    # Assert
    assert failures == []
    assert finished == [True]
    assert loaded.get_indexed_paths() == {"/private/photo.jpg"}
    assert storage.path.read_bytes() == original
    assert ThumbCrypto(new_password, cache_dir).decrypt(thumbnail) == b"thumbnail"
    assert worker._old_password == worker._new_password == ""
    with pytest.raises(AiVectorAuthenticationError):
        storage.load()


def test_password_change_worker_failed_rekey_preserves_old_ai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    db_path = tmp_path / "index.db"
    old_password = "old-ai-passphrase"
    ImageIndexRepository(db_path, key=old_password).close()
    storage = AiVectorStorage(ai_index_path(db_path), old_password)
    expected = (b"vectors", b"paths", b"metadata")
    storage.save(*expected)
    worker = PasswordChangeWorker(db_path, old_password, "new-ai-passphrase", None)
    failures: list[str] = []
    worker.failed.connect(failures.append)

    def fail_rekey(self: ImageIndexRepository, new_password: str) -> None:
        raise OSError("simulated rekey failure")

    monkeypatch.setattr(ImageIndexRepository, "change_password", fail_rekey)

    # Act
    worker.run()
    storage.migrate(ai_index_path(db_path), ai_id_map_path(db_path), tmp_path / "metadata.json")

    # Assert
    assert failures == ["simulated rekey failure"]
    assert storage.load() == expected
    assert not (storage.key_dir / "password.pending").exists()