"""E2E test: mouse-wheel scroll in the Browse-tab image list.

The Browse-tab `browseImageList` ListView must scroll exactly one row
(210 px) per physical mouse-wheel notch — same invariant as the Search-tab
results list. This is enforced by the same :class:`ListScrollFix` event
filter installed on the QQuickWindow.

This test verifies the fix is actually wired up to the browse list so the
user can scroll through a folder's images with the mouse wheel.

Run with:
    pytest tests/ui/test_browse_wheel_scroll.py -v -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt, QUrl
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

_ROW_HEIGHT = 210


@pytest.fixture(scope="module")
def browse_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    """DB with 10 images in a single folder, ready for browsing."""
    base = tmp_path_factory.mktemp("browse_scroll")
    folder = base / "shoot"
    folder.mkdir()

    repo = ImageIndexRepository(base / "browse.db", key="")
    for i in range(10):
        img_path = folder / f"pic_{i:02d}.jpg"
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
    return base / "browse.db", base, folder


@pytest.fixture
def browse_window(
    qtbot: QtBot,
    browse_db: tuple[Path, Path, Path],
) -> Generator[tuple[AppController, QQuickItem, QQuickWindow], None, None]:
    db_path, base, folder = browse_db

    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings_model = SettingsModel(base / "settings.json")
    controller = AppController(db_path, search_model, exif_model, folder_model)
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
    ctx.setContextProperty("thirdPartyLicensesHtml", "")
    ctx.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
    root = engine.rootObjects()[0]

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")

    # Switch to Browse tab and select the folder.
    root.setProperty("_browseTab", None)  # no-op; placeholder
    tab_bar = root.findChild(QQuickItem, "mainTabBar")
    if tab_bar is not None:
        tab_bar.setProperty("currentIndex", 1)
    else:
        # Fall back: directly trigger the controller path that Browse uses.
        controller.loadFolderTree()
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.browseFolder(str(folder))

    root.setVisible(True)
    try:
        qtbot.waitExposed(root, timeout=3000)
    except Exception:
        qtbot.wait(100)
    qtbot.wait(300)

    browse_list: QQuickItem = root.findChild(QQuickItem, "browseImageList")  # type: ignore[assignment]
    assert browse_list is not None, "browseImageList not found in QML tree"

    # Mirror the real app: install ListScrollFix for BOTH the Search-tab
    # resultsList and the Browse-tab browseImageList. The invisible
    # resultsList must not steal wheel events meant for the browse list.
    for name in ("resultsList", "browseImageList"):
        fix = ListScrollFix(root, name)
        root.installEventFilter(fix)

    yield controller, browse_list, root

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


def _send_wheel(
    target: QQuickItem,
    window: QQuickWindow,
    angle_delta_y: int,
    pixel_delta_y: int = 0,
    y_frac: float = 0.5,
) -> None:
    cx = float(target.property("width")) / 2
    cy = float(target.property("height")) * y_frac
    scene_pos = target.mapToScene(QPointF(cx, cy))
    global_pos = QPointF(window.x() + scene_pos.x(), window.y() + scene_pos.y())
    event = QWheelEvent(
        scene_pos,
        global_pos,
        QPoint(0, pixel_delta_y),
        QPoint(0, angle_delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QCoreApplication.sendEvent(window, event)
    QCoreApplication.processEvents()


class TestBrowseListWheelScroll:
    def test_browse_list_is_visible_and_populated(
        self,
        browse_window: tuple[AppController, QQuickItem, QQuickWindow],
    ) -> None:
        _, browse_list, _ = browse_window
        assert bool(browse_list.property("visible")) is True
        assert int(browse_list.property("count")) == 10

    def test_single_notch_scrolls_one_row(
        self,
        qtbot: QtBot,
        browse_window: tuple[AppController, QQuickItem, QQuickWindow],
    ) -> None:
        _, browse_list, window = browse_window
        browse_list.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        _send_wheel(browse_list, window, angle_delta_y=-120, pixel_delta_y=-3)
        qtbot.wait(50)

        content_y = float(browse_list.property("contentY"))
        assert content_y == pytest.approx(_ROW_HEIGHT, abs=1.0), (
            f"Expected contentY={_ROW_HEIGHT} after one notch, got {content_y:.1f}"
        )

    def test_wheel_up_scrolls_back_one_row(
        self,
        qtbot: QtBot,
        browse_window: tuple[AppController, QQuickItem, QQuickWindow],
    ) -> None:
        _, browse_list, window = browse_window
        browse_list.setProperty("contentY", float(_ROW_HEIGHT * 2))
        QCoreApplication.processEvents()

        _send_wheel(browse_list, window, angle_delta_y=120)
        qtbot.wait(50)

        content_y = float(browse_list.property("contentY"))
        assert content_y == pytest.approx(_ROW_HEIGHT, abs=1.0), (
            f"Expected contentY={_ROW_HEIGHT} after wheel-up notch, got {content_y:.1f}"
        )

    def test_wheel_at_top_of_list_scrolls_one_row(
        self,
        qtbot: QtBot,
        browse_window: tuple[AppController, QQuickItem, QQuickWindow],
    ) -> None:
        """Regression: wheel events in the UPPER part of the list must scroll
        too, not just the lower part. Sends a notch near the top edge (5%)."""
        _, browse_list, window = browse_window
        browse_list.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        _send_wheel(browse_list, window, angle_delta_y=-120, y_frac=0.05)
        qtbot.wait(50)

        content_y = float(browse_list.property("contentY"))
        assert content_y == pytest.approx(_ROW_HEIGHT, abs=1.0), (
            f"Wheel near top of list should scroll one row; got contentY={content_y:.1f}"
        )

    def test_wheel_after_selecting_top_image_still_scrolls(
        self,
        qtbot: QtBot,
        browse_window: tuple[AppController, QQuickItem, QQuickWindow],
    ) -> None:
        """Regression: after the user clicks a delegate in the top half of
        the list (which calls selectResult and gives focus), the mouse wheel
        must continue to scroll. This caught a real bug where wheel events
        only fired in the lower part of the list after a selection."""
        controller, browse_list, window = browse_window
        browse_list.setProperty("contentY", 0.0)
        controller.selectResult(0)
        QCoreApplication.processEvents()
        qtbot.wait(50)

        _send_wheel(browse_list, window, angle_delta_y=-120, y_frac=0.05)
        qtbot.wait(50)

        content_y = float(browse_list.property("contentY"))
        assert content_y == pytest.approx(_ROW_HEIGHT, abs=1.0), (
            f"Wheel near top of list after selection should scroll one row; "
            f"got contentY={content_y:.1f}"
        )
