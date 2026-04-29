"""pytest-qt integration tests for AppController.

Each test opens the full QML window, drives it through the controller, and
pauses long enough for the window to be visible on screen.

Run with:
    pytest tests/ui/ -v -s
"""

from __future__ import annotations

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

# How long to leave the window visible between steps (ms).
_PAUSE_MS = 700

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

# Five cameras with distinct makes so tests can filter each group.
_CAMERAS = [
    ("canon_r5.jpg",  "Canon",     "EOS R5",      "2024:01:15 10:30:00"),
    ("nikon_z9.jpg",  "Nikon",     "Z 9",         "2024:02:20 14:00:00"),
    ("sony_a7iv.jpg", "Sony",      "A7 IV",       "2024:03:10 08:45:00"),
    ("canon_5d.jpg",  "Canon",     "5D Mark IV",  "2024:04:05 16:20:00"),
    ("fuji_xt5.jpg",  "Fujifilm",  "X-T5",        "2024:05:01 11:00:00"),
]
_COLORS = [
    (220,  50,  50),
    ( 50, 100, 200),
    (200,  50, 100),
    ( 50, 200, 100),
    (180, 120,  30),
]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Real indexed DB with five camera images; created once for the whole module."""
    base = tmp_path_factory.mktemp("ui_demo")
    img_dir = base / "images"
    img_dir.mkdir()

    repo = ImageIndexRepository(base / "demo.db", key="")
    for (fname, make, model, date), color in zip(_CAMERAS, _COLORS):
        img_path = img_dir / fname
        Image.new("RGB", (32, 32), color=color).save(str(img_path), format="JPEG")
        stat = img_path.stat()
        metadata = {
            "FileName": fname,
            "Make": make,
            "Model": model,
            "DateTimeOriginal": date,
        }
        text = f"{fname} {make} {model} {date}"
        repo.upsert_image(
            str(img_path), fname, stat.st_mtime, stat.st_size, metadata, text
        )

    repo.commit()
    repo.close()
    return base / "demo.db", base


@pytest.fixture
def window(
    qtbot: QtBot,
    demo_db: tuple[Path, Path],
) -> Generator[tuple[AppController, SearchListModel], None, None]:
    """Load the full QML window backed by the demo DB; one fresh window per test."""
    db_path, base = demo_db

    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings_model = SettingsModel(base / "settings.json")
    controller = AppController(db_path, search_model, exif_model, folder_model)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel", settings_model)
    ctx.setContextProperty("thirdPartyLicensesHtml", "")
    ctx.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)

    yield controller, search_model

    engine.deleteLater()
    qtbot.wait(200)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_unlock_shows_all_images(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert not controller.isLocked
    assert controller.totalResults == 5
    assert search_model.rowCount() == 5


def test_search_canon_returns_two_results(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window
    controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.search("Canon")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == 2
    assert search_model.rowCount() == 2


def test_search_exact_model_name_returns_one_result(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window
    controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.search("Z 9")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == 1
    assert search_model.rowCount() == 1


def test_clear_search_restores_all_results(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange — unlock and narrow the results first
    controller, search_model = window
    controller.unlock("")
    qtbot.wait(_PAUSE_MS // 2)
    controller.search("Fujifilm")
    qtbot.wait(_PAUSE_MS)

    # Act — clear the query
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.search("")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == 5
    assert search_model.rowCount() == 5


def test_search_no_match_returns_empty_results(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
) -> None:
    # Arrange
    controller, search_model = window
    controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.search("Hasselblad")
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert controller.totalResults == 0
    assert search_model.rowCount() == 0


# ── Debounce tests (no QML window needed) ─────────────────────────────────────


@pytest.fixture
def bare_controller(
    tmp_path: Path,
    demo_db: tuple[Path, Path],
) -> AppController:
    """Lightweight AppController backed by the demo DB — no QML engine."""
    db_path, base = demo_db
    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    return AppController(db_path, search_model, exif_model, folder_model)


def test_selectResult_thumb_source_updates_synchronously(
    qtbot: QtBot,
    bare_controller: AppController,
) -> None:
    # Arrange — unlock so the search model is populated
    with qtbot.waitSignal(bare_controller.totalResultsChanged, timeout=3000):
        bare_controller.unlock("")

    fired: list[int] = []
    bare_controller.selectedThumbSourceChanged.connect(lambda: fired.append(1))

    # Act — no event-loop spin after this call
    bare_controller.selectResult(0)

    # Assert — signal was emitted synchronously (inside selectResult, not deferred)
    assert len(fired) == 1


def test_selectResult_image_source_is_empty_before_debounce_fires(
    qtbot: QtBot,
    bare_controller: AppController,
) -> None:
    # Arrange
    with qtbot.waitSignal(bare_controller.totalResultsChanged, timeout=3000):
        bare_controller.unlock("")

    # Act — call selectResult but do NOT advance the event loop
    bare_controller.selectResult(0)

    # Assert — full preview has not loaded yet (timer has not fired)
    assert bare_controller.selectedImageSource == ""


def test_selectResult_image_source_set_after_debounce_fires(
    qtbot: QtBot,
    bare_controller: AppController,
) -> None:
    # Arrange
    with qtbot.waitSignal(bare_controller.totalResultsChanged, timeout=3000):
        bare_controller.unlock("")

    # Act — wait for the debounce timer to fire
    with qtbot.waitSignal(bare_controller.selectedImageSourceChanged, timeout=1000):
        bare_controller.selectResult(0)

    # Assert — full preview source is now set
    assert bare_controller.selectedImageSource != ""


def test_selectResult_rapid_calls_use_last_path(
    qtbot: QtBot,
    bare_controller: AppController,
) -> None:
    # Arrange — need at least 2 results
    with qtbot.waitSignal(bare_controller.totalResultsChanged, timeout=3000):
        bare_controller.unlock("")
    assert bare_controller.totalResults >= 2

    path_1 = bare_controller._search_model.get_path(0)
    path_2 = bare_controller._search_model.get_path(1)
    assert path_1 != path_2

    # Act — select row 0 then immediately row 1; only one timer fire expected
    with qtbot.waitSignal(bare_controller.selectedImageSourceChanged, timeout=1000):
        bare_controller.selectResult(0)
        bare_controller.selectResult(1)

    # Assert — final source encodes path_2, not path_1
    import urllib.parse
    expected = "image://preview/" + urllib.parse.quote(path_2, safe="")
    assert bare_controller.selectedImageSource == expected


def test_clear_details_cancels_pending_preview(
    qtbot: QtBot,
    bare_controller: AppController,
) -> None:
    # Arrange — arm the debounce timer without letting it fire
    with qtbot.waitSignal(bare_controller.totalResultsChanged, timeout=3000):
        bare_controller.unlock("")
    bare_controller.selectResult(0)
    assert bare_controller._preview_delay_timer.isActive()

    # Act
    bare_controller._clear_details()

    # Assert — timer is stopped and pending path is cleared
    assert not bare_controller._preview_delay_timer.isActive()
    assert bare_controller._pending_preview_path == ""
    assert bare_controller.selectedImageSource == ""
