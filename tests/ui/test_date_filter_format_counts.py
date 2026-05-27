"""E2E tests: File Format facet counts must update when a date filter is active.

Bug
───
When the user clicks a year bar in the timeline histogram the search results
are correctly filtered to that year, but the File Format facet chips continue
to show counts for *all* images — ignoring the date filter entirely.

Root cause
──────────
``SearchWorker.run()`` calls ``repo.get_format_counts(...)`` without passing
``date_from`` / ``date_to``.  ``get_format_counts`` itself also has no date
parameters, so it always counts across the whole DB regardless of the active
date range.

Expected behaviour
──────────────────
After applying a date filter the format facet counts must reflect only the
images that fall within the active date range.

How the tests prove the bug
───────────────────────────
A DB is seeded with images of distinct formats split across two years:

  - 3 JPEG + 1 TIFF  →  captured in 2010
  - 2 PNG            →  captured in 2015

With the bug:

* Filtering to 2010 still lists "PNG · 2" in the format chips.
* Filtering to 2015 still lists "JPG · 3" and "TIF · 1".

After the fix:

* 2010 filter shows only JPG · 3 and TIF · 1.
* 2015 filter shows only PNG · 2.

Run with::

    pytest tests/ui/test_date_filter_format_counts.py -v -s
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.view_models.app_controller import AppController

_PAUSE_MS = 400

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

_YEAR_2010 = 2010
_YEAR_2015 = 2015

# fname, PIL format, capture year
_IMAGES: list[tuple[str, str, int]] = [
    ("a.jpg", "JPEG", _YEAR_2010),
    ("b.jpg", "JPEG", _YEAR_2010),
    ("c.jpg", "JPEG", _YEAR_2010),
    ("d.tif", "TIFF", _YEAR_2010),
    ("e.png", "PNG",  _YEAR_2015),
    ("f.png", "PNG",  _YEAR_2015),
]

_ALL_COUNTS  = {"jpg": 3, "png": 2, "tif": 1}
_2010_COUNTS = {"jpg": 3, "tif": 1}
_2015_COUNTS = {"png": 2}


def _year_range(year: int) -> tuple[int, int]:
    """Return (ts_start, ts_end) for a full calendar year.

    Mirrors the QML ``onClicked`` handler::

        var yStart = Math.floor(Date.UTC(yr,   0, 1) / 1000)
        var yEnd   = Math.floor(Date.UTC(yr+1, 0, 1) / 1000) - 1
    """
    start = math.floor(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
    end   = math.floor(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp()) - 1
    return start, end


def _formats(controller: AppController) -> dict[str, int]:
    return {f["ext"]: f["count"] for f in json.loads(controller.availableFormats)}


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def mixed_year_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """DB with JPEGs/TIFFs in 2010 and PNGs in 2015; shared across the module."""
    base = tmp_path_factory.mktemp("date_format_counts")
    img_dir = base / "images"
    img_dir.mkdir()

    repo = ImageIndexRepository(base / "test.db", key="")
    for fname, pil_fmt, year in _IMAGES:
        img_path = img_dir / fname
        Image.new("RGB", (32, 32)).save(str(img_path), format=pil_fmt)
        stat = img_path.stat()
        captured = datetime(year, 6, 15, 12, 0, tzinfo=timezone.utc).timestamp()
        repo.upsert_image(
            str(img_path), fname, stat.st_mtime, stat.st_size,
            {}, fname,
            captured_at=captured,
        )
    repo.commit()
    repo.close()
    return base / "test.db", base


@pytest.fixture
def window(
    qtbot: QtBot,
    mixed_year_db: tuple[Path, Path],
) -> Generator[AppController, None, None]:
    """Full QML window backed by mixed_year_db; one fresh controller per test."""
    db_path, base = mixed_year_db

    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model   = ExifListModel()
    folder_model = FolderListModel()
    settings     = SettingsModel(base / "settings.json")
    controller   = AppController(db_path, search_model, exif_model, folder_model, settings)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller",      controller)
    ctx.setContextProperty("searchModel",     search_model)
    ctx.setContextProperty("exifModel",       exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel",   settings)
    ctx.setContextProperty("thirdPartyLicensesHtml", "")
    ctx.setContextProperty("userManualUrl",   "")
    engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
        controller.unlock("")
    qtbot.wait(_PAUSE_MS)

    yield controller

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


# ── tests ─────────────────────────────────────────────────────────────────────


class TestDateFilterFormatCounts:
    """Format facet counts must respect the active date filter."""

    def test_no_date_filter_shows_all_format_counts(
        self,
        qtbot: QtBot,
        window: AppController,
    ) -> None:
        """Baseline: with no date filter all formats and their totals are visible."""
        # Arrange / Act — counts are set during unlock; no further action needed.
        controller = window

        # Assert
        assert _formats(controller) == _ALL_COUNTS

    def test_date_filter_2010_hides_png_format_chip(
        self,
        qtbot: QtBot,
        window: AppController,
    ) -> None:
        """Filtering to 2010 must remove PNG from format facets.

        Bug: ``get_format_counts`` ignores ``date_from``/``date_to``, so PNG
        (only present in 2015) still appears with count 2 even though no PNG
        images match the 2010 date range.
        """
        # Arrange
        controller = window
        y_start, y_end = _year_range(_YEAR_2010)

        # Act
        with qtbot.waitSignal(controller.availableFormatsChanged, timeout=3000):
            controller.setDateFilter(y_start, y_end)
        qtbot.wait(_PAUSE_MS)

        # Assert — PNG must not appear; only JPG and TIF images are in 2010
        fmt = _formats(controller)
        assert fmt == _2010_COUNTS, (
            f"Expected {_2010_COUNTS!r} after {_YEAR_2010} date filter, got {fmt!r}. "
            f"PNG count={fmt.get('png', 0)} should be 0 — "
            f"get_format_counts does not apply the date filter."
        )

    def test_date_filter_2015_shows_only_png_format_chip(
        self,
        qtbot: QtBot,
        window: AppController,
    ) -> None:
        """Filtering to 2015 must remove JPG and TIF from format facets.

        Bug: ``get_format_counts`` ignores ``date_from``/``date_to``, so JPG
        and TIF (only in 2010) still appear even though no such images match
        the 2015 date range.
        """
        # Arrange
        controller = window
        y_start, y_end = _year_range(_YEAR_2015)

        # Act
        with qtbot.waitSignal(controller.availableFormatsChanged, timeout=3000):
            controller.setDateFilter(y_start, y_end)
        qtbot.wait(_PAUSE_MS)

        # Assert — only PNG must appear; JPG and TIF images are only in 2010
        fmt = _formats(controller)
        assert fmt == _2015_COUNTS, (
            f"Expected {_2015_COUNTS!r} after {_YEAR_2015} date filter, got {fmt!r}. "
            f"JPG count={fmt.get('jpg', 0)}, TIF count={fmt.get('tif', 0)} "
            f"should both be 0 — get_format_counts does not apply the date filter."
        )
