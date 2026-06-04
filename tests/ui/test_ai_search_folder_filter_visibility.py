from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.view_models.app_controller import AppController
from tests.ui.test_folder_management import _PAUSE_MS, _QML_PATH, folder_demo_db


def test_ai_search_mode_keeps_folder_filter_visible(
    qtbot: QtBot,
    folder_demo_db: tuple[Path, Path, Path, Path],
) -> None:
    # Arrange
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
    root = engine.rootObjects()[0]

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(alpha_dir)).toString())
    qtbot.wait(_PAUSE_MS)
    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(beta_dir)).toString())
    qtbot.wait(_PAUSE_MS)

    folder_combo = root.findChild(QQuickItem, "folderMultiCombo")
    assert folder_combo is not None
    assert folder_combo.property("visible") is True

    # Act
    controller.setAiSearchMode(True)
    root.setProperty("_aiSearchMode", True)
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert folder_combo.property("visible") is True


def test_ai_search_folder_filter_change_keeps_search_field_text(
    qtbot: QtBot,
    folder_demo_db: tuple[Path, Path, Path, Path],
) -> None:
    # Arrange
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
    root = engine.rootObjects()[0]

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(alpha_dir)).toString())
    qtbot.wait(_PAUSE_MS)
    with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
        controller.addIndexedFolder(QUrl.fromLocalFile(str(beta_dir)).toString())
    qtbot.wait(_PAUSE_MS)

    search_field = root.findChild(QQuickItem, "searchField")
    assert search_field is not None

    controller.setAiSearchMode(True)
    root.setProperty("_aiSearchMode", True)
    search_field.setProperty("text", "boats")
    qtbot.wait(_PAUSE_MS)

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.setSearchFolderFilter(str(alpha_dir))
    qtbot.wait(_PAUSE_MS)

    # Assert
    assert search_field.property("text") == "boats"

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)