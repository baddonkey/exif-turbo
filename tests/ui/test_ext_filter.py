"""E2E tests for format / extension filter switching via AppController.

These tests index images of three distinct formats (jpg/jpeg, png, tif) into a
real SQLite database and then drive the controller's setExtFilter slot to verify
that switching filters returns the correct result counts and that clearing the
filter restores all images.

Run with:
    pytest tests/ui/test_ext_filter.py -v -s
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

_PAUSE_MS = 500

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

# Each tuple: (filename, PIL format, camera make)
# After alias normalisation ".jpeg" folds into the "jpg" bucket.
_IMAGES: list[tuple[str, str, str]] = [
    ("alpha.jpg",   "JPEG", "Nikon"),
    ("beta.jpg",    "JPEG", "Canon"),
    ("gamma.jpg",   "JPEG", "Sony"),
    ("delta.jpeg",  "JPEG", "Fuji"),     # ".jpeg" alias → counted under "jpg"
    ("epsilon.png", "PNG",  "Olympus"),
    ("zeta.png",    "PNG",  "Leica"),
    ("eta.tif",     "TIFF", "Epson"),
]

_COUNTS = {"jpg": 4, "png": 2, "tif": 1}  # expected per-format totals
_TOTAL = sum(_COUNTS.values())


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def mixed_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Real indexed DB with images in three formats; created once per module."""
    base = tmp_path_factory.mktemp("ext_filter")
    img_dir = base / "images"
    img_dir.mkdir()

    repo = ImageIndexRepository(base / "mixed.db", key="")
    for fname, pil_fmt, make in _IMAGES:
        img_path = img_dir / fname
        Image.new("RGB", (32, 32), color=(100, 150, 200)).save(str(img_path), format=pil_fmt)
        stat = img_path.stat()
        metadata = {"FileName": fname, "Make": make}
        repo.upsert_image(
            str(img_path), fname, stat.st_mtime, stat.st_size,
            metadata, f"{fname} {make}",
        )

    repo.commit()
    repo.close()
    return base / "mixed.db", base


@pytest.fixture
def window(
    qtbot: QtBot,
    mixed_db: tuple[Path, Path],
) -> Generator[tuple[AppController, SearchListModel], None, None]:
    """Full QML window backed by mixed_db; one fresh window per test."""
    db_path, base = mixed_db

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

    yield controller, search_model

    engine.deleteLater()
    qtbot.wait(200)


def _unlock(controller: AppController, qtbot: QtBot) -> None:
    """Unlock the database and wait for the initial search to complete."""
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_unlock_shows_all_mixed_images(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window

    # Act
    _unlock(controller, qtbot)

    # Assert
    assert controller.totalResults == _TOTAL
    assert search_model.rowCount() == _TOTAL


def test_available_formats_lists_all_three_extensions(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, _ = window
    _unlock(controller, qtbot)

    # Act
    formats: list[dict] = json.loads(controller.availableFormats)
    by_ext = {f["ext"]: f["count"] for f in formats}

    # Assert — jpeg alias must be merged into "jpg" bucket; tif present
    assert by_ext.get("jpg") == _COUNTS["jpg"]
    assert by_ext.get("png") == _COUNTS["png"]
    assert by_ext.get("tif") == _COUNTS["tif"]
    assert "jpeg" not in by_ext, ".jpeg must be merged into jpg bucket, not listed separately"


def test_ext_filter_jpg_returns_jpeg_alias_images_too(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window
    _unlock(controller, qtbot)

    # Act — filter by "jpg"; should include both .jpg and .jpeg files
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("jpg")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == _COUNTS["jpg"]
    assert search_model.rowCount() == _COUNTS["jpg"]
    filenames = [search_model.get_path(i).split("\\")[-1].split("/")[-1]
                 for i in range(search_model.rowCount())]
    assert all(f.endswith((".jpg", ".jpeg")) for f in filenames), filenames


def test_ext_filter_png_returns_only_png_images(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window
    _unlock(controller, qtbot)

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("png")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == _COUNTS["png"]
    assert search_model.rowCount() == _COUNTS["png"]
    filenames = [search_model.get_path(i).split("\\")[-1].split("/")[-1]
                 for i in range(search_model.rowCount())]
    assert all(f.endswith(".png") for f in filenames), filenames


def test_ext_filter_tif_returns_only_tif_images(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window
    _unlock(controller, qtbot)

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("tif")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == _COUNTS["tif"]
    assert search_model.rowCount() == _COUNTS["tif"]
    filenames = [search_model.get_path(i).split("\\")[-1].split("/")[-1]
                 for i in range(search_model.rowCount())]
    assert all(f.endswith(".tif") for f in filenames), filenames


def test_ext_filter_switch_from_jpg_to_png_updates_results(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange — start with jpg filter active
    controller, search_model = window
    _unlock(controller, qtbot)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("jpg")
    qtbot.wait(_PAUSE_MS)
    assert controller.totalResults == _COUNTS["jpg"]

    # Act — switch to png
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("png")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == _COUNTS["png"]
    assert search_model.rowCount() == _COUNTS["png"]


def test_ext_filter_clear_after_filter_restores_all_results(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange — apply a filter first
    controller, search_model = window
    _unlock(controller, qtbot)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("tif")
    qtbot.wait(_PAUSE_MS)
    assert controller.totalResults == _COUNTS["tif"]

    # Act — clear the filter
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == _TOTAL
    assert search_model.rowCount() == _TOTAL


def test_ext_filter_combined_with_text_search(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window
    _unlock(controller, qtbot)
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.search("Nikon")
    qtbot.wait(_PAUSE_MS)
    assert controller.totalResults == 1  # only alpha.jpg

    # Act — add png filter while Nikon query is active; Nikon has no png → 0
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setExtFilter("png")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == 0
    assert search_model.rowCount() == 0
