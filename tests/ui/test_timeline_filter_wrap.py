"""E2E tests: Timeline Filter year bars must wrap instead of being clipped.

Bug
───
The date-filter histogram (``dateFilterRow``) uses a ``Flickable + Row`` to
display per-year bars.  The ``dateFilterRow`` has a fixed
``implicitHeight: 68``.  When there are more year bars than fit horizontally
in the panel, the ``Flickable`` silently clips the overflow — bars beyond
the visible edge are invisible and there is no scroll affordance shown to the
user.

Expected behaviour
──────────────────
When the total width of all year bars exceeds the available panel width, the
histogram container must grow taller so that the excess bars wrap to
additional rows.  Every year bar must be reachable without horizontal
scrolling.

How the test proves the bug
───────────────────────────
The test seeds the database with 40 years of images (1985–2024).  At the
default 1200 px window width the left panel is ≈600 px wide, leaving ≈500 px
for bars; 40 bars × 20 px = 800 px clearly overflows.

``histFlickable`` has ``objectName: "histFlickable"`` so it can be located
with ``findChild``.  The invariant checked is:

  ``histFlickable.contentWidth ≤ histFlickable.width``

This assertion *fails* with the current ``Flickable`` layout because
``contentWidth (800 px) > width (≈500 px)`` — proving the bug.

Once the layout is changed to a wrapping ``Flow``, the ``Flickable`` is
removed and the assertion is vacuously satisfied (the ``Flickable`` object no
longer exists).  A secondary assertion then verifies that ``dateFilterRow``
grew taller than the original 68 px single-row height.

Run with::

    pytest tests/ui/test_timeline_filter_wrap.py -v -s

A screenshot is written to the OS temp directory each run.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.providers.thumb_image_provider import ThumbnailImageProvider
from exif_turbo.ui.view_models.app_controller import AppController
from exif_turbo.utils.thumb_cache import thumb_cache_name_from_stamp

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

# Sample images from the schweiz test collection, cycled across all years.
_SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample-data" / "schweiz"
_SAMPLE_JPGS: list[Path] = sorted(_SAMPLE_DIR.rglob("*.jpg"))

# Years seeded into the DB — 65 years guarantees bar overflow at any normal panel width.
# 65 bars × 20 px/bar = 1300 px, far exceeding any reasonable left-panel width.
_YEARS = list(range(1960, 2025))

# Each bar is 18 px wide with 2 px spacing → 20 px per bar.
_BAR_STEP_PX = 20

# Original fixed height in the unfixed QML (single-row height used as sentinel).
_ORIGINAL_SINGLE_ROW_HEIGHT = 68

# Minimum bar pixels before the layout is considered ready.
_LAYOUT_READY_MIN_CONTENT_PX = 200

# Thumbnail size written to the cache (matches app default).
_THUMB_SIZE = (144, 144)

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def timeline_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """DB with one image per year from 1960–2024 using real sample images.

    Each year gets a resized copy of a schweiz sample JPEG (cycled).  Thumbnail
    PNGs are pre-built into ``base/thumbs`` so the UI renders real images.
    """
    base = tmp_path_factory.mktemp("timeline_wrap_test")
    db_path = base / "timeline.db"
    img_dir = base / "images"
    thumbs_dir = base / "thumbs"
    img_dir.mkdir()
    thumbs_dir.mkdir()

    # Resize template images once; cycle through them for the 65 years.
    templates: list[Image.Image] = []
    for src in _SAMPLE_JPGS:
        t = Image.open(src)
        t.thumbnail((600, 450), Image.LANCZOS)
        templates.append(t)

    repo = ImageIndexRepository(db_path, key="")
    for i, year in enumerate(_YEARS):
        ts = datetime.datetime(
            year, 6, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
        ).timestamp()
        img_path = img_dir / f"year_{year}.jpg"
        tpl = templates[i % len(templates)]
        tpl.convert("RGB").save(str(img_path), "JPEG", quality=75)

        stat = img_path.stat()
        # Pre-build thumbnail PNG so ThumbnailImageProvider can serve it.
        thumb_name = thumb_cache_name_from_stamp(str(img_path), stat.st_mtime, stat.st_size)
        thumb = tpl.copy()
        thumb.thumbnail(_THUMB_SIZE, Image.LANCZOS)
        thumb.convert("RGBA").save(str(thumbs_dir / thumb_name), "PNG")

        repo.upsert_image(
            str(img_path),
            img_path.name,
            stat.st_mtime,
            stat.st_size,
            {},
            f"photo from {year}",
            captured_at=ts,
        )
    repo.commit()
    repo.close()
    return db_path, base


@pytest.fixture
def timeline_window(
    qtbot: QtBot,
    timeline_db: tuple[Path, Path],
) -> Generator[tuple[QQuickItem, AppController, QQmlApplicationEngine], None, None]:
    """Full QML window loaded with timeline data; yields (root, controller, engine)."""
    db_path, base = timeline_db

    thumb_provider = ThumbnailImageProvider()
    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings_model = SettingsModel(base / "settings.json")
    filter_proxy = CheckedFilterProxyModel()
    filter_proxy.setSourceModel(search_model)
    controller = AppController(
        db_path, search_model, exif_model, folder_model,
        thumb_provider=thumb_provider,
    )
    controller.set_filter_proxy(filter_proxy)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("thumb", thumb_provider)
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

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
        controller.unlock("")

    with qtbot.waitSignal(controller.yearCountsChanged, timeout=5000):
        controller.search("")

    # Allow QML reactive bindings to propagate.
    qtbot.wait(400)

    yield root, controller, engine

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


# ── helpers ───────────────────────────────────────────────────────────────────


def _save_screenshot(window: QQuickItem, name: str) -> None:
    """Grab the window and write it to the OS temp directory; non-fatal."""
    import tempfile

    try:
        out = Path(tempfile.gettempdir()) / name
        img = window.grabWindow()
        img.save(str(out))
        print(f"\nScreenshot saved to: {out}")
    except Exception:  # noqa: BLE001
        pass


# ── tests ─────────────────────────────────────────────────────────────────────


class TestTimelineFilterWrap:
    """Timeline Filter histogram must show all year bars without horizontal clipping."""

    def test_timeline_filter_year_bars_visible_without_horizontal_clipping(
        self,
        qtbot: QtBot,
        timeline_window: tuple[QQuickItem, AppController, QQmlApplicationEngine],
    ) -> None:
        # Arrange
        root, _controller, _engine = timeline_window

        date_filter_row = root.findChild(QQuickItem, "dateFilterRow")
        assert date_filter_row is not None, (
            "objectName: 'dateFilterRow' is missing from the Rectangle in Main.qml"
        )

        # Assert — the date filter panel must be visible (year data loaded).
        qtbot.waitUntil(
            lambda: date_filter_row.property("visible") is True,
            timeout=3000,
        )

        hist_flickable = root.findChild(QQuickItem, "histFlickable")

        if hist_flickable is not None:
            # Wait for Qt Quick to compute the Row's implicitWidth so that the
            # Flickable's contentWidth is non-zero before we assert on it.
            qtbot.waitUntil(
                lambda: hist_flickable.property("contentWidth") > _LAYOUT_READY_MIN_CONTENT_PX,
                timeout=3000,
            )

        # Act — wait for thumbnails to render, then capture the current state.
        qtbot.wait(800)
        _save_screenshot(root, "timeline_clip_bug.png")

        if hist_flickable is not None:
            # Current (unfixed) layout: Flickable must not clip bars.
            content_w: float = hist_flickable.property("contentWidth")
            visible_w: float = hist_flickable.property("width")
            assert content_w <= visible_w, (
                f"Timeline Filter clips year bars: contentWidth ({content_w:.0f} px) "
                f"> visible width ({visible_w:.0f} px).  "
                f"{len(_YEARS)} year bars × {_BAR_STEP_PX} px/bar = "
                f"{len(_YEARS) * _BAR_STEP_PX} px total — bars beyond the visible "
                f"edge are silently hidden.  Replace the Flickable+Row with a "
                f"wrapping Flow so that all bars remain reachable."
            )
        else:
            # Fixed layout (Flow): the panel must grow to accommodate wrapped rows.
            panel_h: float = date_filter_row.property("height")
            assert panel_h > _ORIGINAL_SINGLE_ROW_HEIGHT, (
                f"dateFilterRow height ({panel_h:.0f} px) is not taller than the "
                f"original single-row height ({_ORIGINAL_SINGLE_ROW_HEIGHT} px).  "
                f"With {len(_YEARS)} year bars the Flow must wrap to multiple rows."
            )
