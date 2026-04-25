"""E2E GUI tests for format filter switching against the real user database.

Opens the full QML window backed by ``~/.exif-turbo/data/index/index.db``,
unlocks it, then drives the controller's ``setExtFilter`` slot to verify that:

- every format bucket shown in the UI returns the correct result count, and
- switching and clearing filters updates results correctly.

The expected counts are read dynamically from ``get_format_counts()`` so the
tests remain valid even if the real DB is re-indexed.

Run with:
    pytest tests/ui/test_ext_filter_real_db_e2e.py -v -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from pytestqt.qtbot import QtBot

from exif_turbo.config import default_db_path, thumb_cache_dir, settings_path
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.view_models.app_controller import AppController

_REAL_DB = default_db_path()
_REAL_DB_KEY = "HurzHurz"
_PAUSE_MS = 700

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def real_format_counts() -> dict[str, int]:
    """Read the expected per-format counts directly from the DB (no GUI)."""
    if not _REAL_DB.exists():
        pytest.skip(f"Real DB not found at {_REAL_DB}")
    repo = ImageIndexRepository(_REAL_DB, key=_REAL_DB_KEY)
    counts = dict(repo.get_format_counts())
    repo.close()
    return counts


@pytest.fixture
def window(
    qtbot: QtBot,
) -> Generator[tuple[AppController, SearchListModel], None, None]:
    """Full QML window backed by the real user DB; one fresh window per test."""
    if not _REAL_DB.exists():
        pytest.skip(f"Real DB not found at {_REAL_DB}")

    cache_dir = thumb_cache_dir(_REAL_DB)
    settings = SettingsModel(settings_path(_REAL_DB))

    search_model = SearchListModel(cache_dir=cache_dir)
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    controller = AppController(_REAL_DB, search_model, exif_model, folder_model, settings)

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel", settings)
    ctx.setContextProperty("thirdPartyLicensesHtml", "")
    ctx.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)

    yield controller, search_model

    engine.deleteLater()
    qtbot.wait(200)


def _unlock(controller: AppController, qtbot: QtBot) -> None:
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=10000):
        controller.unlock(_REAL_DB_KEY)
    qtbot.wait(_PAUSE_MS)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_real_db_unlock_shows_all_images(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
    real_format_counts: dict[str, int],
) -> None:
    # Arrange
    controller, search_model = window
    expected_total = sum(real_format_counts.values())

    # Act
    _unlock(controller, qtbot)

    # Assert
    print(f"\n  Total results: {controller.totalResults}  (expected {expected_total})")
    assert not controller.isLocked
    assert controller.totalResults == expected_total


def test_real_db_ext_filter_cr2_matches_format_count(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
    real_format_counts: dict[str, int],
) -> None:
    # Arrange
    controller, search_model = window
    _unlock(controller, qtbot)
    if "cr2" not in real_format_counts:
        pytest.skip("No cr2 images in real DB")
    expected = real_format_counts["cr2"]

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=10000):
        controller.setExtFilter("cr2")
    qtbot.wait(_PAUSE_MS)

    # Assert
    print(f"\n  cr2 filter: got {controller.totalResults}, expected {expected}")
    assert controller.totalResults == expected
    assert search_model.rowCount() > 0


def test_real_db_ext_filter_jpg_matches_format_count(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
    real_format_counts: dict[str, int],
) -> None:
    # Arrange
    controller, search_model = window
    _unlock(controller, qtbot)
    if "jpg" not in real_format_counts:
        pytest.skip("No jpg images in real DB")
    expected = real_format_counts["jpg"]

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=10000):
        controller.setExtFilter("jpg")
    qtbot.wait(_PAUSE_MS)

    # Assert
    print(f"\n  jpg filter: got {controller.totalResults}, expected {expected}")
    assert controller.totalResults == expected


def test_real_db_ext_filter_tif_matches_format_count(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
    real_format_counts: dict[str, int],
) -> None:
    # Arrange
    controller, search_model = window
    _unlock(controller, qtbot)
    if "tif" not in real_format_counts:
        pytest.skip("No tif images in real DB")
    expected = real_format_counts["tif"]

    # Act
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=10000):
        controller.setExtFilter("tif")
    qtbot.wait(_PAUSE_MS)

    # Assert
    print(f"\n  tif filter: got {controller.totalResults}, expected {expected}")
    assert controller.totalResults == expected


def test_real_db_ext_filter_switch_cr2_to_jpg(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
    real_format_counts: dict[str, int],
) -> None:
    # Arrange — start with cr2 filter
    controller, search_model = window
    _unlock(controller, qtbot)
    if "cr2" not in real_format_counts or "jpg" not in real_format_counts:
        pytest.skip("cr2 or jpg not present in real DB")

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=10000):
        controller.setExtFilter("cr2")
    qtbot.wait(_PAUSE_MS)
    assert controller.totalResults == real_format_counts["cr2"]

    # Act — switch to jpg
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=10000):
        controller.setExtFilter("jpg")
    qtbot.wait(_PAUSE_MS)

    # Assert
    print(f"\n  After switch cr2→jpg: got {controller.totalResults}, expected {real_format_counts['jpg']}")
    assert controller.totalResults == real_format_counts["jpg"]


def test_real_db_ext_filter_clear_restores_total(
    qtbot: QtBot,
    window: tuple[AppController, SearchListModel],
    real_format_counts: dict[str, int],
) -> None:
    # Arrange — apply a filter first
    controller, search_model = window
    _unlock(controller, qtbot)
    expected_total = sum(real_format_counts.values())
    first_ext = next(iter(real_format_counts))

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=10000):
        controller.setExtFilter(first_ext)
    qtbot.wait(_PAUSE_MS)
    assert controller.totalResults == real_format_counts[first_ext]

    # Act — clear the filter
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=10000):
        controller.setExtFilter("")
    qtbot.wait(_PAUSE_MS)

    # Assert
    print(f"\n  After clear: got {controller.totalResults}, expected {expected_total}")
    assert controller.totalResults == expected_total
