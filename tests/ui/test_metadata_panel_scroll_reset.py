"""E2E regression test: metadata panel goes black after scrolling then switching rows.

Steps that reproduce the bug:
  1. Open the app with an indexed DB.
  2. Select the 3rd result row  →  metadata panel fills with text.
  3. Scroll down in the metadata panel with the mouse wheel.
  4. Select the 1st result row.
  5. The metadata panel should show new text from the top (contentY == 0).
     Before the fix, contentY was left at the stale scrolled position, which
     put the viewport past the end of the (possibly shorter) new text and
     rendered a blank (black) panel.

Run with:
    pytest tests/ui/test_metadata_panel_scroll_reset.py -v -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QUrl,
)
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
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

# Use enough metadata lines so the panel is tall enough to actually scroll.
_CAMERAS = [
    (
        "cam_a.jpg",
        "Canon",
        "EOS R5",
        "2024:01:15 10:30:00",
        # Long metadata so the TextArea height exceeds the panel height.
        "\n".join(f"CanonTag{i}: ValueA{i}" for i in range(80)),
    ),
    (
        "cam_b.jpg",
        "Nikon",
        "Z 9",
        "2024:02:20 14:00:00",
        "\n".join(f"NikonTag{i}: ValueB{i}" for i in range(80)),
    ),
    (
        "cam_c.jpg",
        "Sony",
        "A7 IV",
        "2024:03:10 08:45:00",
        "\n".join(f"SonyTag{i}: ValueC{i}" for i in range(80)),
    ),
]


@pytest.fixture(scope="module")
def scroll_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """DB with three richly-annotated images; created once per module."""
    base = tmp_path_factory.mktemp("scroll_reset")
    img_dir = base / "images"
    img_dir.mkdir()

    repo = ImageIndexRepository(base / "scroll.db", key="")
    for fname, make, model, date, extra_text in _CAMERAS:
        img_path = img_dir / fname
        Image.new("RGB", (32, 32), color=(100, 150, 200)).save(
            str(img_path), format="JPEG"
        )
        stat = img_path.stat()
        metadata = {
            "FileName": fname,
            "Make": make,
            "Model": model,
            "DateTimeOriginal": date,
        }
        text = f"{fname} {make} {model} {date} {extra_text}"
        repo.upsert_image(
            str(img_path), fname, stat.st_mtime, stat.st_size, metadata, text
        )
    repo.commit()
    repo.close()
    return base / "scroll.db", base


@pytest.fixture
def scroll_window(
    qtbot: QtBot,
    scroll_db: tuple[Path, Path],
) -> Generator[tuple[AppController, QQmlApplicationEngine, QObject], None, None]:
    db_path, base = scroll_db
    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings_model = SettingsModel(base / "settings.json")
    filter_proxy = CheckedFilterProxyModel()
    filter_proxy.setSourceModel(search_model)
    controller = AppController(db_path, search_model, exif_model, folder_model)
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
    root.showNormal()
    root.setProperty("width", 1200)
    root.setProperty("height", 800)
    QCoreApplication.processEvents()

    yield controller, engine, root


def test_metadata_panel_contentY_resets_to_zero_after_row_switch(
    qtbot: QtBot,
    scroll_window: tuple[AppController, QQmlApplicationEngine, QObject],
) -> None:
    # Arrange — unlock and show all results
    controller, engine, root = scroll_window
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    QCoreApplication.processEvents()

    details_scroll: QQuickItem = root.findChild(QQuickItem, "detailsScrollView")  # type: ignore[assignment]
    assert details_scroll is not None, "detailsScrollView not found — missing objectName?"

    details_area: QQuickItem = root.findChild(QQuickItem, "detailsArea")  # type: ignore[assignment]
    assert details_area is not None, "detailsArea not found — missing objectName?"

    # Act step 1 — select the 3rd row (index 2)
    with qtbot.waitSignal(controller.detailsHtmlChanged, timeout=3000):
        controller.selectResult(2)
    QCoreApplication.processEvents()
    qtbot.wait(300)  # let TextArea finish its RichText layout pass

    flickable = details_scroll  # the Flickable itself carries contentY
    assert flickable is not None

    # Act step 2 — simulate scrolling down by setting contentY directly on the
    # Flickable (same as what a real mouse-wheel scroll does; wheel events sent
    # via QCoreApplication.sendEvent don't always reach the right Flickable in
    # a headless test environment).
    scroll_amount = 200.0
    flickable.setProperty("contentY", scroll_amount)
    QCoreApplication.processEvents()
    qtbot.wait(100)

    scrolled_y = flickable.property("contentY")
    assert scrolled_y > 0, (
        f"Precondition failed: could not set contentY to {scroll_amount} — "
        f"actual contentY={scrolled_y}. The TextArea content may be too short "
        f"to allow scrolling (contentHeight <= panel height)."
    )

    # Act step 3 — switch to the 1st row (index 0)
    with qtbot.waitSignal(controller.detailsHtmlChanged, timeout=3000):
        controller.selectResult(0)
    QCoreApplication.processEvents()
    qtbot.wait(300)  # let the RichText layout settle

    # Assert — contentY must be back at 0
    final_y = flickable.property("contentY")
    assert final_y == pytest.approx(0.0, abs=2.0), (
        f"Metadata panel did not scroll back to top after row switch. "
        f"contentY = {final_y} (was {scrolled_y} after scrolling). "
        f"The panel renders black because the scroll position points past "
        f"the new content."
    )
