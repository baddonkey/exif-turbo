"""E2E tests for Search-state save/restore around the Browse tab.

Verifies that switching from the Search tab to the Browse tab:
  * snapshots the current query, search-folder-filters and extension filter
  * clears those filters so Browse shows un-filtered folder contents
and that returning to the Search tab restores the snapshot exactly.

Run with:
    pytest tests/ui/test_browse_tab_state.py -v
"""

from __future__ import annotations

import json
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


# Each tuple: (subdir, filename, format, camera make)
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
    """A real AppController backed by a SQLite DB containing two folders of images.

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


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestEnterBrowseTabSnapshot:
    def test_enter_browse_tab_clears_query_text(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, _ = controller_with_images
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.search("Canon")
        qtbot.wait(_PAUSE_MS)
        assert controller.totalResults == 3  # 3 Canon images

        # Act — entering Browse must clear the active query filter
        controller.enterBrowseTab("Canon")
        qtbot.wait(_PAUSE_MS)

        # Assert — controller has no query applied; selecting a folder will
        # show its full contents, not the Search-filtered subset.
        assert controller._query_text == ""

    def test_enter_browse_tab_clears_search_folder_filters(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, folder_a, _ = controller_with_images
        with qtbot.waitSignal(controller.searchFolderFiltersChanged, timeout=3000):
            controller.toggleSearchFolderFilter(str(folder_a))
        qtbot.wait(_PAUSE_MS)
        assert json.loads(controller.searchFolderFilters) == [str(folder_a)]

        # Act
        with qtbot.waitSignal(controller.searchFolderFiltersChanged, timeout=3000):
            controller.enterBrowseTab("")
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert json.loads(controller.searchFolderFilters) == []

    def test_enter_browse_tab_clears_ext_filter(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, _ = controller_with_images
        with qtbot.waitSignal(controller.extFilterChanged, timeout=3000):
            controller.setExtFilter("jpg")
        qtbot.wait(_PAUSE_MS)
        assert controller.extFilter == "jpg"

        # Act
        with qtbot.waitSignal(controller.extFilterChanged, timeout=3000):
            controller.enterBrowseTab("")
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.extFilter == ""

    def test_second_enter_browse_tab_does_not_overwrite_snapshot(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — establish search state, snapshot it, then mutate filters
        # while in Browse, then call enterBrowseTab again (e.g. Browse ->
        # Settings -> Browse) and verify the original snapshot survives.
        controller, _, _, _ = controller_with_images
        controller.search("Canon")
        qtbot.wait(_PAUSE_MS)
        controller.enterBrowseTab("Canon")
        qtbot.wait(_PAUSE_MS)
        # Pretend the user did something in Browse that set a transient query.
        controller._query_text = "transient"

        # Act — second entry must NOT overwrite the original snapshot.
        controller.enterBrowseTab("transient")
        qtbot.wait(_PAUSE_MS)

        # Assert — leave restores the FIRST snapshot ("Canon"), not "transient".
        saved = controller.leaveBrowseTab()
        assert saved == "Canon"


class TestLeaveBrowseTabRestore:
    def test_leave_browse_tab_restores_query_text(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, _ = controller_with_images
        controller.search("Canon")
        qtbot.wait(_PAUSE_MS)
        controller.enterBrowseTab("Canon")
        qtbot.wait(_PAUSE_MS)

        # Act
        saved = controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert saved == "Canon"
        assert controller._query_text == "Canon"

    def test_leave_browse_tab_restores_search_folder_filters(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, folder_a, folder_b = controller_with_images
        controller.toggleSearchFolderFilter(str(folder_a))
        controller.toggleSearchFolderFilter(str(folder_b))
        qtbot.wait(_PAUSE_MS)
        original = sorted(json.loads(controller.searchFolderFilters))

        # Act
        controller.enterBrowseTab("")
        qtbot.wait(_PAUSE_MS)
        controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert
        restored = sorted(json.loads(controller.searchFolderFilters))
        assert restored == original

    def test_leave_browse_tab_restores_ext_filter(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, _, _ = controller_with_images
        controller.setExtFilter("png")
        qtbot.wait(_PAUSE_MS)

        # Act
        controller.enterBrowseTab("")
        qtbot.wait(_PAUSE_MS)
        controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.extFilter == "png"

    def test_leave_browse_tab_clears_folder_filter(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — pick a Browse folder so folder_filter is non-empty.
        controller, _, folder_a, _ = controller_with_images
        controller.enterBrowseTab("")
        controller.browseFolder(str(folder_a))
        qtbot.wait(_PAUSE_MS)
        assert controller.folderFilter == str(folder_a)

        # Act
        controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert controller.folderFilter == ""

    def test_leave_browse_tab_without_snapshot_returns_empty_string(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — fresh controller, no snapshot held.
        controller, _, _, _ = controller_with_images

        # Act
        saved = controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert
        assert saved == ""


class TestBrowseTabShowsUnfilteredFolderContents:
    def test_browse_folder_after_enter_shows_all_folder_images(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange — user had an extension filter active on Search tab.
        controller, search_model, folder_a, _ = controller_with_images
        controller.setExtFilter("jpg")
        qtbot.wait(_PAUSE_MS)
        assert controller.totalResults == 3  # 3 jpgs total across both folders

        # Act — switch to Browse and pick folder_a (which has 2 jpg + 1 png).
        controller.enterBrowseTab("")
        qtbot.wait(_PAUSE_MS)
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.browseFolder(str(folder_a))
        qtbot.wait(_PAUSE_MS)

        # Assert — Browse shows ALL 3 images in folder_a, not only the jpgs.
        assert controller.totalResults == 3
        assert search_model.rowCount() == 3

    def test_returning_to_search_re_applies_ext_filter(
        self,
        qtbot: QtBot,
        controller_with_images: tuple[AppController, SearchListModel, Path, Path],
    ) -> None:
        # Arrange
        controller, _, folder_a, _ = controller_with_images
        controller.setExtFilter("png")
        qtbot.wait(_PAUSE_MS)
        assert controller.totalResults == 2  # 2 png images total

        # Act — go to Browse, pick a folder, then return to Search.
        controller.enterBrowseTab("")
        controller.browseFolder(str(folder_a))
        qtbot.wait(_PAUSE_MS)
        with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
            controller.leaveBrowseTab()
        qtbot.wait(_PAUSE_MS)

        # Assert — png filter is restored, total back to 2.
        assert controller.extFilter == "png"
        assert controller.totalResults == 2
