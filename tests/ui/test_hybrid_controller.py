from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from exif_turbo.data.ai_vec1_repository import AiVec1Repository
from exif_turbo.data.ai_vector_backend import AiVectorBackend
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.view_models.app_controller import AppController
from exif_turbo.ui.workers.hybrid_search_worker import HybridSearchWorker


@pytest.fixture
def hybrid_controller(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[AppController, SearchListModel, list[str], list[str]]]:
    extension = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not extension:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")
    extension_path = Path(extension)
    db_path = tmp_path / "test.db"
    paths = [str(tmp_path / f"{index:03}.jpg") for index in range(125)]
    repo = ImageIndexRepository(db_path, key="")
    repo.upsert_images_batch([
        (path, Path(path).name, 1.0, 100, {},
         "Canon" if index < 70 else "Nikon", None, 1609459200.0)
        for index, path in enumerate(paths)
    ])
    repo.close()
    vectors = AiVec1Repository(db_path, "", extension_path)
    vectors.load()
    vector = np.ones(512, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    vectors.add_images(np.stack([vector] * 60), paths[45:105])
    vectors.save()
    vectors.close()
    encoded: list[str] = []

    class FakeEncoder:
        def __init__(self, vector_repo: AiVectorBackend) -> None:
            pass

        def encode_text(self, text: str) -> np.ndarray:
            encoded.append(text)
            return vector

    monkeypatch.setattr("exif_turbo.ui.workers.hybrid_search_worker.AiIndexerService", FakeEncoder)
    monkeypatch.setattr(
        "exif_turbo.data.ai_search_session.bundled_vec1_extension", lambda: extension_path
    )
    model = SearchListModel(cache_dir=tmp_path / "thumbs")
    controller = AppController(db_path, model, ExifListModel(), FolderListModel())
    controller.unlock("")
    qtbot.waitUntil(
        lambda: not controller.isLocked and not controller.isSearching
        and controller.totalResults == 125 and controller._search_worker is None,
        timeout=10000,
    )
    yield controller, model, paths, encoded
    controller.close()


def test_hybrid_controller_pages_complete_union_without_requery(
    qtbot: QtBot, hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]]
) -> None:
    controller, model, paths, encoded = hybrid_controller
    controller.setHybridSearchMode(True)
    controller.hybridSearch("Canon", "normal")
    qtbot.waitUntil(lambda: not controller.isSearching, timeout=10000)

    assert controller.totalResults == 105, controller.searchError
    assert controller.loadedResults == 50
    assert controller.loadMore()
    qtbot.waitUntil(lambda: not controller._loading, timeout=10000)
    assert controller.loadedResults == 100, controller.searchError
    assert controller.loadMore()
    qtbot.waitUntil(lambda: controller.loadedResults == 105, timeout=10000)

    assert {model.get_path(index) for index in range(105)} == set(paths[:105])
    assert len({model.get_path(index) for index in range(105)}) == 105
    assert encoded == ["Canon"]


def test_hybrid_controller_sorts_cached_ranking_without_requery(
    qtbot: QtBot, hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]]
) -> None:
    controller, model, _, encoded = hybrid_controller
    controller.setHybridSearchMode(True)
    controller.hybridSearch("Canon", "normal")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)
    relevance_first = model.get_path(0)

    controller.setSortBy("filename_desc")
    qtbot.waitUntil(lambda: not controller.isSearching, timeout=10000)
    assert Path(model.get_path(0)).name == "104.jpg"
    controller.setSortBy("")
    qtbot.waitUntil(lambda: not controller.isSearching, timeout=10000)

    assert model.get_path(0) == relevance_first
    assert encoded == ["Canon"]
    assert controller.searchError == ""


def test_hybrid_controller_sort_requeries_after_database_change(
    qtbot: QtBot, hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]]
) -> None:
    controller, model, _, encoded = hybrid_controller
    controller.setHybridSearchMode(True)
    controller.hybridSearch("Canon", "normal")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)
    repo = ImageIndexRepository(controller._db_path, key="")
    repo.upsert_image(str(controller._db_path.parent / "new.jpg"), "new.jpg", 1.0, 100, {}, "Canon")
    repo.close()

    controller.setSortBy("filename_desc")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 106, timeout=10000)

    assert Path(model.get_path(0)).name == "new.jpg"
    assert encoded == ["Canon", "Canon"]


def test_hybrid_controller_restarts_stale_generation_after_database_change(
    qtbot: QtBot, hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]]
) -> None:
    controller, _, _, encoded = hybrid_controller
    controller.setHybridSearchMode(True)
    controller.hybridSearch("Canon", "normal")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)
    repo = ImageIndexRepository(controller._db_path, key="")
    new_path = str(controller._db_path.parent / "new.jpg")
    repo.upsert_image(new_path, "new.jpg", 1.0, 100, {}, "Canon")
    repo.close()

    assert not controller.loadMore()
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 106, timeout=10000)
    assert encoded == ["Canon", "Canon"]


def test_hybrid_controller_timer_refreshes_after_external_database_change(
    qtbot: QtBot, hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]]
) -> None:
    controller, _, _, encoded = hybrid_controller
    controller.setHybridSearchMode(True)
    controller.hybridSearch("Canon", "normal")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)
    repo = ImageIndexRepository(controller._db_path, key="")
    repo.upsert_image(str(controller._db_path.parent / "new.jpg"), "new.jpg", 1.0, 100, {}, "Canon")
    repo.close()

    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 106, timeout=10000)

    assert encoded == ["Canon", "Canon"]


def test_hybrid_controller_discards_failure_from_superseded_worker(
    qtbot: QtBot,
    hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _, _, _ = hybrid_controller
    started = Event()
    release = Event()
    original_run = HybridSearchWorker.run

    def run(worker: HybridSearchWorker) -> None:
        if worker._query == "old":
            started.set()
            if release.wait(10):
                worker.failed.emit("obsolete failure", worker._serial)
        else:
            original_run(worker)

    monkeypatch.setattr(HybridSearchWorker, "run", run)
    controller.setHybridSearchMode(True)
    try:
        controller.hybridSearch("old", "normal")
        qtbot.waitUntil(started.is_set, timeout=10000)
        controller.hybridSearch("Canon", "normal")
        qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)
        release.set()
        qtbot.waitUntil(lambda: not controller._finishing_search_workers, timeout=10000)
    finally:
        release.set()

    assert controller.totalResults == 105
    assert controller.searchError == ""


def test_hybrid_controller_stale_failure_does_not_clear_new_worker_busy_state(
    qtbot: QtBot,
    hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _, _, _ = hybrid_controller
    old_started = Event()
    new_started = Event()
    release_old = Event()
    release_new = Event()
    original_run = HybridSearchWorker.run

    def run(worker: HybridSearchWorker) -> None:
        if worker._query == "old":
            old_started.set()
            if release_old.wait(10):
                worker.failed.emit("obsolete failure", worker._serial)
        else:
            new_started.set()
            if release_new.wait(10):
                original_run(worker)

    monkeypatch.setattr(HybridSearchWorker, "run", run)
    controller.setHybridSearchMode(True)
    try:
        controller.hybridSearch("old", "normal")
        qtbot.waitUntil(old_started.is_set, timeout=10000)
        old_worker = controller._hybrid_search_worker
        assert old_worker is not None
        controller.hybridSearch("Canon", "normal")
        qtbot.waitUntil(new_started.is_set, timeout=10000)
        with qtbot.waitSignal(old_worker.finished, timeout=10000):
            release_old.set()
        assert controller.isSearching
        assert controller.searchError == ""
    finally:
        release_old.set()
        release_new.set()
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)


def test_hybrid_controller_retries_failure_from_changed_database_generation(
    qtbot: QtBot,
    hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _, _, encoded = hybrid_controller
    started = Event()
    release = Event()
    original_run = HybridSearchWorker.run
    attempts: list[int] = []

    def run(worker: HybridSearchWorker) -> None:
        attempts.append(worker._serial)
        if len(attempts) == 1:
            started.set()
            if release.wait(10):
                worker.failed.emit("stale failure", worker._serial)
        else:
            original_run(worker)

    monkeypatch.setattr(HybridSearchWorker, "run", run)
    controller.setHybridSearchMode(True)
    try:
        controller.hybridSearch("Canon", "normal")
        qtbot.waitUntil(started.is_set, timeout=10000)
        repo = ImageIndexRepository(controller._db_path, key="")
        repo.upsert_image(str(controller._db_path.parent / "new.jpg"), "new.jpg", 1.0, 100, {}, "Canon")
        repo.close()
        release.set()
        qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 106, timeout=10000)
    finally:
        release.set()

    assert len(attempts) == 2
    assert encoded == ["Canon"]
    assert controller.searchError == ""


def test_hybrid_controller_browse_restores_mode_and_query(
    qtbot: QtBot, hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]]
) -> None:
    controller, _, _, _ = hybrid_controller
    controller.setHybridSearchMode(True)
    controller.hybridSearch("Canon", "normal")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)

    controller.enterBrowseTab("Canon")
    assert not controller.isHybridSearchMode
    query = controller.leaveBrowseTab()
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)

    assert query == "Canon"
    assert controller.isHybridSearchMode


def test_hybrid_controller_disabling_ai_restores_metadata_results(
    qtbot: QtBot, hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]]
) -> None:
    controller, _, _, _ = hybrid_controller
    controller.setAiEnabled(True)
    controller.setHybridSearchMode(True)
    controller.hybridSearch("Canon", "normal")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 105, timeout=10000)

    controller.setAiEnabled(False)
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 70, timeout=10000)

    assert not controller.isHybridSearchMode


def test_hybrid_controller_saves_and_restores_image_set_search_view(
    qtbot: QtBot, hybrid_controller: tuple[AppController, SearchListModel, list[str], list[str]]
) -> None:
    controller, model, _, _ = hybrid_controller
    controller.setAiEnabled(True)
    controller.setHybridSearchMode(True)
    controller.hybridSearch('Canon ai:="deer"', "broad")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 25, timeout=10000)
    controller.setSortBy("filename_desc")
    qtbot.waitUntil(lambda: not controller.isSearching, timeout=10000)
    controller.setExtFilter("jpg")
    qtbot.waitUntil(lambda: not controller.isSearching, timeout=10000)
    set_id = controller.createImageSet("Saved view")

    assert controller.saveHybridSearchToImageSet(set_id)
    controller.setHybridSearchMode(False)
    controller.search("Nikon")
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 55, timeout=10000)
    assert controller.restoreHybridSearchFromImageSet(set_id)
    qtbot.waitUntil(lambda: not controller.isSearching and controller.totalResults == 25, timeout=10000)

    assert controller.hybridQuery == 'Canon ai:="deer"'
    assert controller.hybridPrecision == "broad"
    assert controller.hybridSortBy == "filename_desc"
    assert controller.extFilter == "jpg"
    assert Path(model.get_path(0)).name == "069.jpg"
