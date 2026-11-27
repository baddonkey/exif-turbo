from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from exif_turbo.data.ai_vec1_repository import AiVec1Repository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.ai_model_profile import DEFAULT_AI_MODEL_PROFILE
from exif_turbo.ui.workers.vec1_training_worker import Vec1TrainingWorker


def test_vec1_training_worker_trains_in_background(
    qtbot: QtBot, tmp_path: Path
) -> None:
    extension = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not extension:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")
    db_path = tmp_path / "index.db"
    paths = [str(tmp_path / f"{index:03}.jpg") for index in range(128)]
    images = ImageIndexRepository(db_path, key="")
    images.upsert_images_batch([
        (path, Path(path).name, 1.0, 100, {}, "", None, None) for path in paths
    ])
    images.close()
    repo = AiVec1Repository(db_path, "", Path(extension))
    repo.load()
    vectors = np.zeros((128, DEFAULT_AI_MODEL_PROFILE.dimension), dtype=np.float32)
    vectors[:, 0] = 1.0
    repo.add_images(vectors, paths)
    repo.close()
    worker = Vec1TrainingWorker(db_path, "", Path(extension))
    errors: list[str] = []
    worker.failed.connect(errors.append)

    with qtbot.waitSignal(worker.completed, timeout=10000):
        worker.start()
    assert worker.wait(10000)
    assert errors == []
    reopened = AiVec1Repository(db_path, "", Path(extension))
    reopened.load()
    try:
        assert reopened.get_vector_count() == 128
    finally:
        reopened.close()
