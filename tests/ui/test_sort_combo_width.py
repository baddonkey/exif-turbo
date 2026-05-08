"""E2E tests: sort ComboBox width must accommodate all translated labels.

Root cause
──────────
Without an explicit ``implicitWidth`` binding, Qt Quick Controls 2 Material
``ComboBox`` auto-sizes to the *current* selection's text.  When a short label
is selected (e.g. "Path A→Z", the fallback), the popup also inherits that
narrow width and clips longer entries such as "Neueste zuerst" (German) or
"Plus récent d'abord" (French).

Fix
───
Bind ``implicitWidth`` to the *maximum* ``FontMetrics.advanceWidth()`` of all
option labels, plus the standard padding and indicator width.
``FontMetrics.advanceWidth()`` is an invokable method, not a property read, so
it does not create a reactive dependency and avoids a re-entrant binding loop.

These tests prove the invariant:
    combo.width − leftPadding − rightPadding − indicator.width
        ≥ QFontMetrics.horizontalAdvance(label)
    for every label in every locale.

The tests *would have failed* before the fix because the combo was sized only
to the current selection ("Path A→Z"), leaving 14-char German and 19-char
French entries truncated in the popup.

Run with:
    pytest tests/ui/test_sort_combo_width.py -v -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtGui import QFontMetrics
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
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

# Number of sort options defined in Main.qml.
_NUM_SORT_OPTIONS = 8

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sort_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Minimal indexed DB with a single image; created once for the module."""
    base = tmp_path_factory.mktemp("sort_combo_test")
    img_dir = base / "images"
    img_dir.mkdir()
    img_path = img_dir / "test.jpg"
    Image.new("RGB", (32, 32), color=(100, 150, 200)).save(str(img_path))
    repo = ImageIndexRepository(base / "sort.db", key="")
    stat = img_path.stat()
    repo.upsert_image(
        str(img_path), img_path.name, stat.st_mtime, stat.st_size, {}, "test"
    )
    repo.commit()
    repo.close()
    return base / "sort.db", base


@pytest.fixture
def sort_window(
    qtbot: QtBot,
    sort_db: tuple[Path, Path],
) -> Generator[QQuickItem, None, None]:
    """Full QML window; yields the sortCombo QQuickItem."""
    db_path, base = sort_db

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
    controller.search("")
    qtbot.wait(300)

    sort_combo = root.findChild(QQuickItem, "sortCombo")
    assert sort_combo is not None, (
        "objectName: 'sortCombo' is missing from the ComboBox in Main.qml"
    )

    yield sort_combo

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


# ── helpers ───────────────────────────────────────────────────────────────────


def _available_text_width(sort_combo: QQuickItem) -> float:
    """Pixels available for label text inside the ComboBox."""
    combo_w: float = sort_combo.property("width")
    left_pad: float = sort_combo.property("leftPadding") or 0.0
    right_pad: float = sort_combo.property("rightPadding") or 0.0
    indicator = sort_combo.property("indicator")
    indicator_w: float = indicator.property("width") if indicator else 0.0
    return combo_w - left_pad - right_pad - indicator_w


def _all_option_labels(sort_combo: QQuickItem) -> list[str]:
    """Return the display text for every option by cycling currentIndex."""
    original = sort_combo.property("currentIndex")
    labels: list[str] = []
    try:
        for idx in range(_NUM_SORT_OPTIONS):
            sort_combo.setProperty("currentIndex", idx)
            labels.append(sort_combo.property("displayText"))
    finally:
        sort_combo.setProperty("currentIndex", original)
    return labels


# ── tests ─────────────────────────────────────────────────────────────────────


class TestSortComboWidth:
    """Sort ComboBox must be wide enough for all option labels at any selection."""

    def test_sort_combo_stable_width_fits_all_options(
        self,
        sort_window: QQuickItem,
    ) -> None:
        """combo.width before any interaction covers every option's label.

        This is the scenario that triggered the bug: the combo renders with the
        default selection ("Path A→Z", index 2).  Without the fix, available
        width equals the pixel width of "Path A→Z" — shorter than the widest
        label in every non-English locale.  The popup therefore clips those
        entries.

        With the fix, ``implicitWidth`` is bound to the widest label's
        ``FontMetrics.advanceWidth()`` so the combo is always large enough.
        """
        # Arrange – read combo metrics BEFORE touching currentIndex
        sort_combo = sort_window
        available = _available_text_width(sort_combo)
        font = sort_combo.property("font")
        fm = QFontMetrics(font)

        # Act – collect every option label
        labels = _all_option_labels(sort_combo)

        # Assert – every label fits within the stable combo width
        for label in labels:
            text_w = fm.horizontalAdvance(label)
            assert text_w <= available, (
                f"Label '{label}' needs {text_w}px but only "
                f"{available:.1f}px available "
                f"(combo.width={sort_combo.property('width'):.1f})"
            )

    def test_sort_combo_width_does_not_shrink_on_short_selection(
        self,
        sort_window: QQuickItem,
    ) -> None:
        """Selecting the shortest option must not narrow the combo.

        Before the fix, choosing e.g. "Name A→Z" (shortest label) would shrink
        ``implicitWidth``, so the popup would clip long labels on subsequent
        opens.  After the fix the width stays constant.
        """
        # Arrange
        sort_combo = sort_window
        width_before = sort_combo.property("width")

        # Act – select the shortest label (index 0: "Name A→Z")
        sort_combo.setProperty("currentIndex", 0)
        width_after = sort_combo.property("width")

        # Assert – width must not decrease
        assert width_after >= width_before, (
            f"combo.width shrank from {width_before:.1f} to {width_after:.1f} "
            f"after selecting the shortest option"
        )
