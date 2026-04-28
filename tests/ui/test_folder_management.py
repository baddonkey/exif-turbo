"""pytest-qt integration tests for folder management via AppController.

Tests add/remove/enable/disable of managed folders through the live QML
window, verifying that search results are filtered accordingly.

Run with:
    pytest tests/ui/test_folder_management.py -v -s
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

_PAUSE_MS = 700

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_jpeg(path: Path, color: tuple) -> Path:
    Image.new("RGB", (32, 32), color=color).save(str(path), format="JPEG")
    return path


# ── Module-scoped DB fixture ──────────────────────────────────────────────────


@pytest.fixture
def folder_demo_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path, Path]:
    """DB with images split across two folders: alpha (3 Canon) and beta (2 Nikon)."""
    base = tmp_path_factory.mktemp("folder_demo")

    alpha_dir = base / "alpha"
    beta_dir = base / "beta"
    alpha_dir.mkdir()
    beta_dir.mkdir()

    repo = ImageIndexRepository(base / "demo.db", key="")

    for i in range(3):
        p = _make_jpeg(alpha_dir / f"canon_{i}.jpg", (200, 50 + i * 30, 50))
        stat = p.stat()
        repo.upsert_image(
            str(p), p.name, stat.st_mtime, stat.st_size,
            {"Make": "Canon", "Model": f"EOS R{i}"},
            f"Canon EOS R{i} {p.name}",
        )

    for i in range(2):
        p = _make_jpeg(beta_dir / f"nikon_{i}.jpg", (50, 100, 200 + i * 20))
        stat = p.stat()
        repo.upsert_image(
            str(p), p.name, stat.st_mtime, stat.st_size,
            {"Make": "Nikon", "Model": f"Z{i + 6}"},
            f"Nikon Z{i + 6} {p.name}",
        )

    repo.commit()
    repo.close()
    return base / "demo.db", base, alpha_dir, beta_dir


# ── Per-test window fixture ───────────────────────────────────────────────────


@pytest.fixture
def folder_window(
    qtbot: QtBot,
    folder_demo_db: tuple[Path, Path, Path, Path],
) -> Generator[tuple[AppController, SearchListModel, FolderListModel, Path, Path], None, None]:
    db_path, base, alpha_dir, beta_dir = folder_demo_db

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

    # Unlock so the DB is open
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    yield controller, search_model, folder_model, alpha_dir, beta_dir

    engine.deleteLater()
    qtbot.wait(200)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_add_indexed_folder_tracks_folder_in_model(
    qtbot: QtBot,
    folder_window: tuple[AppController, SearchListModel, FolderListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, folder_model, alpha_dir, _ = folder_window

    # Act
    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(alpha_dir)).toString())
    qtbot.wait(_PAUSE_MS)

    # Assert — folder appears in the model
    assert folder_model.rowCount() >= 1
    paths = [folder_model.data(folder_model.index(i), FolderListModel.PathRole)
             for i in range(folder_model.rowCount())]
    from pathlib import Path as _Path
    import os
    assert any(os.path.normpath(p) == os.path.normpath(str(alpha_dir)) for p in paths)


def test_add_duplicate_folder_does_not_add_twice(
    qtbot: QtBot,
    folder_window: tuple[AppController, SearchListModel, FolderListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, folder_model, alpha_dir, _ = folder_window
    controller.addIndexedFolder(QUrl.fromLocalFile(str(alpha_dir)).toString())
    qtbot.wait(_PAUSE_MS)
    count_after_first = folder_model.rowCount()

    # Act — add same folder again
    controller.addIndexedFolder(QUrl.fromLocalFile(str(alpha_dir)).toString())
    qtbot.wait(_PAUSE_MS)

    # Assert — row count unchanged
    assert folder_model.rowCount() == count_after_first


def test_set_folder_enabled_false_excludes_images_from_search(
    qtbot: QtBot,
    folder_window: tuple[AppController, SearchListModel, FolderListModel, Path, Path],
) -> None:
    # Arrange — add both folders and wait for indexedFoldersChanged
    controller, search_model, folder_model, alpha_dir, beta_dir = folder_window

    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(alpha_dir)).toString())
    qtbot.wait(_PAUSE_MS)
    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(beta_dir)).toString())
    qtbot.wait(_PAUSE_MS)

    # Confirm both folders tracked
    assert folder_model.rowCount() == 2

    # Find the alpha folder's id
    alpha_id = None
    for i in range(folder_model.rowCount()):
        import os
        path = folder_model.data(folder_model.index(i), FolderListModel.PathRole)
        if os.path.normpath(path) == os.path.normpath(str(alpha_dir)):
            alpha_id = folder_model.data(folder_model.index(i), FolderListModel.FolderIdRole)
            break
    assert alpha_id is not None

    # Act — disable alpha folder
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setFolderEnabled(alpha_id, False)
    qtbot.wait(_PAUSE_MS)

    # Assert — only beta images (2 Nikon) appear in search
    assert controller.totalResults == 2


def test_set_folder_enabled_true_restores_images_in_search(
    qtbot: QtBot,
    folder_window: tuple[AppController, SearchListModel, FolderListModel, Path, Path],
) -> None:
    # Arrange — add alpha, disable it
    controller, search_model, folder_model, alpha_dir, _ = folder_window

    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(alpha_dir)).toString())
    qtbot.wait(_PAUSE_MS)

    alpha_id = folder_model.data(folder_model.index(0), FolderListModel.FolderIdRole)

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setFolderEnabled(alpha_id, False)
    qtbot.wait(_PAUSE_MS)
    count_disabled = controller.totalResults

    # Act — re-enable alpha
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setFolderEnabled(alpha_id, True)
    qtbot.wait(_PAUSE_MS)

    # Assert — more results than when disabled
    assert controller.totalResults > count_disabled


def test_remove_indexed_folder_removes_from_model(
    qtbot: QtBot,
    folder_window: tuple[AppController, SearchListModel, FolderListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, folder_model, alpha_dir, _ = folder_window

    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(alpha_dir)).toString())
    qtbot.wait(_PAUSE_MS)

    assert folder_model.rowCount() >= 1
    alpha_id = folder_model.data(folder_model.index(0), FolderListModel.FolderIdRole)

    # Act
    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.removeIndexedFolder(alpha_id)
    qtbot.wait(_PAUSE_MS)

    # Assert — folder removed from model
    ids = [folder_model.data(folder_model.index(i), FolderListModel.FolderIdRole)
           for i in range(folder_model.rowCount())]
    assert alpha_id not in ids
