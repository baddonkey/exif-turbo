"""E2E test reproducing the Third-Party Licenses wheel-scroll regression.

User-visible symptom (issue #17):
    After performing a search and opening a result, choosing
    Help -> Third-Party Licenses opens a dialog over the search results.
    Scrolling the mouse wheel moves the *background* search results list
    instead of the foreground dialog content.

Root cause:
    :class:`ListScrollFix` is installed on the ``QQuickWindow`` and intercepts
    wheel events that land over the (still visible) ``resultsList`` behind the
    dialog, writing its ``contentY`` directly.  It did not account for an open
    foreground popup, so the background scrolled while the dialog did not.

Fix:
    ``ListScrollFix`` now lets wheel events through (returns ``False``) whenever
    a popup/dialog is shown in the ``ApplicationWindow`` overlay, so the
    foreground dialog receives them instead of the background list.

Run with::

    pytest tests/ui/test_third_party_licenses_wheel_scroll.py -v -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import (
    QCoreApplication,
    QMetaObject,
    QObject,
    QPoint,
    QPointF,
    Qt,
    QUrl,
)
from PySide6.QtGui import QWheelEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.scroll_fix import ListScrollFix
from exif_turbo.ui.view_models.app_controller import AppController

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

_ROW_HEIGHT = 210  # px — must match the resultsList delegate height in Main.qml


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def licenses_window(
    qtbot: QtBot,
    tmp_path: Path,
) -> Generator[tuple[AppController, QQuickItem, QQuickWindow, QObject], None, None]:
    """Full QML window, unlocked, Search tab with scrollable results.

    Yields (controller, resultsList item, window, thirdPartyDialog).
    """
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    repo = ImageIndexRepository(tmp_path / "scroll.db", key="")
    for i in range(10):
        img_path = img_dir / f"img_{i:02d}.jpg"
        Image.new("RGB", (32, 32), color=(i * 25, 100, 200)).save(str(img_path))
        stat = img_path.stat()
        repo.upsert_image(
            str(img_path),
            img_path.name,
            stat.st_mtime,
            stat.st_size,
            {"FileName": img_path.name},
            img_path.name,
        )
    repo.commit()
    repo.close()

    search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings_model = SettingsModel(tmp_path / "settings.json")
    controller = AppController(
        tmp_path / "scroll.db", search_model, exif_model, folder_model
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
    ctx.setContextProperty("settingsModel", settings_model)
    ctx.setContextProperty("thirdPartyLicensesHtml", "<html><body>licenses</body></html>")
    ctx.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
    root = engine.rootObjects()[0]
    assert isinstance(root, QQuickWindow)

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")

    root.setVisible(True)
    try:
        qtbot.waitExposed(root, timeout=3000)
    except Exception:
        qtbot.wait(100)
    qtbot.wait(200)

    scroll_fix = ListScrollFix(root, "resultsList")
    root.installEventFilter(scroll_fix)

    results_list = root.findChild(QQuickItem, "resultsList")
    assert results_list is not None
    dialog = root.findChild(QObject, "thirdPartyDialog")
    assert dialog is not None

    yield controller, results_list, root, dialog

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _send_wheel(
    target: QQuickItem,
    window: QQuickWindow,
    angle_delta_y: int,
) -> None:
    """Synthesise one wheel event aimed at the centre of *target*."""
    cx = float(target.property("width")) / 2
    cy = float(target.property("height")) / 2
    scene_pos = target.mapToScene(QPointF(cx, cy))
    global_pos = QPointF(window.x() + scene_pos.x(), window.y() + scene_pos.y())
    event = QWheelEvent(
        scene_pos,
        global_pos,
        QPoint(0, 0),
        QPoint(0, angle_delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QCoreApplication.sendEvent(window, event)
    QCoreApplication.processEvents()


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestThirdPartyLicensesWheelScroll:

    def test_wheel_does_not_scroll_background_results_while_dialog_open(
        self,
        qtbot: QtBot,
        licenses_window: tuple[AppController, QQuickItem, QQuickWindow, QObject],
    ) -> None:
        """Reproducer for issue #17: with the Third-Party Licenses dialog open,
        a wheel event over the background results list must not scroll it."""
        # Arrange — open the dialog over the (scrollable) results list.
        _ctrl, results_list, window, dialog = licenses_window
        results_list.setProperty("contentY", 0.0)
        QMetaObject.invokeMethod(dialog, "open")
        qtbot.waitUntil(lambda: bool(dialog.property("visible")), timeout=2000)
        QCoreApplication.processEvents()

        # Act — wheel over the centre of the now-background results list.
        _send_wheel(results_list, window, angle_delta_y=-120)
        qtbot.wait(50)

        # Assert — background list stays put; the dialog owns the wheel event.
        content_y = float(results_list.property("contentY"))
        assert content_y == pytest.approx(0.0, abs=1.0), (
            f"Background results scrolled to {content_y:.1f} while the "
            "Third-Party Licenses dialog was open (issue #17)."
        )

    def test_wheel_scrolls_results_when_dialog_closed(
        self,
        qtbot: QtBot,
        licenses_window: tuple[AppController, QQuickItem, QQuickWindow, QObject],
    ) -> None:
        """Control: with no dialog open the results list still scrolls one row."""
        # Arrange
        _ctrl, results_list, window, _dialog = licenses_window
        results_list.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        # Act
        _send_wheel(results_list, window, angle_delta_y=-120)
        qtbot.wait(50)

        # Assert
        content_y = float(results_list.property("contentY"))
        assert content_y == pytest.approx(_ROW_HEIGHT, abs=1.0), (
            f"Expected contentY={_ROW_HEIGHT} with no dialog open, got {content_y:.1f}."
        )
