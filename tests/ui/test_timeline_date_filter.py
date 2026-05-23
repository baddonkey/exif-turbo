"""E2E tests: Timeline date filter must work for years before 1970.

Bug
───
The timeline histogram lets users select a date range by clicking a year bar.
For years before 1970 (Unix epoch) JavaScript's ``Date.UTC()`` returns a
*negative* Unix timestamp.  The QML ``onClicked`` handler computes::

    var yStart = Math.floor(Date.UTC(yr, 0, 1) / 1000)   // negative for yr < 1970
    var yEnd   = Math.floor(Date.UTC(yr+1, 0, 1) / 1000) - 1

and calls ``controller.setDateFilter(yStart, yEnd)``.

``AppController.setDateFilter`` guards with ``date_from > 0``, so any
negative value is treated as "not set" (mapped to ``None``).  As a result,
clicking the bar for any year ≤ 1969 silently leaves the filter unset:
``controller.dateFrom`` stays at 0 and *all* bars remain highlighted as if
no year had been selected.

Expected behaviour
──────────────────
Clicking a year bar must restrict the search to that single year regardless
of whether it falls before or after 1970.  After the click (or the equivalent
``setDateFilter`` call) ``controller.dateFrom`` must be non-zero and equal to
the expected year-start timestamp.

How the test proves the bug
───────────────────────────
``_js_year_range(year)`` reproduces the exact integer timestamps that the QML
``onClicked`` handler computes via ``Math.floor(Date.UTC(...) / 1000)``.
Calling ``setDateFilter`` with those values for year 1960 must result in
``controller.dateFrom == yStart``.

Under the current code the assertion *fails* because ``date_from > 0`` is
``False`` for the negative timestamp ``-315619200``, so ``_date_from`` is set
to ``None`` and the public ``dateFrom`` property returns 0.

Run with::

    pytest tests/ui/test_timeline_date_filter.py -v -s
"""

from __future__ import annotations

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
from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.providers.thumb_image_provider import ThumbnailImageProvider
from exif_turbo.ui.view_models.app_controller import AppController

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

# Pre-1970 year to exercise the negative-timestamp path.
_PRE_1970_YEAR = 1960
# Post-1970 year used as a control case.
_POST_1970_YEAR = 2010

_SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample-data" / "schweiz"
_SAMPLE_JPGS: list[Path] = sorted(_SAMPLE_DIR.rglob("*.jpg"))


def _js_year_range(year: int) -> tuple[int, int]:
    """Return (yStart, yEnd) exactly as QML's onClicked computes them.

    Mirrors::

        var yStart = Math.floor(Date.UTC(yr,   0, 1) / 1000)
        var yEnd   = Math.floor(Date.UTC(yr+1, 0, 1) / 1000) - 1
    """
    y_start = math.floor(
        datetime(year, 1, 1, tzinfo=timezone.utc).timestamp()
    )
    y_end = math.floor(
        datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp()
    ) - 1
    return y_start, y_end


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def date_filter_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """DB with one image each for 1960 and 2010 (pre- and post-epoch).

    Real schweiz sample JPEGs are used so the UI can render thumbnails.
    """
    base = tmp_path_factory.mktemp("date_filter_test")
    db_path = base / "date_filter.db"
    img_dir = base / "images"
    img_dir.mkdir()

    template = Image.open(_SAMPLE_JPGS[0])
    template.thumbnail((300, 300), Image.LANCZOS)

    repo = ImageIndexRepository(db_path, key="")
    for i, year in enumerate([_PRE_1970_YEAR, _POST_1970_YEAR]):
        ts = datetime(year, 6, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        img_path = img_dir / f"year_{year}.jpg"
        template.convert("RGB").save(str(img_path), "JPEG", quality=75)
        stat = img_path.stat()
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
def date_filter_window(
    qtbot: QtBot,
    date_filter_db: tuple[Path, Path],
) -> Generator[tuple[AppController, QQmlApplicationEngine], None, None]:
    """Full QML window loaded with pre- and post-1970 data; yields (controller, engine)."""
    db_path, base = date_filter_db

    thumb_provider = ThumbnailImageProvider()
    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings_model = SettingsModel(base / "settings.json")
    filter_proxy = CheckedFilterProxyModel()
    filter_proxy.setSourceModel(search_model)
    controller = AppController(
        db_path,
        search_model,
        exif_model,
        folder_model,
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

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=5000):
        controller.unlock("")

    with qtbot.waitSignal(controller.yearCountsChanged, timeout=5000):
        controller.search("")

    qtbot.wait(300)

    yield controller, engine

    controller.close()
    engine.deleteLater()
    qtbot.wait(200)


# ── tests ─────────────────────────────────────────────────────────────────────


class TestTimelineDateFilter:
    """Timeline date filter must apply correctly for any year, including pre-1970."""

    def test_setDateFilter_pre1970_year_sets_dateFrom_to_year_start(
        self,
        qtbot: QtBot,
        date_filter_window: tuple[AppController, QQmlApplicationEngine],
    ) -> None:
        """Clicking the bar for a pre-1970 year must activate the date filter.

        Bug: ``setDateFilter`` uses ``date_from > 0`` as the "is set" guard.
        For year 1960 the QML sends ``yStart = -315619200`` (negative).  That
        guard discards the value, ``dateFrom`` stays 0, and the QML sees no
        active filter so all bars remain highlighted.
        """
        # Arrange
        controller, _engine = date_filter_window
        y_start, y_end = _js_year_range(_PRE_1970_YEAR)
        assert y_start < 0, "Test precondition: 1960 must produce a negative timestamp"

        # Act — simulate the QML onClicked handler for the 1960 bar.
        # NOTE: with the current bug, dateFilterChanged is *never* emitted because
        # setDateFilter's 'date_from > 0' guard discards -315619200 as None, and
        # None == self._date_from (already None) triggers the early-return.  We
        # therefore cannot waitSignal here — just call and wait for Qt events.
        controller.setDateFilter(y_start, y_end)
        qtbot.wait(300)

        # Assert — the filter must reflect the selected year, not the "unset" sentinel
        assert controller.dateFrom != 0, (
            f"controller.dateFrom is 0 after clicking the {_PRE_1970_YEAR} bar — "
            f"setDateFilter discarded the negative timestamp {y_start} because of "
            f"the 'date_from > 0' guard.  All bars remain highlighted instead of "
            f"only {_PRE_1970_YEAR}."
        )
        assert controller.dateFrom == y_start, (
            f"Expected dateFrom={y_start}, got {controller.dateFrom}"
        )
        assert controller.dateTo == y_end, (
            f"Expected dateTo={y_end}, got {controller.dateTo}"
        )

    def test_setDateFilter_post1970_year_sets_dateFrom_to_year_start(
        self,
        qtbot: QtBot,
        date_filter_window: tuple[AppController, QQmlApplicationEngine],
    ) -> None:
        """Control case: a post-1970 year must also apply the filter correctly."""
        # Arrange
        controller, _engine = date_filter_window
        y_start, y_end = _js_year_range(_POST_1970_YEAR)
        assert y_start > 0, "Test precondition: 2010 must produce a positive timestamp"

        # Act
        with qtbot.waitSignal(controller.dateFilterChanged, timeout=3000):
            controller.setDateFilter(y_start, y_end)
        qtbot.wait(300)

        # Assert
        assert controller.dateFrom == y_start
        assert controller.dateTo == y_end

    def test_setDateFilter_pre1970_year_narrows_search_results(
        self,
        qtbot: QtBot,
        date_filter_window: tuple[AppController, QQmlApplicationEngine],
    ) -> None:
        """Filtering to a pre-1970 year must exclude the post-1970 image.

        The DB contains exactly one image from 1960 and one from 2010.  After
        applying the 1960 filter only one result should be returned.  With the
        bug, no filter is applied and both images are returned.
        """
        # Arrange
        controller, _engine = date_filter_window
        controller.clearDateFilter()
        qtbot.wait(200)
        y_start, y_end = _js_year_range(_PRE_1970_YEAR)

        # Act — same note: signal is not emitted due to the bug.
        controller.setDateFilter(y_start, y_end)
        qtbot.wait(500)

        # Assert — only the 1960 image should match
        assert controller.totalResults == 1, (
            f"Expected 1 result after filtering to {_PRE_1970_YEAR}, "
            f"got {controller.totalResults} — the date filter was not applied "
            f"(negative timestamp {y_start} was discarded by 'date_from > 0')."
        )
