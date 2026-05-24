"""E2E tests for the "Browse →" / "← Search" cross-tab navigation feature.

Covers:
  * selectResultByPath — finds an image by path, selects it, returns proxy row
  * selectResultByPath with an unknown path — returns -1
  * Full flow: search results → enterBrowseTab + browseFolder →
    selectResultByPath locates and selects the correct image in Browse
  * Returning to Search after Browse navigation preserves the previously
    selected search result row

Run with:
    pytest tests/ui/test_browse_navigation.py -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.view_models.app_controller import AppController

_PAUSE_MS = 300

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


# ── selectResultByPath ────────────────────────────────────────────────────────


class TestSelectResultByPath:
    def test_selectResultByPath_known_path_returns_proxy_row(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — all 5 images are loaded; pick any path from the model.
        controller, search_model, _, _ = controller_with_images
        target_source_row = 2
        target_path = search_model.get_path(target_source_row)
        assert target_path is not None

        # Act
        proxy_row = controller.selectResultByPath(target_path)

        # Assert — a valid (≥ 0) proxy row is returned
        assert proxy_row >= 0

    def test_selectResultByPath_unknown_path_returns_minus_one(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, _ = controller_with_images

        # Act
        result = controller.selectResultByPath("/no/such/image.jpg")

        # Assert
        assert result == -1

    def test_selectResultByPath_selects_matching_image(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — pick the last image in the model (non-trivial row index).
        controller, search_model, _, _ = controller_with_images
        last_row = search_model.rowCount() - 1
        target_path = search_model.get_path(last_row)
        assert target_path is not None

        # Act
        controller.selectResultByPath(target_path)
        qtbot.wait(_PAUSE_MS)

        # Assert — the controller's selected source row matches the target.
        assert search_model.get_path(controller.currentResultRow) == target_path

    def test_selectResultByPath_proxy_row_matches_currentProxyResultRow(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, search_model, _, _ = controller_with_images
        target_path = search_model.get_path(1)
        assert target_path is not None

        # Act
        returned_proxy_row = controller.selectResultByPath(target_path)
        qtbot.wait(_PAUSE_MS)

        # Assert — returned value matches the property exposed to QML.
        assert returned_proxy_row == controller.currentProxyResultRow


# ── Full Browse navigation flow ───────────────────────────────────────────────


class TestBrowseNavigation:
    def test_selectResultByPath_after_browseFolder_selects_image_in_browse(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — simulate the "Browse →" button: save the path of a
        # folder_b image, enter Browse, load that folder.
        controller, _, _, folder_b = controller_with_images
        target_path = str(folder_b / "delta.jpg")

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b))
        qtbot.wait(_PAUSE_MS)

        # Act — QML would call this once browseImageList.countChanged fires.
        proxy_row = controller.selectResultByPath(target_path)
        qtbot.wait(_PAUSE_MS)

        # Assert — the image is found and selected.
        assert proxy_row >= 0
        assert search_model_path(controller) == target_path

    def test_selectResultByPath_image_not_in_current_browse_folder_returns_minus_one(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — browse folder_b, but look for a folder_a image.
        controller, _, folder_a, folder_b = controller_with_images
        path_from_other_folder = str(folder_a / "alpha.jpg")

        controller.enterBrowseTab("")
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_b))
        qtbot.wait(_PAUSE_MS)

        # Act
        result = controller.selectResultByPath(path_from_other_folder)

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
        controller.selectResultByPath(str(folder_b / "delta.jpg"))
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def search_model_path(controller: AppController) -> str | None:
    """Return the file path of the currently selected result."""
    from exif_turbo.ui.models.search_list_model import SearchListModel
    model: SearchListModel = controller._search_model  # type: ignore[attr-defined]
    return model.get_path(controller.currentResultRow)
