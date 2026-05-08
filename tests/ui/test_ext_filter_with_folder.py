"""E2E tests for the format-filter / folder-filter interaction.

Reproduces the bug where selecting a format (e.g. TIFF) and then restricting
the search to a folder that contains no images of that format would cause the
format chip row in the UI to disappear, leaving the user unable to switch
back to "All" or another available format.

The expected behaviour:
    * The currently selected ext filter must always remain visible in
      ``availableFormats`` — even when its count in the current scope is 0 —
      so the user can see what is selected and switch away from it.
    * When a folder restriction surfaces other formats, those formats must
      remain selectable.

Run with:
    pytest tests/ui/test_ext_filter_with_folder.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
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

# Two folders:
#   "mixed/" → jpg + png + tif
#   "no_tif/" → jpg + png only (this is the folder that triggers the bug)
_LAYOUT: dict[str, list[tuple[str, str]]] = {
    "mixed": [
        ("a.jpg", "JPEG"),
        ("b.png", "PNG"),
        ("c.tif", "TIFF"),
    ],
    "no_tif": [
        ("d.jpg", "JPEG"),
        ("e.jpg", "JPEG"),
        ("f.png", "PNG"),
    ],
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def two_folder_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, dict[str, Path]]:
    """Indexed DB with two folders, only one of which contains TIFF images."""
    base = tmp_path_factory.mktemp("ext_folder_filter")
    folder_paths: dict[str, Path] = {}

    repo = ImageIndexRepository(base / "two_folder.db", key="")
    for folder_name, files in _LAYOUT.items():
        folder = base / folder_name
        folder.mkdir()
        folder_paths[folder_name] = folder
        for fname, pil_fmt in files:
            img_path = folder / fname
            Image.new("RGB", (16, 16), color=(120, 120, 120)).save(
                str(img_path), format=pil_fmt,
            )
            stat = img_path.stat()
            repo.upsert_image(
                str(img_path), fname, stat.st_mtime, stat.st_size,
                {"FileName": fname}, fname,
            )
    repo.commit()
    repo.close()

    return base / "two_folder.db", base, folder_paths


@pytest.fixture
def window(
    qtbot: QtBot,
    two_folder_db: tuple[Path, Path, dict[str, Path]],
) -> Generator[tuple[AppController, SearchListModel, dict[str, Path]], None, None]:
    db_path, base, folder_paths = two_folder_db

    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings = SettingsModel(base / "settings.json")
    controller = AppController(db_path, search_model, exif_model, folder_model, settings)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel", settings)
    ctx.setContextProperty("thirdPartyLicensesHtml", "")
    ctx.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)

    yield controller, search_model, folder_paths

    controller.close()
    engine.deleteLater()
    qtbot.wait(100)


def _unlock(controller: AppController, qtbot: QtBot) -> None:
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)


def _formats_by_ext(controller: AppController) -> dict[str, int]:
    return {f["ext"]: f["count"] for f in json.loads(controller.availableFormats)}


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_active_ext_filter_remains_visible_when_folder_has_no_matches(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel, dict[str, Path]],
) -> None:
    """The active ext (TIFF) must stay listed even when the scoped folder
    contains zero TIFF files — otherwise the UI hides the chip row and the
    user gets stuck."""
    # Arrange
    controller, _, folders = window
    _unlock(controller, qtbot)

    # Act — pick TIFF first, then restrict to a folder with no TIFFs
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("tif")
    qtbot.wait(_PAUSE_MS)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setSearchFolderFilter(str(folders["no_tif"]))
    qtbot.wait(_PAUSE_MS)

    # Assert — the search is empty …
    assert controller.totalResults == 0
    # … but the active filter stays exposed in availableFormats with count 0,
    # so the chip row still has something to render.
    by_ext = _formats_by_ext(controller)
    assert "tif" in by_ext, (
        f"Active ext filter must remain in availableFormats; got {by_ext!r}"
    )
    assert by_ext["tif"] == 0


def test_other_formats_in_folder_are_still_selectable(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel, dict[str, Path]],
) -> None:
    """When TIFF is selected and folder has only jpg+png, both jpg and png
    must appear so the user can switch to one of them."""
    # Arrange
    controller, _, folders = window
    _unlock(controller, qtbot)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("tif")
    qtbot.wait(_PAUSE_MS)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setSearchFolderFilter(str(folders["no_tif"]))
    qtbot.wait(_PAUSE_MS)

    # Act
    by_ext = _formats_by_ext(controller)

    # Assert
    assert by_ext.get("jpg") == 2, by_ext
    assert by_ext.get("png") == 1, by_ext


def test_user_can_recover_by_switching_to_other_format(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel, dict[str, Path]],
) -> None:
    """End-to-end: get into the broken state, then switch to JPG → results
    must come back. This is what the user should be able to do via the chip
    row in the UI."""
    # Arrange — into the broken state
    controller, search_model, folders = window
    _unlock(controller, qtbot)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("tif")
    qtbot.wait(_PAUSE_MS)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setSearchFolderFilter(str(folders["no_tif"]))
    qtbot.wait(_PAUSE_MS)
    assert controller.totalResults == 0

    # Act — recover by switching to jpg
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("jpg")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == 2
    assert search_model.rowCount() == 2


def test_user_can_recover_by_clearing_format_filter(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel, dict[str, Path]],
) -> None:
    """End-to-end: get into the broken state, then clear the format filter →
    all jpg+png images in the folder must come back."""
    # Arrange
    controller, search_model, folders = window
    _unlock(controller, qtbot)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("tif")
    qtbot.wait(_PAUSE_MS)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setSearchFolderFilter(str(folders["no_tif"]))
    qtbot.wait(_PAUSE_MS)
    assert controller.totalResults == 0

    # Act — clear ext filter
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("")
    qtbot.wait(_PAUSE_MS)

    # Assert — folder still has 3 files (2 jpg + 1 png)
    assert controller.totalResults == 3
    assert search_model.rowCount() == 3


def test_clearing_folder_filter_restores_full_format_list(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel, dict[str, Path]],
) -> None:
    """Sanity check: once the folder filter is removed, TIFF must come back
    with its real count, and the chip row should look normal again."""
    # Arrange — broken state
    controller, _, folders = window
    _unlock(controller, qtbot)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("tif")
    qtbot.wait(_PAUSE_MS)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setSearchFolderFilter(str(folders["no_tif"]))
    qtbot.wait(_PAUSE_MS)

    # Act — clear folder filter
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.clearSearchFolderFilters()
    qtbot.wait(_PAUSE_MS)

    # Assert
    by_ext = _formats_by_ext(controller)
    assert by_ext.get("tif") == 1
    assert by_ext.get("jpg") == 3
    assert by_ext.get("png") == 2
