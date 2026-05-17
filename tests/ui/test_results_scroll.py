"""E2E tests: mouse-wheel scroll in the Search-tab results list.

Scrolling invariant on Linux (X11 and Wayland)
───────────────────────────────────────────────
One physical mouse-wheel notch (angleDelta.y = ±120) must always advance
the list by exactly one row (210 px), regardless of what pixelDelta.y
reports.  On Linux, Qt may report a small non-zero pixelDelta for an
ordinary mouse-wheel event (X11 behaviour) or split a single notch into
many sub-notch events (Wayland/libinput high-resolution scroll).

The fix is a Python ``QObject.eventFilter`` (:class:`ListScrollFix`) installed
on the ``QQuickWindow``.  It intercepts wheel events before the Flickable
sees them, uses an ``angleDelta`` accumulator, and sets ``contentY`` directly.

These tests verify both the X11 and Wayland scenarios.

Run with:
    pytest tests/ui/test_results_scroll.py -v -s
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import (
    QCoreApplication,
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
from exif_turbo.ui.linux_scroll_fix import ListScrollFix
from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.view_models.app_controller import AppController

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

_ROW_HEIGHT = 210  # px — must match the delegate height in Main.qml


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def scroll_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Indexed DB with ten images — enough rows for scrollable content."""
    base = tmp_path_factory.mktemp("scroll_test")
    img_dir = base / "images"
    img_dir.mkdir()

    repo = ImageIndexRepository(base / "scroll.db", key="")
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
    return base / "scroll.db", base


@pytest.fixture
def scroll_window(
    qtbot: QtBot,
    scroll_db: tuple[Path, Path],
) -> Generator[tuple[AppController, QQuickItem, QQuickWindow], None, None]:
    """Full QML window, unlocked, Search tab visible.

    Yields (controller, resultsList item, qml_window).
    """
    db_path, base = scroll_db

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

    root.setVisible(True)
    try:
        qtbot.waitExposed(root, timeout=3000)
    except Exception:
        qtbot.wait(100)
    qtbot.wait(200)

    results_list: QQuickItem = root.findChild(QQuickItem, "resultsList")  # type: ignore[assignment]
    qml_window: QQuickWindow = root  # type: ignore[assignment]

    # Install the Linux scroll fix so the fixture mirrors the live app behaviour.
    scroll_fix = ListScrollFix(qml_window, "resultsList")
    qml_window.installEventFilter(scroll_fix)

    yield controller, results_list, qml_window

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


# ── helpers ───────────────────────────────────────────────────────────────────


def _send_wheel(
    results_list: QQuickItem,
    qml_window: QQuickWindow,
    angle_delta_y: int,
    pixel_delta_y: int = 0,
) -> None:
    """Synthesise one wheel event aimed at the centre of resultsList."""
    cx = float(results_list.property("width")) / 2
    cy = float(results_list.property("height")) / 2
    scene_pos = results_list.mapToScene(QPointF(cx, cy))
    global_pos = QPointF(
        qml_window.x() + scene_pos.x(),
        qml_window.y() + scene_pos.y(),
    )
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
    QCoreApplication.sendEvent(qml_window, event)
    QCoreApplication.processEvents()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific scroll fix")
class TestResultsListWheelScroll:
    """WheelHandler scrolls exactly one row per notch on Linux."""

    def test_single_notch_with_small_pixeldelta_scrolls_one_row(
        self,
        qtbot: QtBot,
        scroll_window: tuple[AppController, QQuickItem, QQuickWindow],
    ) -> None:
        """X11: angleDelta=120 + small pixelDelta → exactly one row (210 px).

        Before the fix, the pixelDelta branch was taken on Linux,
        scrolling only 3 px instead of 210 px.
        """
        # Arrange
        controller, results_list, qml_window = scroll_window
        results_list.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        # Act — simulate one X11 notch: angleDelta=-120, pixelDelta=-3 (small, unreliable)
        _send_wheel(results_list, qml_window, angle_delta_y=-120, pixel_delta_y=-3)
        qtbot.wait(50)

        # Assert
        content_y = float(results_list.property("contentY"))
        assert content_y == pytest.approx(_ROW_HEIGHT, abs=1.0), (
            f"Expected contentY={_ROW_HEIGHT} after one notch, got {content_y:.1f}. "
            "pixelDelta branch may still be taken on Linux."
        )

    def test_subnotch_events_accumulate_to_one_row(
        self,
        qtbot: QtBot,
        scroll_window: tuple[AppController, QQuickItem, QQuickWindow],
    ) -> None:
        """Wayland: 8 sub-notch events (angleDelta=15 each) accumulate to one row.

        libinput on Wayland may split one physical notch into 8 events,
        each reporting angleDelta.y=15.  The accumulator must batch these
        before scrolling so the list advances by exactly one row.
        """
        # Arrange
        controller, results_list, qml_window = scroll_window
        results_list.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        # Act — 8 × angleDelta=-15 = -120 total (one physical Wayland notch)
        for _ in range(8):
            _send_wheel(results_list, qml_window, angle_delta_y=-15)
        qtbot.wait(50)

        # Assert
        content_y = float(results_list.property("contentY"))
        assert content_y == pytest.approx(_ROW_HEIGHT, abs=1.0), (
            f"Expected contentY={_ROW_HEIGHT} after 8×angleDelta=15, got {content_y:.1f}. "
            "Sub-notch accumulation may not be working."
        )

    def test_scroll_up_after_scroll_down_returns_to_top(
        self,
        qtbot: QtBot,
        scroll_window: tuple[AppController, QQuickItem, QQuickWindow],
    ) -> None:
        """Scrolling down one row then up one row returns contentY to 0."""
        # Arrange
        controller, results_list, qml_window = scroll_window
        results_list.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        # Act
        _send_wheel(results_list, qml_window, angle_delta_y=-120)
        _send_wheel(results_list, qml_window, angle_delta_y=120)
        qtbot.wait(50)

        # Assert
        content_y = float(results_list.property("contentY"))
        assert content_y == pytest.approx(0.0, abs=1.0), (
            f"Expected contentY=0 after round-trip scroll, got {content_y:.1f}."
        )
