from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
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


def test_ai_search_select_all_marks_only_ai_results(
    qtbot: QtBot,
    folder_demo_db: tuple[Path, Path, Path, Path],
) -> None:
    # Arrange
    db_path, base, alpha_dir, beta_dir = folder_demo_db
    ai_result_paths = [str(alpha_dir / "canon_0.jpg"), str(beta_dir / "nikon_1.jpg")]

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
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    for folder in (alpha_dir, beta_dir):
        with qtbot.waitSignal(controller.indexedFoldersChanged, timeout=3000):
            controller.addIndexedFolder(QUrl.fromLocalFile(str(folder)).toString())
        qtbot.wait(_PAUSE_MS)

    controller.setAiSearchMode(True)
    fake_rows = [
        (1, ai_result_paths[0], "canon_0.jpg", "{}", 123, 1.0),
        (5, ai_result_paths[1], "nikon_1.jpg", "{}", 123, 1.0),
    ]
    with patch("exif_turbo.ui.view_models.app_controller.AiSearchWorker.run", autospec=True) as mocked_run:
        def _emit_ai_results(worker: object) -> None:
            worker.results_ready.emit(fake_rows, len(fake_rows), [], worker._serial)  # type: ignore[attr-defined]

        mocked_run.side_effect = _emit_ai_results
        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            controller.aiSearch("boats", "normal")

    assert search_model.rowCount() == len(ai_result_paths)

    # Act
    with qtbot.waitSignal(controller.checkedCountChanged, timeout=5000):
        controller.selectAll()

    repo = ImageIndexRepository(db_path, key="")
    marked_paths = set(repo.get_marked_paths())
    repo.close()

    # Assert
    assert marked_paths == set(ai_result_paths)

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


def test_clear_search_button_in_ai_mode_triggers_empty_ai_search(
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
    qml_window: QQuickWindow = root  # type: ignore[assignment]

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
    clear_mouse = root.findChild(QQuickItem, "clearSearchMouse")
    assert search_field is not None
    assert clear_mouse is not None

    controller.setAiSearchMode(True)
    root.setProperty("_aiSearchMode", True)

    with patch("exif_turbo.ui.view_models.app_controller.AiSearchWorker.run", autospec=True) as mocked_run:
        def _emit_results(worker: object) -> None:
            worker.results_ready.emit([], 0, [], worker._serial)  # type: ignore[attr-defined]

        mocked_run.side_effect = _emit_results

        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            controller.aiSearch("boats", "normal")
        qtbot.wait(_PAUSE_MS)
        assert controller._last_ai_query == "boats"  # type: ignore[attr-defined]

        # Act
        search_field.setProperty("text", "boats")
        click_pos = clear_mouse.mapToScene(
            QPointF(clear_mouse.width() / 2.0, clear_mouse.height() / 2.0)
        )
        with qtbot.waitSignal(controller.loadedResultsChanged, timeout=5000):
            QTest.mouseClick(
                qml_window,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(int(click_pos.x()), int(click_pos.y())),
            )
        qtbot.wait(_PAUSE_MS)

    # Assert
    assert search_field.property("text") == ""
    assert controller._last_ai_query == ""  # type: ignore[attr-defined]

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)