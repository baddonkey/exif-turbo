"""E2E test reproducing the Indexed Folders list wheel-scroll regression.

User-visible symptom:
    Scrolling with the mouse wheel works when the cursor hovers the upper part
    of the folder list, but stops responding when the cursor is over the lower
    rows (where row controls — Switch, multiple Buttons — densely cover the
    delegate area).  Root cause: child controls install ``HoverHandler`` /
    ``WheelHandler`` instances that grab pointer events on hover, and Qt's
    ``QQuickFlickable`` never sees the wheel event.

Fix:
    A Python ``QObject.eventFilter`` (:class:`ListScrollFix`) installed on the
    ``QQuickWindow`` intercepts wheel events targeted at ``foldersList`` before
    they reach the Flickable / child handlers, and writes ``contentY`` directly.

This test:
    1. Adds enough folders to overflow the visible area.
    2. Synthesises a wheel event at the *top* of the list — should scroll.
    3. Synthesises a wheel event at the *bottom* of the list, over a Button /
       Switch in a delegate — should still scroll (this is the reproducer).
    4. Synthesises a wheel-up event near the bottom — should scroll back up.

Run with::

    pytest tests/ui/test_folders_wheel_scroll.py -v -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QWheelEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.scroll_fix import ListScrollFix
from exif_turbo.ui.view_models.app_controller import AppController

_OVERFLOW_FOLDER_COUNT = 20  # 20 × 76 px = 1520 px content → guaranteed overflow
_FOLDER_ROW_PX = 76
_PAUSE_MS = 600

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def wheel_window(
    qtbot: QtBot,
    tmp_path: Path,
) -> Generator[
    tuple[AppController, QQuickItem, QQuickWindow, Path],
    None,
    None,
]:
    search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings_model = SettingsModel(tmp_path / "settings.json")
    controller = AppController(
        tmp_path / "test.db", search_model, exif_model, folder_model
    )

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

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5_000)
    root = engine.rootObjects()[0]
    assert isinstance(root, QQuickWindow)

    # Install the production event filter (mirrors app_main.py wiring).
    fix = ListScrollFix(root, "foldersList", row_height=_FOLDER_ROW_PX)
    root.installEventFilter(fix)

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3_000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    # Switch to the Indexed Folders tab
    tab_bar = root.findChild(QObject, "mainTabBar")
    assert tab_bar is not None
    tab_bar.setProperty("currentIndex", 2)
    qtbot.wait(_PAUSE_MS)

    # Populate enough folders to overflow
    for i in range(_OVERFLOW_FOLDER_COUNT):
        d = tmp_path / f"dir_{i:02d}"
        d.mkdir(exist_ok=True)
        controller.addIndexedFolder(QUrl.fromLocalFile(str(d)).toString())

    qtbot.wait(_PAUSE_MS)

    folders_list = root.findChild(QQuickItem, "foldersList")
    assert folders_list is not None

    yield controller, folders_list, root, tmp_path

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _send_wheel(
    target: QQuickItem,
    window: QQuickWindow,
    relative_y_fraction: float,
    angle_delta_y: int,
) -> None:
    """Synthesise a wheel event at (centre-x, height*fraction) inside *target*."""
    width = float(target.property("width"))
    height = float(target.property("height"))
    local = QPointF(width / 2, height * relative_y_fraction)
    scene_pos = target.mapToScene(local)
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


class TestFoldersListWheelScroll:

    def test_wheel_scrolls_when_cursor_is_on_upper_part_of_list(
        self,
        qtbot: QtBot,
        wheel_window: tuple[AppController, QQuickItem, QQuickWindow, Path],
    ) -> None:
        _ctrl, folders_list, window, _tmp = wheel_window
        folders_list.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        _send_wheel(folders_list, window, relative_y_fraction=0.1, angle_delta_y=-120)
        qtbot.wait(80)

        content_y = float(folders_list.property("contentY"))
        assert content_y == pytest.approx(_FOLDER_ROW_PX, abs=1.0), (
            f"Wheel at top: expected contentY={_FOLDER_ROW_PX}, got {content_y:.1f}"
        )

    def test_wheel_scrolls_when_cursor_is_on_lower_part_of_list(
        self,
        qtbot: QtBot,
        wheel_window: tuple[AppController, QQuickItem, QQuickWindow, Path],
    ) -> None:
        """Reproducer: wheel over the lower rows (over Button / Switch controls)
        must still scroll the list.  Without ListScrollFix the delegate's child
        HoverHandlers grab the wheel event and the list does not move."""
        _ctrl, folders_list, window, _tmp = wheel_window
        folders_list.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        # Cursor at 90% of list height — squarely over a delegate's Button row.
        _send_wheel(folders_list, window, relative_y_fraction=0.9, angle_delta_y=-120)
        qtbot.wait(80)

        content_y = float(folders_list.property("contentY"))
        assert content_y == pytest.approx(_FOLDER_ROW_PX, abs=1.0), (
            f"Wheel at bottom: expected contentY={_FOLDER_ROW_PX}, got {content_y:.1f}. "
            "Reproducer: child Button/Switch hover-grabs swallow wheel events."
        )

    def test_wheel_up_at_bottom_scrolls_back_up(
        self,
        qtbot: QtBot,
        wheel_window: tuple[AppController, QQuickItem, QQuickWindow, Path],
    ) -> None:
        """After scrolling down, wheel-up at the lower part of the list must
        scroll back up (the user's exact reported symptom)."""
        _ctrl, folders_list, window, _tmp = wheel_window

        # Pre-scroll well into the list.
        folders_list.setProperty("contentY", 5 * _FOLDER_ROW_PX)
        QCoreApplication.processEvents()
        start_y = float(folders_list.property("contentY"))

        _send_wheel(folders_list, window, relative_y_fraction=0.9, angle_delta_y=+120)
        qtbot.wait(80)

        content_y = float(folders_list.property("contentY"))
        expected = start_y - _FOLDER_ROW_PX
        assert content_y == pytest.approx(expected, abs=1.0), (
            f"Wheel-up at bottom: expected contentY={expected}, got {content_y:.1f}"
        )
