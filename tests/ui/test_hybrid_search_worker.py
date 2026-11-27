from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from exif_turbo.config import ai_id_map_path, ai_index_path, ai_vector_metadata_path
from exif_turbo.data.ai_search_session import AiSearchSession
from exif_turbo.data.ai_vector_backend import AiVectorBackend
from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.workers.hybrid_search_worker import HybridSearchWorker


def test_hybrid_worker_builds_ranked_generation_and_first_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "index.db"
    paths = [str(tmp_path / f"{index}.jpg") for index in range(3)]
    repo = ImageIndexRepository(db_path, key="")
    for path in paths:
        repo.upsert_image(path, Path(path).name, 1.0, 100, {}, "Canon")
    repo.close()

    vector_paths = (
        ai_index_path(db_path), ai_id_map_path(db_path), ai_vector_metadata_path(db_path)
    )
    vectors = AiVectorRepository(*vector_paths)
    vectors.load()
    vector = np.ones(512, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    vectors.add_images(np.stack([vector, vector]), paths[:2])
    vectors.save()
    vectors.close()

    class FakeEncoder:
        def __init__(self, vector_repo: AiVectorBackend) -> None:
            pass

        def encode_text(self, text: str) -> np.ndarray:
            return vector

    monkeypatch.setattr("exif_turbo.ui.workers.hybrid_search_worker.AiIndexerService", FakeEncoder)
    session = AiSearchSession(*vector_paths)
    worker = HybridSearchWorker(db_path, "", "Canon", 19, page_size=1, session=session)
    emitted: list[tuple[list, int, int]] = []
    failures: list[tuple[str, int]] = []
    worker.results_ready.connect(lambda rows, count, serial: emitted.append((rows, count, serial)))
    worker.failed.connect(lambda message, serial: failures.append((message, serial)))

    worker.run()
    session.close()

    assert failures == []
    assert len(emitted) == 1
    assert len(emitted[0][0]) == 1
    assert emitted[0][1:] == (3, 19)
    assert worker.results is not None
    assert len(worker.results.matches) == 3


def test_hybrid_worker_empty_ai_index_reports_error_instead_of_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    repo = ImageIndexRepository(db_path, key="")
    repo.upsert_image(str(tmp_path / "one.jpg"), "one.jpg", 1.0, 100, {}, "Canon")
    repo.close()
    worker = HybridSearchWorker(db_path, "", 'Canon ai:="deer"', 5)
    failures: list[tuple[str, int]] = []
    worker.failed.connect(lambda message, serial: failures.append((message, serial)))

    worker.run()

    assert len(failures) == 1
    assert "AI index is empty" in failures[0][0]
    assert failures[0][1] == 5
    assert worker.results is None


def test_hybrid_worker_empty_query_browses_without_ai_index(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    repo = ImageIndexRepository(db_path, key="")
    repo.upsert_image(str(tmp_path / "one.jpg"), "one.jpg", 1.0, 100, {}, "Canon")
    repo.close()
    worker = HybridSearchWorker(db_path, "", "", 7)
    emitted: list[tuple[list, int, int]] = []
    worker.results_ready.connect(lambda rows, count, serial: emitted.append((rows, count, serial)))

    worker.run()

    assert len(emitted) == 1
    assert emitted[0][1:] == (1, 7)
