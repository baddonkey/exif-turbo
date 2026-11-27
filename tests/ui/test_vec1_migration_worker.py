from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from exif_turbo.config import ai_id_map_path, ai_index_path, ai_vector_metadata_path
from exif_turbo.data.ai_vec1_repository import AiVec1StagingResult
from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.workers.vec1_migration_worker import Vec1MigrationWorker


def test_vec1_migration_worker_stages_authenticated_snapshot_without_activation(
    qtbot: QtBot, tmp_path: Path
) -> None:
    extension = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not extension:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")
    db_path = tmp_path / "index.db"
    password = "test-database-password"
    image_path = str(tmp_path / "image.jpg")
    images = ImageIndexRepository(db_path, key=password)
    images.upsert_image(image_path, "image.jpg", 1.0, 100, {}, "")
    images.close()
    paths = (ai_index_path(db_path), ai_id_map_path(db_path), ai_vector_metadata_path(db_path))
    source = AiVectorRepository(*paths, key=password)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [image_path])
    source.save()
    source.close()
    worker = Vec1MigrationWorker(db_path, password, Path(extension))
    failures: list[str] = []
    worker.failed.connect(failures.append)

    with qtbot.waitSignal(worker.completed, timeout=10000) as completed:
        worker.start()
    assert worker.wait(10000)
    assert failures == []
    assert isinstance(completed.args[0], AiVec1StagingResult)
    assert completed.args[0].staged_vectors == 1
    assert paths[0].with_name(paths[0].name + ".enc").exists()
