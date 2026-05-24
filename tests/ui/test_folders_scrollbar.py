"""E2E test proving that the Indexed Folders list shows a scrollbar when
the folder count overflows the visible area, without requiring any user
interaction (hover, flick, drag).

The misbehaviour:
    The Material-style overlay ScrollBar (policy: ScrollBar.AsNeeded) uses an
    opacity animation to auto-hide the visual indicator when the user is not
    actively scrolling.  contentItem.opacity is therefore 0.0 even when the
    content overflows — the user sees no scrollbar and has no cue that more
    items exist below.

Expected (correct) behaviour:
    With policy: ScrollBar.AlwaysOn the Qt Material delegate sets
    contentItem.opacity = 1.0 whenever size < 1.0 (overflow), regardless of
    whether the user is interacting.  The scrollbar is permanently visible as
    soon as there is content to scroll.

Run with:
    pytest tests/ui/test_folders_scrollbar.py -v -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.view_models.app_controller import AppController

# Number of folders to add.  Each delegate is 76 px; the window opens at
# 800 px height with ~88 px of chrome (tab bar + panel header), leaving ≈712 px
# for the list.  20 folders = 1520 px of content → guaranteed overflow.
_OVERFLOW_FOLDER_COUNT = 20
_DELEGATE_HEIGHT_PX = 76  # height of each folder row in FoldersPanel.qml

_PAUSE_MS = 600  # ms to wait for layout/animations to settle

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def scrollbar_window(
    qtbot: QtBot,
    tmp_path: Path,
) -> Generator[
    tuple[AppController, FolderListModel, QQmlApplicationEngine, Path],
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

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3_000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    yield controller, folder_model, engine, tmp_path

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _switch_to_folders_tab(root: QObject, qtbot: QtBot) -> None:
    """Set mainTabBar.currentIndex to 2 (Indexed Folders tab)."""
    tab_bar = root.findChild(QObject, "mainTabBar")
    assert tab_bar is not None, "mainTabBar QML item not found"
    tab_bar.setProperty("currentIndex", 2)
    qtbot.wait(200)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_folders_list_scrollbar_visible_without_interaction_when_content_overflows(
    qtbot: QtBot,
    scrollbar_window: tuple[
        AppController, FolderListModel, QQmlApplicationEngine, Path
    ],
) -> None:
    """Scrollbar contentItem must be opaque as soon as the folder list overflows.

    Reproduces the misbehaviour: with policy: ScrollBar.AsNeeded the Qt
    Material delegate sets contentItem.opacity = 0 whenever the scrollbar is
    not "active" (not being interacted with).  After adding folders the bar is
    present in the scene but fully transparent — invisible to the user.

    The fix is policy: ScrollBar.AlwaysOn, which makes the Qt Material delegate
    set contentItem.opacity = 1 whenever size < 1.0 (overflow), regardless of
    the active/interaction state.
    """
    # Arrange
    controller, folder_model, engine, tmp_path = scrollbar_window
    root = engine.rootObjects()[0]

    _switch_to_folders_tab(root, qtbot)

    folders_list = root.findChild(QObject, "foldersList")
    assert folders_list is not None, (
        "foldersList not found — add objectName: 'foldersList' to the ListView "
        "in FoldersPanel.qml"
    )

    # Act — add enough folders to guarantee content overflow
    for i in range(_OVERFLOW_FOLDER_COUNT):
        d = tmp_path / f"dir_{i:02d}"
        d.mkdir(exist_ok=True)
        controller.addIndexedFolder(QUrl.fromLocalFile(str(d)).toString())

    # Wait for layout and any opacity animations to settle
    qtbot.wait(_PAUSE_MS)

    # Assert — model has all rows
    assert folder_model.rowCount() == _OVERFLOW_FOLDER_COUNT

    # Assert — content genuinely overflows the visible area
    content_height = folders_list.property("contentHeight")
    list_height = folders_list.property("height")
    assert content_height > list_height, (
        f"Expected contentHeight ({content_height:.0f}px) > "
        f"list height ({list_height:.0f}px) — "
        f"increase _OVERFLOW_FOLDER_COUNT if this fails on a tall display"
    )

    # Assert — the scrollbar's visual indicator is opaque (user can see it)
    # without any scrolling or hover interaction.
    #
    # BUG (policy: ScrollBar.AsNeeded):
    #   Qt Material overlay: contentItem.opacity = (active || AlwaysOn) ? 1 : 0
    #   With no user interaction, active=False → opacity=0 → bar invisible.
    #
    # FIX (policy: ScrollBar.AlwaysOn):
    #   contentItem.opacity = 1 whenever size < 1.0 → bar always visible.
    scroll_bar = root.findChild(QObject, "foldersScrollBar")
    assert scroll_bar is not None, (
        "foldersScrollBar not found — add objectName: 'foldersScrollBar' "
        "to the ScrollBar in FoldersPanel.qml"
    )

    content_item = scroll_bar.property("contentItem")
    assert content_item is not None, "ScrollBar has no contentItem"

    opacity = content_item.property("opacity")
    assert opacity > 0, (
        f"ScrollBar contentItem.opacity is {opacity:.2f} — the bar is invisible "
        "to the user even though the list overflows.  "
        "Fix: set policy: ScrollBar.AlwaysOn in FoldersPanel.qml."
    )
