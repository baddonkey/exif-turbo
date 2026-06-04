"""E2E tests for the "Browse →" / "← Search" cross-tab navigation feature.

Covers:
  * selectResultById — finds an image by integer id, selects it, returns proxy row
  * selectResultById with an unknown id — returns -1
  * Full flow: search results → enterBrowseTab + browseFolder →
    selectResultById locates and selects the correct image in Browse
  * Returning to Search after Browse navigation preserves the previously
    selected search result row

Run with:
    pytest tests/ui/test_browse_navigation.py -v
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.view_models.app_controller import AppController

_PAUSE_MS = 300
_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

# (subdir, filename, PIL format, camera make)
_IMAGES: list[tuple[str, str, str, str]] = [
    ("folder_a", "alpha.jpg", "JPEG", "Canon"),
    ("folder_a", "beta.jpg",  "JPEG", "Canon"),
    ("folder_a", "gamma.png", "PNG",  "Canon"),
    ("folder_b", "delta.jpg", "JPEG", "Nikon"),
    ("folder_b", "epsil.png", "PNG",  "Nikon"),
]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def controller_with_images(
    qtbot: QtBot,
    tmp_path: Path,
) -> Generator[tuple[AppController, SearchListModel, Path, Path], None, None]:
    """AppController backed by a SQLite DB with two folders of indexed images.

    Yields (controller, search_model, folder_a, folder_b).
    """
    folder_a = tmp_path / "folder_a"
    folder_b = tmp_path / "folder_b"
    folder_a.mkdir()
    folder_b.mkdir()

    repo = ImageIndexRepository(tmp_path / "test.db", key="")
    for subdir, fname, pil_fmt, make in _IMAGES:
        img_path = tmp_path / subdir / fname
        Image.new("RGB", (32, 32), color=(100, 150, 200)).save(
            str(img_path), format=pil_fmt
        )
        stat = img_path.stat()
        metadata = {"FileName": fname, "Make": make}
        repo.upsert_image(
            str(img_path), fname, stat.st_mtime, stat.st_size,
            metadata, f"{fname} {make}",
        )
    repo.commit()
    repo.close()

    search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings = SettingsModel(tmp_path / "settings.json")
    controller = AppController(
        tmp_path / "test.db", search_model, exif_model, folder_model, settings
    )

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    yield controller, search_model, folder_a, folder_b

    controller.close()
    qtbot.wait(100)


# ── selectResultById ──────────────────────────────────────────────────────────


class TestSelectResultById:
    def test_selectResultById_known_id_returns_proxy_row(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — all 5 images are loaded; pick any id from the model.
        controller, search_model, _, _ = controller_with_images
        target_source_row = 2
        target_id = search_model.get_image_id(target_source_row)
        assert target_id is not None

        # Act
        proxy_row = controller.selectResultById(target_id)

        # Assert — a valid (≥ 0) proxy row is returned
        assert proxy_row >= 0

    def test_selectResultById_unknown_id_returns_minus_one(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, _ = controller_with_images

        # Act
        result = controller.selectResultById(-999)

        # Assert
        assert result == -1

    def test_selectResultById_selects_matching_image(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — pick the last image in the model (non-trivial row index).
        controller, search_model, _, _ = controller_with_images
        last_row = search_model.rowCount() - 1
        target_id = search_model.get_image_id(last_row)
        target_path = search_model.get_path(last_row)
        assert target_id is not None

        # Act
        controller.selectResultById(target_id)
        qtbot.wait(_PAUSE_MS)

        # Assert — the controller's selected source row matches the target.
        assert search_model.get_path(controller.currentResultRow) == target_path

    def test_selectResultById_proxy_row_matches_currentProxyResultRow(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, search_model, _, _ = controller_with_images
        target_id = search_model.get_image_id(1)
        assert target_id is not None

        # Act
        returned_proxy_row = controller.selectResultById(target_id)
        qtbot.wait(_PAUSE_MS)

        # Assert — returned value matches the property exposed to QML.
        assert returned_proxy_row == controller.currentProxyResultRow


# ── Full Browse navigation flow ───────────────────────────────────────────────


class TestBrowseNavigation:
    def test_ai_search_folder_filter_change_reruns_last_ai_search(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, folder_b = controller_with_images
        controller.setAiSearchMode(True)

        with patch("exif_turbo.ui.view_models.app_controller.AiSearchWorker.run", autospec=True) as mocked_run:
            def _emit_initial_results(worker: object) -> None:
                worker.results_ready.emit([], 0, [], worker._serial)  # type: ignore[attr-defined]

            mocked_run.side_effect = _emit_initial_results
            with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
                controller.aiSearch("boat", "normal")
        qtbot.wait(_PAUSE_MS)
        assert controller._last_ai_query == "boat"  # type: ignore[attr-defined]

        # Act
        seen_queries: list[str] = []
        with patch("exif_turbo.ui.view_models.app_controller.AiSearchWorker.run", autospec=True) as mocked_run:
            def _emit_filtered_results(worker: object) -> None:
                seen_queries.append(worker._query_text)  # type: ignore[attr-defined]
                worker.results_ready.emit([], 0, [], worker._serial)  # type: ignore[attr-defined]

            mocked_run.side_effect = _emit_filtered_results
            with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
                controller.setSearchFolderFilter(str(folder_b))
            qtbot.wait(_PAUSE_MS)

        # Assert
        assert seen_queries == ["boat"]

    def test_ai_search_uses_current_search_folder_filter(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, folder_b = controller_with_images
        controller.setAiSearchMode(True)
        controller.setSearchFolderFilter(str(folder_b))
        seen_path_filters: list[list[str] | None] = []

        # Act
        with patch("exif_turbo.ui.view_models.app_controller.AiSearchWorker.run", autospec=True) as mocked_run:
            def _emit_results(worker: object) -> None:
                seen_path_filters.append(worker._path_filter)  # type: ignore[attr-defined]
                worker.results_ready.emit([], 0, [], worker._serial)  # type: ignore[attr-defined]

            mocked_run.side_effect = _emit_results
            with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
                controller.aiSearch("boat", "normal")
            qtbot.wait(_PAUSE_MS)

        # Assert
        assert seen_path_filters == [[str(folder_b)]]

    def test_ai_search_completion_clears_busy_state_and_worker(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, _ = controller_with_images
        controller.setAiSearchMode(True)

        fake_rows = [
            (1, "C:/images/alpha.jpg", "alpha.jpg", "{}", 123, 1.0),
        ]

        # Act
        with patch("exif_turbo.ui.view_models.app_controller.AiSearchWorker.run", autospec=True) as mocked_run:
            def _emit_results(worker: object) -> None:
                worker.results_ready.emit(fake_rows, 1, [], worker._serial)  # type: ignore[attr-defined]
            mocked_run.side_effect = _emit_results
            with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
                controller.aiSearch("boat", "normal")
            qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.isSearching is False
        assert controller._ai_search_worker is None  # type: ignore[attr-defined]

    def test_enter_browse_tab_from_ai_mode_suspends_ai_until_return(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, search_model, _, folder_b = controller_with_images
        controller.setAiSearchMode(True)
        controller._ai_result_cache = list(search_model._rows)  # type: ignore[attr-defined]
        controller.selectResult(1)
        qtbot.wait(_PAUSE_MS)

        # Act
        controller.enterBrowseTab("boats")
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.isAiSearchMode is False

        # Act
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b))
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.isAiSearchMode is False

        # Act
        controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.isAiSearchMode is True

    def test_browseFolder_does_not_enable_blocking_search_state(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, folder_b = controller_with_images
        controller.enterBrowseTab("")

        # Act
        controller.browseFolder(str(folder_b))

        # Assert
        assert controller.isSearching is False

    def test_browseFolder_with_target_id_enables_busy_search_state(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, search_model, folder_a, _ = controller_with_images
        target_id = search_model.get_image_id(0)
        assert target_id is not None
        controller.enterBrowseTab("")

        # Act
        controller.browseFolder(str(folder_a), target_id)

        # Assert
        assert controller.isSearching is True

    def test_selectResultById_after_browseFolder_selects_image_in_browse(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — simulate the "Browse →" button: save the id of a
        # folder_b image from Search results, enter Browse, load that folder.
        controller, search_model, _, folder_b = controller_with_images
        target_path = str(folder_b / "delta.jpg")
        # Find the id in the current Search results (all images are loaded).
        target_id: int | None = None
        for i in range(search_model.rowCount()):
            if search_model.get_path(i) == target_path:
                target_id = search_model.get_image_id(i)
                break
        assert target_id is not None

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b))
        qtbot.wait(_PAUSE_MS)

        # Act — QML would call this once browseImageList.countChanged fires.
        proxy_row = controller.selectResultById(target_id)
        qtbot.wait(_PAUSE_MS)

        # Assert — the image is found and selected.
        assert proxy_row >= 0
        assert search_model_path(controller) == target_path

    def test_browse_jump_selection_from_loaded_results_is_not_overwritten(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — mimic QML's loadedResultsChanged handler selecting the
        # target image during a Browse jump.
        controller, search_model, _, folder_b = controller_with_images
        target_path = str(folder_b / "epsil.png")
        target_id: int | None = None
        for i in range(search_model.rowCount()):
            if search_model.get_path(i) == target_path:
                target_id = search_model.get_image_id(i)
                break
        assert target_id is not None

        def _apply_pending_jump() -> None:
            controller.selectResultById(target_id)

        controller.loadedResultsChanged.connect(_apply_pending_jump)

        # Act
        controller.enterBrowseTab("")
        controller._pending_browse_jump_id = target_id  # type: ignore[attr-defined]
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b), target_id)
        qtbot.wait(_PAUSE_MS)

        controller.loadedResultsChanged.disconnect(_apply_pending_jump)

        # Assert — the pending jump selection should survive the search finish.
        assert search_model_path(controller) == target_path

    def test_selectResultById_image_not_in_current_browse_folder_returns_minus_one(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — browse folder_b, but look for a folder_a image id.
        controller, search_model, folder_a, folder_b = controller_with_images
        alpha_path = str(folder_a / "alpha.jpg")
        alpha_id: int | None = None
        for i in range(search_model.rowCount()):
            if search_model.get_path(i) == alpha_path:
                alpha_id = search_model.get_image_id(i)
                break
        assert alpha_id is not None

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b))
        qtbot.wait(_PAUSE_MS)

        # Act
        result = controller.selectResultById(alpha_id)

        # Assert — image is not in the Browse results, so -1 is returned.
        assert result == -1

    def test_leave_browse_tab_after_navigation_restores_search_selection(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — select a non-zero row on the Search tab so the test can
        # distinguish "correctly restored" from "coincidentally row 0".
        controller, search_model, _, folder_b = controller_with_images
        controller.selectResult(2)
        qtbot.wait(_PAUSE_MS)
        search_row_before = controller.currentResultRow
        search_path_before = search_model.get_path(search_row_before)
        assert search_path_before is not None, "expected a valid path at row 2"

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b))
        qtbot.wait(_PAUSE_MS)
        # Select a different image while in Browse — delta.jpg is typically row 0.
        delta_path = str(folder_b / "delta.jpg")
        delta_id: int | None = None
        for i in range(search_model.rowCount()):
            if search_model.get_path(i) == delta_path:
                delta_id = search_model.get_image_id(i)
                break
        assert delta_id is not None
        controller.selectResultById(delta_id)
        qtbot.wait(_PAUSE_MS)

        # Act — return to Search tab.
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert — the search results are restored and the originally selected
        # non-zero row is still reflected in currentResultRow.
        assert controller.totalResults == len(_IMAGES)
        assert controller.currentResultRow == search_row_before
        assert search_model.get_path(controller.currentResultRow) == search_path_before

    def test_leave_browse_tab_restores_correct_image_after_index_insert(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — select a non-zero row and record its image id.
        controller, search_model, folder_a, folder_b = controller_with_images
        controller.selectResult(2)
        qtbot.wait(_PAUSE_MS)
        selected_id = search_model.get_image_id(controller.currentResultRow)
        selected_path = search_model.get_path(controller.currentResultRow)
        assert selected_id is not None

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b))
        qtbot.wait(_PAUSE_MS)

        # Simulate the indexer inserting a new image that sorts before the
        # selected one, which would shift the saved row number by 1.
        new_img = folder_a / "aardvark.jpg"
        Image.new("RGB", (32, 32)).save(str(new_img), format="JPEG")
        stat = new_img.stat()
        repo = controller._repo  # type: ignore[attr-defined]
        repo.upsert_image(str(new_img), "aardvark.jpg", stat.st_mtime, stat.st_size, {}, "")
        repo.commit()

        # Act — return to Search tab; the row number is now stale.
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert — the correct image (by id) is selected, not the shifted row.
        assert search_model.get_path(controller.currentResultRow) == selected_path

    def test_leave_browse_tab_currentProxyResultRow_correct_when_loadedResultsChanged_fires(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        """currentProxyResultRow must already reflect the restored image at the
        moment loadedResultsChanged is emitted, not after a deferred call.

        Regression: selectResultById was previously called *after* the emit,
        so QML's onLoadedResultsChanged captured a stale proxy row into
        Qt.callLater and scrolled to the wrong image.  The fix moves
        selection to before the emit.
        """
        # Arrange — select row 2 (non-zero) so the test can distinguish
        # "correctly restored" from "coincidentally row 0".
        controller, search_model, _, folder_b = controller_with_images
        controller.selectResult(2)
        qtbot.wait(_PAUSE_MS)
        expected_proxy_row = controller.currentProxyResultRow
        expected_path = search_model.get_path(controller.currentResultRow)
        assert expected_path is not None
        assert expected_proxy_row > 0, "need a non-zero proxy row for this test to be meaningful"

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b))
        qtbot.wait(_PAUSE_MS)

        # Connect a listener BEFORE triggering the restore so we can capture
        # currentProxyResultRow synchronously inside the signal handler.
        captured_proxy_row: list[int] = []

        def _on_loaded() -> None:
            captured_proxy_row.append(controller.currentProxyResultRow)

        controller.loadedResultsChanged.connect(_on_loaded)

        # Act — return to Search tab.
        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=3000):
            controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        controller.loadedResultsChanged.disconnect(_on_loaded)

        # Assert — the proxy row was already correct when the signal fired
        # (not deferred), and the correct image is selected afterwards.
        assert len(captured_proxy_row) > 0, "loadedResultsChanged was never emitted"
        assert captured_proxy_row[-1] == expected_proxy_row
        assert search_model.get_path(controller.currentResultRow) == expected_path

    def test_browseFolder_with_target_id_loads_target_page_immediately(
        self,
        qtbot: QtBot,
        tmp_path: Path,
    ) -> None:
        """browseFolder(folder, target_id) should load the slice containing the
        target image directly instead of paging from row 0.
        """
        from exif_turbo.ui.models.exif_list_model import ExifListModel
        from exif_turbo.ui.models.folder_list_model import FolderListModel
        from exif_turbo.ui.models.settings_model import SettingsModel

        folder = tmp_path / "large_folder"
        folder.mkdir()

        repo = ImageIndexRepository(tmp_path / "large.db", key="")
        # Index 55 images so the last one is on page 2 (page size = 50).
        for i in range(55):
            fname = f"img_{i:04d}.jpg"
            img_path = folder / fname
            Image.new("RGB", (8, 8)).save(str(img_path), format="JPEG")
            stat = img_path.stat()
            repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, {}, "")
        repo.commit()

        # The last image by filename sort order will be on page 2.
        target_fname = "img_0054.jpg"
        target_path = str(folder / target_fname)
        repo_r = ImageIndexRepository(tmp_path / "large.db", key="")
        rows = repo_r.search_images("", 200, 0, sort_by="filename")
        target_id = next(r[0] for r in rows if r[2] == target_fname)
        repo_r.close()
        repo.close()

        search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
        controller = AppController(
            tmp_path / "large.db", search_model,
            ExifListModel(), FolderListModel(),
            SettingsModel(tmp_path / "settings.json"),
        )
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.unlock("")
        qtbot.wait(_PAUSE_MS)

        controller.selectResult(10)
        qtbot.wait(_PAUSE_MS)
        assert controller.currentResultRow == 10

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.browseFolder(str(folder), target_id)
        qtbot.wait(_PAUSE_MS)

        # Act
        proxy_row = controller.selectResultById(target_id)

        # Assert — the initial Browse slice already contains the target.
        assert proxy_row >= 0
        assert search_model.get_path(controller.currentResultRow) == target_path
        assert search_model.rowCount() < 50

        controller.close()
        qtbot.wait(100)

    def test_browseFolder_with_target_id_load_previous_prepends_earlier_rows(
        self,
        qtbot: QtBot,
        tmp_path: Path,
    ) -> None:
        # Arrange
        folder = tmp_path / "large_folder_prev"
        folder.mkdir()

        repo = ImageIndexRepository(tmp_path / "large_prev.db", key="")
        for i in range(55):
            fname = f"img_{i:04d}.jpg"
            img_path = folder / fname
            Image.new("RGB", (8, 8)).save(str(img_path), format="JPEG")
            stat = img_path.stat()
            repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, {}, "")
        repo.commit()

        target_fname = "img_0054.jpg"
        target_path = str(folder / target_fname)
        rows = repo.search_images("", 200, 0, sort_by="filename")
        target_id = next(r[0] for r in rows if r[2] == target_fname)
        repo.close()

        search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
        controller = AppController(
            tmp_path / "large_prev.db", search_model,
            ExifListModel(), FolderListModel(),
            SettingsModel(tmp_path / "settings.json"),
        )
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.unlock("")
        qtbot.wait(_PAUSE_MS)

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.browseFolder(str(folder), target_id)
        qtbot.wait(_PAUSE_MS)

        initial_first_path = search_model.get_path(0)
        assert initial_first_path != str(folder / "img_0000.jpg")
        assert controller.selectResultById(target_id) >= 0
        assert search_model.get_path(controller.currentResultRow) == target_path

        # Act
        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            controller.loadPrevious()
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert search_model.get_path(0) == str(folder / "img_0000.jpg")
        assert search_model.get_path(controller.currentResultRow) == target_path
        assert search_model.rowCount() == 55

        controller.close()
        qtbot.wait(100)


# ── Helpers ───────────────────────────────────────────────────────────────────


def search_model_path(controller: AppController) -> str | None:
    """Return the file path of the currently selected result."""
    from exif_turbo.ui.models.search_list_model import SearchListModel
    model: SearchListModel = controller._search_model  # type: ignore[attr-defined]
    return model.get_path(controller.currentResultRow)


def click_search_result_browse_button(window: QQuickWindow, results_list: QQuickItem) -> None:
    """Click the Browse pill on the first visible Search-result card."""
    click_pos = results_list.mapToScene(
        QPointF(
            float(results_list.property("width")) - 72.0,
            190.0,
        )
    )
    QTest.mouseClick(
        window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(click_pos.x()), int(click_pos.y())),
    )


@pytest.fixture
def browse_navigation_window(
    qtbot: QtBot,
    controller_with_images: tuple[AppController, SearchListModel, Path, Path],
) -> Generator[tuple[AppController, SearchListModel, QQmlApplicationEngine, object], None, None]:
    """Full QML window wired to the existing browse-navigation controller."""
    controller, search_model, _, _ = controller_with_images
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings = SettingsModel(search_model.cache_dir.parent / "qml-settings.json")
    filter_proxy = CheckedFilterProxyModel()
    filter_proxy.setSourceModel(search_model)
    controller.set_filter_proxy(filter_proxy)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("filteredSearchModel", filter_proxy)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel", settings)
    ctx.setContextProperty("thirdPartyLicensesHtml", "")
    ctx.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
    root = engine.rootObjects()[0]

    yield controller, search_model, engine, root

    engine.deleteLater()
    qtbot.wait(100)


class TestBrowseNavigationQml:
    def test_entering_browse_tab_does_not_start_blocking_folder_reload(
        self,
        qtbot: QtBot,
        browse_navigation_window: tuple[AppController, SearchListModel, QQmlApplicationEngine, object],
    ) -> None:
        # Arrange
        controller, _, _, root = browse_navigation_window
        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        assert tab_bar is not None
        assert controller.isSearching is False

        # Act
        tab_bar.setProperty("currentIndex", 1)
        qtbot.wait(100)

        # Assert
        assert controller.isSearching is False

    def test_browse_jump_loading_state_hides_browse_content_until_jump_completes(
        self,
        qtbot: QtBot,
        browse_navigation_window: tuple[AppController, SearchListModel, QQmlApplicationEngine, object],
    ) -> None:
        # Arrange
        _, _, _, root = browse_navigation_window
        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        busy_overlay = root.findChild(QQuickItem, "searchBusyOverlay")
        browse_content = root.findChild(QQuickItem, "browseContentSplit")
        assert tab_bar is not None
        assert busy_overlay is not None
        assert browse_content is not None

        tab_bar.setProperty("currentIndex", 1)
        qtbot.wait(50)

        # Act
        root.setProperty("_pendingBrowseTargetId", 123)
        qtbot.wait(10)

        # Assert
        assert bool(root.property("_browseJumpLoading")) is True
        assert bool(busy_overlay.property("visible")) is True
        assert float(browse_content.property("opacity")) == 0.0

        # Act
        root.setProperty("_pendingBrowseTargetId", -1)
        root.setProperty("_pendingBrowseScrollRow", 7)
        qtbot.wait(10)

        # Assert
        assert bool(root.property("_browseJumpLoading")) is True
        assert float(browse_content.property("opacity")) == 0.0

        # Act
        root.setProperty("_pendingBrowseScrollRow", -1)
        qtbot.wait(10)

        # Assert
        assert bool(root.property("_browseJumpLoading")) is False
        assert bool(busy_overlay.property("visible")) is False
        assert float(browse_content.property("opacity")) == 1.0

    def test_browse_jump_pending_target_retries_until_image_available(
        self,
        qtbot: QtBot,
        browse_navigation_window: tuple[AppController, SearchListModel, QQmlApplicationEngine, object],
    ) -> None:
        # Arrange
        controller, search_model, _, root = browse_navigation_window
        target_id = search_model.get_image_id(0)
        target_path = search_model.get_path(0)
        assert target_id is not None
        assert target_path is not None

        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        assert tab_bar is not None
        tab_bar.setProperty("currentIndex", 1)
        qtbot.wait(50)

        saved_rows = list(search_model._rows)  # type: ignore[attr-defined]
        search_model.set_rows([])
        root.setProperty("_pendingBrowseTargetId", target_id)

        # Act
        controller.loadedResultsChanged.emit()
        qtbot.wait(50)

        # Assert
        assert root.property("_pendingBrowseTargetId") == target_id

        # Arrange
        search_model.set_rows(saved_rows)

        # Act
        controller.loadedResultsChanged.emit()
        qtbot.wait(100)

        # Assert
        assert root.property("_pendingBrowseTargetId") == -1
        assert search_model.get_path(controller.currentResultRow) == target_path

    def test_browse_jump_scrolls_large_folder_to_target_row(
        self,
        qtbot: QtBot,
        tmp_path: Path,
    ) -> None:
        # Arrange
        folder = tmp_path / "large_folder"
        folder.mkdir()

        repo = ImageIndexRepository(tmp_path / "large_qml.db", key="")
        for i in range(55):
            fname = f"img_{i:04d}.jpg"
            img_path = folder / fname
            Image.new("RGB", (8, 8)).save(str(img_path), format="JPEG")
            stat = img_path.stat()
            repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, {}, "")
        repo.commit()
        rows = repo.search_images("", 200, 0, sort_by="filename")
        target_fname = "img_0054.jpg"
        target_row = next(r for r in rows if r[2] == target_fname)
        target_id = target_row[0]
        target_path = target_row[1]
        repo.close()

        search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
        exif_model = ExifListModel()
        folder_model = FolderListModel()
        settings = SettingsModel(tmp_path / "qml-settings.json")
        controller = AppController(
            tmp_path / "large_qml.db",
            search_model,
            exif_model,
            folder_model,
            settings,
        )
        filter_proxy = CheckedFilterProxyModel()
        filter_proxy.setSourceModel(search_model)
        controller.set_filter_proxy(filter_proxy)

        engine = QQmlApplicationEngine()
        engine.addImageProvider("preview", PreviewImageProvider())
        engine.addImageProvider("raw", RawImageProvider())
        ctx = engine.rootContext()
        ctx.setContextProperty("controller", controller)
        ctx.setContextProperty("searchModel", search_model)
        ctx.setContextProperty("filteredSearchModel", filter_proxy)
        ctx.setContextProperty("exifModel", exif_model)
        ctx.setContextProperty("folderListModel", folder_model)
        ctx.setContextProperty("settingsModel", settings)
        ctx.setContextProperty("thirdPartyLicensesHtml", "")
        ctx.setContextProperty("userManualUrl", "")
        engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

        qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
        root = engine.rootObjects()[0]
        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        browse_list = root.findChild(QQuickItem, "browseImageList")
        assert tab_bar is not None
        assert browse_list is not None

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.unlock("")
        qtbot.wait(_PAUSE_MS)

        root.setProperty("_pendingBrowseTargetId", target_id)

        # Act
        tab_bar.setProperty("currentIndex", 1)
        controller.browseFolder(str(folder), target_id)
        qtbot.waitUntil(lambda: root.property("_pendingBrowseTargetId") == -1, timeout=5000)
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert search_model.get_path(controller.currentResultRow) == target_path
        assert browse_list.property("currentIndex") == controller.currentProxyResultRow
        assert float(browse_list.property("contentY")) > 0.0

        engine.deleteLater()
        controller.close()
        qtbot.wait(100)

    def test_browse_button_click_large_folder_opens_target_slice(
        self,
        qtbot: QtBot,
        tmp_path: Path,
    ) -> None:
        # Arrange
        folder = tmp_path / "large_folder_search"
        folder.mkdir()

        target_fname = "img_0054.jpg"
        target_path = str(folder / target_fname)
        repo = ImageIndexRepository(tmp_path / "large_qml_search.db", key="")
        for i in range(55):
            fname = f"img_{i:04d}.jpg"
            img_path = folder / fname
            Image.new("RGB", (8, 8)).save(str(img_path), format="JPEG")
            stat = img_path.stat()
            text = fname
            if fname == target_fname:
                text = f"{fname} needle"
            repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, {}, text)
        repo.commit()
        repo.close()

        search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
        exif_model = ExifListModel()
        folder_model = FolderListModel()
        settings = SettingsModel(tmp_path / "qml-search-settings.json")
        controller = AppController(
            tmp_path / "large_qml_search.db",
            search_model,
            exif_model,
            folder_model,
            settings,
        )
        filter_proxy = CheckedFilterProxyModel()
        filter_proxy.setSourceModel(search_model)
        controller.set_filter_proxy(filter_proxy)

        engine = QQmlApplicationEngine()
        engine.addImageProvider("preview", PreviewImageProvider())
        engine.addImageProvider("raw", RawImageProvider())
        ctx = engine.rootContext()
        ctx.setContextProperty("controller", controller)
        ctx.setContextProperty("searchModel", search_model)
        ctx.setContextProperty("filteredSearchModel", filter_proxy)
        ctx.setContextProperty("exifModel", exif_model)
        ctx.setContextProperty("folderListModel", folder_model)
        ctx.setContextProperty("settingsModel", settings)
        ctx.setContextProperty("thirdPartyLicensesHtml", "")
        ctx.setContextProperty("userManualUrl", "")
        engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

        qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
        root = engine.rootObjects()[0]
        qml_window: QQuickWindow = root  # type: ignore[assignment]
        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        results_list = root.findChild(QQuickItem, "resultsList")
        browse_list = root.findChild(QQuickItem, "browseImageList")
        assert tab_bar is not None
        assert results_list is not None
        assert browse_list is not None

        qml_window.setVisible(True)
        try:
            qtbot.waitExposed(qml_window, timeout=3000)
        except Exception:
            qtbot.wait(100)

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.unlock("")
        qtbot.wait(_PAUSE_MS)

        # Act
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.search("needle")
        qtbot.wait(_PAUSE_MS)
        assert search_model.rowCount() == 1

        click_search_result_browse_button(qml_window, results_list)
        qtbot.waitUntil(lambda: tab_bar.property("currentIndex") == 1, timeout=5000)
        qtbot.waitUntil(lambda: root.property("_pendingBrowseTargetId") == -1, timeout=5000)
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.totalResults == 55
        assert search_model.get_path(controller.currentResultRow) == target_path
        assert browse_list.property("currentIndex") == controller.currentProxyResultRow
        assert float(browse_list.property("contentY")) > 0.0
        assert search_model.rowCount() < controller.totalResults

        engine.deleteLater()
        controller.close()
        qtbot.wait(100)

    def test_ai_browse_button_click_large_folder_opens_target_slice(
        self,
        qtbot: QtBot,
        tmp_path: Path,
    ) -> None:
        # Arrange
        folder = tmp_path / "large_folder_ai"
        folder.mkdir()

        target_fname = "img_0054.jpg"
        repo = ImageIndexRepository(tmp_path / "large_qml_ai.db", key="")
        for i in range(55):
            fname = f"img_{i:04d}.jpg"
            img_path = folder / fname
            Image.new("RGB", (8, 8)).save(str(img_path), format="JPEG")
            stat = img_path.stat()
            repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, {}, fname)
        repo.commit()
        rows = repo.search_images("", 200, 0, sort_by="filename")
        target_row = next(row for row in rows if row[2] == target_fname)
        target_path = target_row[1]
        repo.close()

        search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
        exif_model = ExifListModel()
        folder_model = FolderListModel()
        settings = SettingsModel(tmp_path / "qml-ai-settings.json")
        controller = AppController(
            tmp_path / "large_qml_ai.db",
            search_model,
            exif_model,
            folder_model,
            settings,
        )
        filter_proxy = CheckedFilterProxyModel()
        filter_proxy.setSourceModel(search_model)
        controller.set_filter_proxy(filter_proxy)

        engine = QQmlApplicationEngine()
        engine.addImageProvider("preview", PreviewImageProvider())
        engine.addImageProvider("raw", RawImageProvider())
        ctx = engine.rootContext()
        ctx.setContextProperty("controller", controller)
        ctx.setContextProperty("searchModel", search_model)
        ctx.setContextProperty("filteredSearchModel", filter_proxy)
        ctx.setContextProperty("exifModel", exif_model)
        ctx.setContextProperty("folderListModel", folder_model)
        ctx.setContextProperty("settingsModel", settings)
        ctx.setContextProperty("thirdPartyLicensesHtml", "")
        ctx.setContextProperty("userManualUrl", "")
        engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

        qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
        root = engine.rootObjects()[0]
        qml_window: QQuickWindow = root  # type: ignore[assignment]
        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        results_list = root.findChild(QQuickItem, "resultsList")
        browse_list = root.findChild(QQuickItem, "browseImageList")
        assert tab_bar is not None
        assert results_list is not None
        assert browse_list is not None

        qml_window.setVisible(True)
        try:
            qtbot.waitExposed(qml_window, timeout=3000)
        except Exception:
            qtbot.wait(100)

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.unlock("")
        qtbot.wait(_PAUSE_MS)

        root.setProperty("_aiSearchMode", True)
        controller.setAiSearchMode(True)

        with patch("exif_turbo.ui.view_models.app_controller.AiSearchWorker.run", autospec=True) as mocked_run:
            def _emit_results(worker: object) -> None:
                worker.results_ready.emit([target_row], 1, [], worker._serial)  # type: ignore[attr-defined]

            mocked_run.side_effect = _emit_results

            # Act
            with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
                controller.aiSearch("needle", "normal")
            qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.isAiSearchMode is True
        assert search_model.rowCount() == 1
        assert search_model.get_path(controller.currentResultRow) == target_path

        # Act
        click_search_result_browse_button(qml_window, results_list)
        qtbot.waitUntil(lambda: tab_bar.property("currentIndex") == 1, timeout=5000)
        qtbot.waitUntil(lambda: root.property("_pendingBrowseTargetId") == -1, timeout=5000)
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.isAiSearchMode is False
        assert controller.totalResults == 55
        assert search_model.get_path(controller.currentResultRow) == target_path
        assert browse_list.property("currentIndex") == controller.currentProxyResultRow
        assert float(browse_list.property("contentY")) > 0.0
        assert search_model.rowCount() < controller.totalResults

        # Act
        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            tab_bar.setProperty("currentIndex", 0)
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.isAiSearchMode is True
        assert search_model.rowCount() == 1
        assert search_model.get_path(controller.currentResultRow) == target_path

        engine.deleteLater()
        controller.close()
        qtbot.wait(100)

    def test_browse_jump_upward_scroll_prefetches_previous_page_before_top_reached(
        self,
        qtbot: QtBot,
        tmp_path: Path,
    ) -> None:
        # Arrange
        folder = tmp_path / "large_folder_upscroll"
        folder.mkdir()

        repo = ImageIndexRepository(tmp_path / "large_qml_upscroll.db", key="")
        for i in range(55):
            fname = f"img_{i:04d}.jpg"
            img_path = folder / fname
            Image.new("RGB", (8, 8)).save(str(img_path), format="JPEG")
            stat = img_path.stat()
            repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, {}, "")
        repo.commit()
        rows = repo.search_images("", 200, 0, sort_by="filename")
        target_row = next(r for r in rows if r[2] == "img_0054.jpg")
        target_id = target_row[0]
        target_path = target_row[1]
        repo.close()

        search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
        exif_model = ExifListModel()
        folder_model = FolderListModel()
        settings = SettingsModel(tmp_path / "qml-upscroll-settings.json")
        controller = AppController(
            tmp_path / "large_qml_upscroll.db",
            search_model,
            exif_model,
            folder_model,
            settings,
        )
        filter_proxy = CheckedFilterProxyModel()
        filter_proxy.setSourceModel(search_model)
        controller.set_filter_proxy(filter_proxy)

        engine = QQmlApplicationEngine()
        engine.addImageProvider("preview", PreviewImageProvider())
        engine.addImageProvider("raw", RawImageProvider())
        ctx = engine.rootContext()
        ctx.setContextProperty("controller", controller)
        ctx.setContextProperty("searchModel", search_model)
        ctx.setContextProperty("filteredSearchModel", filter_proxy)
        ctx.setContextProperty("exifModel", exif_model)
        ctx.setContextProperty("folderListModel", folder_model)
        ctx.setContextProperty("settingsModel", settings)
        ctx.setContextProperty("thirdPartyLicensesHtml", "")
        ctx.setContextProperty("userManualUrl", "")
        engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

        qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
        root = engine.rootObjects()[0]
        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        browse_list = root.findChild(QQuickItem, "browseImageList")
        assert tab_bar is not None
        assert browse_list is not None

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.unlock("")
        qtbot.wait(_PAUSE_MS)

        root.setProperty("_pendingBrowseTargetId", target_id)

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            tab_bar.setProperty("currentIndex", 1)
            controller.browseFolder(str(folder), target_id)
        qtbot.waitUntil(lambda: root.property("_pendingBrowseTargetId") == -1, timeout=5000)
        qtbot.wait(_PAUSE_MS)

        initial_count = search_model.rowCount()
        assert initial_count < controller.totalResults
        assert float(browse_list.property("contentY")) > 0.0
        initial_content_y = float(browse_list.property("contentY"))

        # Act
        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            browse_list.setProperty("contentY", initial_content_y - 1.0)
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert search_model.rowCount() > initial_count
        assert search_model.get_path(controller.currentResultRow) == target_path
        assert float(browse_list.property("contentY")) > 0.0

        engine.deleteLater()
        controller.close()
        qtbot.wait(100)

    def test_browse_downward_scroll_prefetches_next_page_before_bottom_reached(
        self,
        qtbot: QtBot,
        tmp_path: Path,
    ) -> None:
        # Arrange
        folder = tmp_path / "large_folder_downprefetch"
        folder.mkdir()

        repo = ImageIndexRepository(tmp_path / "large_qml_downprefetch.db", key="")
        for i in range(180):
            fname = f"img_{i:04d}.jpg"
            img_path = folder / fname
            Image.new("RGB", (8, 8)).save(str(img_path), format="JPEG")
            stat = img_path.stat()
            repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, {}, "")
        repo.commit()
        repo.close()

        search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
        exif_model = ExifListModel()
        folder_model = FolderListModel()
        settings = SettingsModel(tmp_path / "qml-downprefetch-settings.json")
        controller = AppController(
            tmp_path / "large_qml_downprefetch.db",
            search_model,
            exif_model,
            folder_model,
            settings,
        )
        filter_proxy = CheckedFilterProxyModel()
        filter_proxy.setSourceModel(search_model)
        controller.set_filter_proxy(filter_proxy)

        engine = QQmlApplicationEngine()
        engine.addImageProvider("preview", PreviewImageProvider())
        engine.addImageProvider("raw", RawImageProvider())
        ctx = engine.rootContext()
        ctx.setContextProperty("controller", controller)
        ctx.setContextProperty("searchModel", search_model)
        ctx.setContextProperty("filteredSearchModel", filter_proxy)
        ctx.setContextProperty("exifModel", exif_model)
        ctx.setContextProperty("folderListModel", folder_model)
        ctx.setContextProperty("settingsModel", settings)
        ctx.setContextProperty("thirdPartyLicensesHtml", "")
        ctx.setContextProperty("userManualUrl", "")
        engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

        qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
        root = engine.rootObjects()[0]
        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        browse_list = root.findChild(QQuickItem, "browseImageList")
        assert tab_bar is not None
        assert browse_list is not None

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.unlock("")
        qtbot.wait(_PAUSE_MS)

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            tab_bar.setProperty("currentIndex", 1)
            controller.browseFolder(str(folder))
        qtbot.wait(_PAUSE_MS)

        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            controller.loadMore()
        qtbot.wait(_PAUSE_MS)

        initial_count = search_model.rowCount()
        assert initial_count == 100
        assert float(browse_list.property("contentY")) == 0.0

        row_height = int(root.property("_browseRowHeight"))
        visible_rows = max(
            1,
            math.ceil(float(browse_list.property("height")) / row_height),
        )
        before_prefetch_row = max(0, 49 - visible_rows)
        prefetch_row = max(0, 50 - visible_rows)

        # Act
        browse_list.setProperty("contentY", float(before_prefetch_row * row_height))
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert search_model.rowCount() == initial_count

        # Act
        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            browse_list.setProperty("contentY", float(prefetch_row * row_height))
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert search_model.rowCount() == initial_count + 50
        assert float(browse_list.property("contentY")) > 0.0

        engine.deleteLater()
        controller.close()
        qtbot.wait(100)

    def test_browse_down_arrow_prefetches_next_page_before_loaded_end(
        self,
        qtbot: QtBot,
        tmp_path: Path,
    ) -> None:
        # Arrange
        folder = tmp_path / "large_folder_downkeyprefetch"
        folder.mkdir()

        repo = ImageIndexRepository(tmp_path / "large_qml_downkeyprefetch.db", key="")
        for i in range(180):
            fname = f"img_{i:04d}.jpg"
            img_path = folder / fname
            Image.new("RGB", (8, 8)).save(str(img_path), format="JPEG")
            stat = img_path.stat()
            repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, {}, "")
        repo.commit()
        repo.close()

        search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
        exif_model = ExifListModel()
        folder_model = FolderListModel()
        settings = SettingsModel(tmp_path / "qml-downkeyprefetch-settings.json")
        controller = AppController(
            tmp_path / "large_qml_downkeyprefetch.db",
            search_model,
            exif_model,
            folder_model,
            settings,
        )
        filter_proxy = CheckedFilterProxyModel()
        filter_proxy.setSourceModel(search_model)
        controller.set_filter_proxy(filter_proxy)

        engine = QQmlApplicationEngine()
        engine.addImageProvider("preview", PreviewImageProvider())
        engine.addImageProvider("raw", RawImageProvider())
        ctx = engine.rootContext()
        ctx.setContextProperty("controller", controller)
        ctx.setContextProperty("searchModel", search_model)
        ctx.setContextProperty("filteredSearchModel", filter_proxy)
        ctx.setContextProperty("exifModel", exif_model)
        ctx.setContextProperty("folderListModel", folder_model)
        ctx.setContextProperty("settingsModel", settings)
        ctx.setContextProperty("thirdPartyLicensesHtml", "")
        ctx.setContextProperty("userManualUrl", "")
        engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

        qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
        root = engine.rootObjects()[0]
        qml_window: QQuickWindow = root  # type: ignore[assignment]
        tab_bar = root.findChild(QQuickItem, "mainTabBar")
        browse_list = root.findChild(QQuickItem, "browseImageList")
        assert tab_bar is not None
        assert browse_list is not None

        qml_window.setVisible(True)
        try:
            qtbot.waitExposed(qml_window, timeout=3000)
        except Exception:
            qtbot.wait(100)

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            controller.unlock("")
        qtbot.wait(_PAUSE_MS)

        with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
            tab_bar.setProperty("currentIndex", 1)
            controller.browseFolder(str(folder))
        qtbot.wait(_PAUSE_MS)

        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            controller.loadMore()
        qtbot.wait(_PAUSE_MS)

        initial_count = search_model.rowCount()
        assert initial_count == 100

        row_height = int(root.property("_browseRowHeight"))
        visible_rows = max(
            1,
            math.ceil(float(browse_list.property("height")) / row_height),
        )
        controller.selectResult(48)
        browse_list.setProperty("contentY", float(max(0, 49 - visible_rows) * row_height))
        qml_window.requestActivate()
        browse_list.setProperty("focus", True)
        qtbot.wait(_PAUSE_MS)

        # Act
        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            QTest.keyClick(qml_window, Qt.Key.Key_Down)
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert search_model.rowCount() == initial_count + 50
        assert controller.currentResultRow == 49

        engine.deleteLater()
        controller.close()
        qtbot.wait(100)
