"""E2E tests reproducing the thumbnail-loading bug on the Search tab.

Manual observation (bug report):
  - After searching and selecting a result, the full-size preview loads correctly.
  - BUT the small thumbnails in the search-result cards remain blank.

Root cause (to be fixed later):
  ``_start_auto_thumbs()`` is only triggered after an indexing run completes.
  When the app opens against a pre-existing indexed DB with no pending folder
  scans, thumb building is never started, so every ``ThumbnailSourceRole`` stays
  ``""`` for the lifetime of the session — even though the images are fully
  indexed and the preview provider works fine.

Test structure:
  * test_search_and_select_loads_preview
      Documents the working side: preview (selectedImageSource) IS set.
  * test_thumbnail_source_empty_when_cache_is_empty
      Baseline: with an empty cache, thumbnailSource is "" for every row.
  * test_thumbnails_appear_when_cache_has_prebuilt_files
      When thumb files already exist (from a prior session) and are present
      when the model is created, thumbnailSource returns a file:// URI.
  * test_start_auto_thumbs_populates_thumbnail_source
      If _start_auto_thumbs() IS called explicitly, thumbs are built and
      refresh_thumbnails() makes them available via the model.
  * test_thumbnail_source_stays_empty_for_preindexed_db_without_pending_scans
      BUG: Opening the app with an already-indexed DB (no pending folder scans)
      never triggers thumb building.  thumbnailSource stays "" and
      isBuildingThumbs stays False throughout the session.
      This test PASSES now (documents the current broken state) and should be
      **updated or removed** once the fix is in place.

Run with:
    pytest tests/ui/test_thumbnail_loading.py -v -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.view_models.app_controller import AppController
from exif_turbo.utils.thumb_cache import thumb_cache_name_from_stamp

# ── Module-scoped indexed DB ───────────────────────────────────────────────────

_CAMERAS = [
    ("canon_r5.jpg", "Canon", "EOS R5", "2024:01:15 10:30:00"),
    ("nikon_z9.jpg", "Nikon", "Z 9", "2024:02:20 14:00:00"),
    ("sony_a7iv.jpg", "Sony", "A7 IV", "2024:03:10 08:45:00"),
]


@pytest.fixture(scope="module")
def indexed_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Real indexed DB with three camera images and no registered folders.

    Simulates a DB that was indexed in a previous session (or on another
    machine): images are fully indexed but no IndexedFolder rows exist, so
    ``get_pending_folders()`` returns nothing and no scan is triggered at
    unlock time.
    """
    base = tmp_path_factory.mktemp("thumb_e2e")
    img_dir = base / "images"
    img_dir.mkdir()

    repo = ImageIndexRepository(base / "index.db", key="")
    for fname, make, model, date in _CAMERAS:
        img_path = img_dir / fname
        # Use a recognisable solid colour so thumbnails are visually distinct.
        Image.new("RGB", (64, 64), color=(100, 150, 200)).save(
            str(img_path), format="JPEG"
        )
        stat = img_path.stat()
        metadata = {
            "FileName": fname,
            "Make": make,
            "Model": model,
            "DateTimeOriginal": date,
        }
        text = f"{fname} {make} {model} {date}"
        repo.upsert_image(
            str(img_path), fname, stat.st_mtime, stat.st_size, metadata, text
        )
    repo.commit()
    repo.close()
    return base / "index.db", base


# ── Per-test controller factories ─────────────────────────────────────────────


def _make_controller(
    db_path: Path,
    cache_dir: Path,
) -> AppController:
    """Construct a minimal AppController backed by the given DB and cache dir."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    search_model = SearchListModel(cache_dir=cache_dir)
    return AppController(
        db_path,
        search_model,
        ExifListModel(),
        FolderListModel(),
    )


def _shutdown(ctrl: AppController) -> None:
    """Cancel any running workers and close the DB connection."""
    if ctrl._thumb_worker and ctrl._thumb_worker.isRunning():
        ctrl._thumb_worker.cancel()
        ctrl._thumb_worker.wait(5000)
    if ctrl._index_worker and ctrl._index_worker.isRunning():
        ctrl._index_worker.cancel()
        ctrl._index_worker.wait(5000)
    ctrl.close()


@pytest.fixture
def ctrl_empty_cache(
    indexed_db: tuple[Path, Path],
    tmp_path: Path,
) -> Generator[AppController, None, None]:
    """AppController with an empty thumb cache.

    Reproduces opening the app on a machine where no thumbnails have been
    built yet (fresh install, wiped cache, or first session after indexing).
    """
    db_path, _ = indexed_db
    ctrl = _make_controller(db_path, tmp_path / "thumbs")
    yield ctrl
    _shutdown(ctrl)


@pytest.fixture
def ctrl_prebuilt_cache(
    indexed_db: tuple[Path, Path],
    tmp_path: Path,
) -> Generator[AppController, None, None]:
    """AppController with pre-built thumbnail files in the cache.

    Reproduces reopening the app when thumbs were generated in a prior session.
    The PNG files are created manually using the same hash key the ThumbWorker
    and SearchListModel use, so they are immediately found by _scan_cache_dir().
    """
    db_path, _ = indexed_db
    cache_dir = tmp_path / "thumbs_prebuilt"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Build stub thumbnail files with the correct hash-based filenames.
    repo = ImageIndexRepository(db_path, key="")
    stamps = repo.get_all_stamps()
    repo.close()
    for path, (mtime, size) in stamps.items():
        name = thumb_cache_name_from_stamp(path, mtime, size)
        Image.new("RGB", (32, 32), color=(200, 100, 50)).save(
            str(cache_dir / name), "PNG"
        )

    ctrl = _make_controller(db_path, cache_dir)
    yield ctrl
    _shutdown(ctrl)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _thumb_sources(ctrl: AppController) -> list[str]:
    """Return the ThumbnailSourceRole value for every row in the search model."""
    model = ctrl._search_model
    return [
        model.data(model.index(i, 0), SearchListModel.ThumbnailSourceRole) or ""
        for i in range(model.rowCount())
    ]


# ── Tests: preview loading (works) ────────────────────────────────────────────


def test_search_and_select_loads_preview(
    qtbot: QtBot,
    ctrl_empty_cache: AppController,
) -> None:
    """Selecting a search result fires selectedImageSourceChanged — preview works."""
    ctrl = ctrl_empty_cache

    # Arrange — unlock so the search model is populated
    with qtbot.waitSignal(ctrl.totalResultsChanged, timeout=3000):
        ctrl.unlock("")
    assert ctrl.totalResults == 3

    # Act — select the first result; wait for the debounce timer to fire
    with qtbot.waitSignal(ctrl.selectedImageSourceChanged, timeout=2000):
        ctrl.selectResult(0)

    # Assert — the full-size preview source is set to an image://preview/ URI
    assert ctrl.selectedImageSource.startswith("image://preview/"), (
        f"Expected a preview URI, got: {ctrl.selectedImageSource!r}"
    )


# ── Tests: thumbnail sources (broken) ─────────────────────────────────────────


def test_thumbnail_source_empty_when_cache_is_empty(
    qtbot: QtBot,
    ctrl_empty_cache: AppController,
) -> None:
    """With an empty cache, every ThumbnailSourceRole is '' after searching."""
    ctrl = ctrl_empty_cache

    # Arrange + Act
    with qtbot.waitSignal(ctrl.totalResultsChanged, timeout=3000):
        ctrl.unlock("")
    assert ctrl._search_model.rowCount() == 3

    # Assert — no thumbnail files exist, so every source must be empty
    sources = _thumb_sources(ctrl)
    assert all(src == "" for src in sources), (
        f"Expected all thumbnail sources to be empty (no cache), got: {sources}"
    )


def test_thumbnails_appear_when_cache_has_prebuilt_files(
    qtbot: QtBot,
    ctrl_prebuilt_cache: AppController,
) -> None:
    """Pre-built thumb files present at model-creation time are returned immediately.

    This is the 'happy path' for a repeat session: thumbs exist from before,
    _scan_cache_dir() finds them at __init__ time, and data() returns file://
    URIs without any explicit refresh.
    """
    ctrl = ctrl_prebuilt_cache

    # Arrange + Act
    with qtbot.waitSignal(ctrl.totalResultsChanged, timeout=3000):
        ctrl.unlock("")
    assert ctrl._search_model.rowCount() == 3

    # Assert — every result card has a resolvable file:// thumbnail URI
    sources = _thumb_sources(ctrl)
    assert all(src.startswith("file://") for src in sources), (
        f"Expected all results to have a file:// thumbnail URI, got: {sources}"
    )


def test_start_auto_thumbs_populates_thumbnail_source(
    qtbot: QtBot,
    ctrl_empty_cache: AppController,
) -> None:
    """After _start_auto_thumbs() runs to completion, ThumbnailSourceRole is set.

    Verifies that the ThumbWorker → _on_thumb_done → refresh_thumbnails()
    pipeline correctly updates the model so QML can display the thumbnails.
    """
    ctrl = ctrl_empty_cache

    # Arrange — unlock first so _repo is set and search model is populated
    with qtbot.waitSignal(ctrl.totalResultsChanged, timeout=3000):
        ctrl.unlock("")
    assert ctrl._search_model.rowCount() == 3

    # Act — manually trigger thumbnail building (the call the app skips at startup)
    ctrl._start_auto_thumbs()
    assert ctrl.isBuildingThumbs, "ThumbWorker should have started"

    # Wait for the worker to finish (isBuildingThumbs → False)
    qtbot.waitUntil(lambda: not ctrl.isBuildingThumbs, timeout=15_000)

    # Assert — model now returns file:// URIs for every result card
    sources = _thumb_sources(ctrl)
    assert all(src.startswith("file://") for src in sources), (
        f"Expected file:// thumbnail URIs after building, got: {sources}"
    )


def test_start_auto_thumbs_reports_only_missing_count_not_total_db_size(
    qtbot: QtBot,
    ctrl_prebuilt_cache: AppController,
) -> None:
    """ThumbWorker reports the number of *missing* thumbs, not the total DB size.

    After a small rescan the progress bar must show e.g. "0 / 2" (only the
    newly-added images) rather than "0 / 50 000" (the entire collection).
    When all thumbnails already exist the total must be 0.
    """
    ctrl = ctrl_prebuilt_cache

    # Arrange — unlock; all thumbs are pre-built so nothing should need building
    with qtbot.waitSignal(ctrl.totalResultsChanged, timeout=3000):
        ctrl.unlock("")
    assert ctrl._search_model.rowCount() == 3

    # Wait for the worker triggered by unlock() to finish
    qtbot.waitUntil(lambda: not ctrl.isBuildingThumbs, timeout=15_000)

    # Assert — zero images needed thumbnails, so thumbTotal reported was 0
    assert ctrl.thumbTotal == 0, (
        f"Expected thumbTotal=0 when all thumbs are cached, got {ctrl.thumbTotal}"
    )


def test_thumbnail_building_triggered_for_preindexed_db_without_pending_scans(
    qtbot: QtBot,
    ctrl_empty_cache: AppController,
) -> None:
    """FIX: thumbnail building IS triggered when opening a pre-existing indexed DB.

    unlock() now calls _start_auto_thumbs() when the scan queue is empty,
    so thumbnails are built immediately rather than staying blank forever.
    """
    ctrl = ctrl_empty_cache

    # Arrange + Act — unlock; thumb worker should start right away
    with qtbot.waitSignal(ctrl.totalResultsChanged, timeout=3000):
        ctrl.unlock("")

    # Assert — thumb building was triggered synchronously inside unlock()
    assert ctrl.isBuildingThumbs, (
        "Expected isBuildingThumbs=True immediately after unlock() on a pre-indexed DB"
    )

    # Wait for the worker to finish and refresh the model
    qtbot.waitUntil(lambda: not ctrl.isBuildingThumbs, timeout=15_000)

    # Assert — thumbnails are now populated in the search result cards
    sources = _thumb_sources(ctrl)
    assert all(src.startswith("file://") for src in sources), (
        f"Expected file:// thumbnail URIs after unlock on pre-indexed DB, got: {sources}"
    )


def test_rescan_triggers_exactly_one_thumb_build_not_multiple(
    qtbot: QtBot,
    indexed_db: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    """Pressing Rescan must not trigger multiple thumb-build runs, and the
    cancelled unlock-time worker must not corrupt the post-index worker's state.

    Before the fixes, two bugs combined:
    1. unlock()-triggered Worker A raced with the post-index Worker B, causing
       2-3 builds.
    2. Worker A's late 'canceled' signal (arriving after B started) called
       _on_thumb_canceled, which stopped Worker B's refresh timer and set
       _is_building_thumbs=False while B was still running — hiding the progress
       bar and preventing mid-build thumbnail refreshes.

    After the fixes:
    - _actually_start_indexing() disconnects Worker A's signals before cancelling,
      so its late 'canceled' can never touch Worker B's state.
    - isBuildingThumbs stays True continuously throughout Worker B's entire run.
    """
    db_path, base = indexed_db
    cache_dir = tmp_path / "thumbs"
    cache_dir.mkdir()

    img_dir = tmp_path / "images"
    img_dir.mkdir()
    for fname, make, model, date in _CAMERAS:
        img_path = img_dir / fname
        Image.new("RGB", (32, 32), color=(80, 120, 200)).save(str(img_path), "JPEG")

    local_db = tmp_path / "rescan_test.db"
    repo = ImageIndexRepository(local_db, key="")
    folder_repo = IndexedFolderRepository(local_db, key="")
    folder_obj = folder_repo.add(str(img_dir))
    folder_repo.update_status(folder_obj.id, "indexed", image_count=len(_CAMERAS))
    for fname, make, model, date in _CAMERAS:
        img_path = img_dir / fname
        stat = img_path.stat()
        metadata = {"FileName": fname, "Make": make, "Model": model}
        repo.upsert_image(str(img_path), fname, stat.st_mtime, stat.st_size, metadata, fname)
    repo.commit()
    repo.close()
    folder_repo.close()

    search_model = SearchListModel(cache_dir=cache_dir)
    ctrl = AppController(local_db, search_model, ExifListModel(), FolderListModel())

    try:
        # Unlock — starts Worker A (unlock-triggered)
        with qtbot.waitSignal(ctrl.totalResultsChanged, timeout=3000):
            ctrl.unlock("")
        assert ctrl.totalResults == len(_CAMERAS)

        # Track isBuildingThumbs transitions
        build_starts: list[int] = []
        build_stops: list[int] = []

        def _on_building_changed() -> None:
            if ctrl.isBuildingThumbs:
                build_starts.append(1)
            else:
                build_stops.append(1)

        ctrl.isBuildingThumbsChanged.connect(_on_building_changed)

        # Act — rescan; _actually_start_indexing cancels Worker A and
        # disconnects its signals
        folder_id = ctrl._folder_model._rows[0].id
        ctrl.rescanFolder(folder_id)

        # Wait for indexing + thumb build to fully complete
        qtbot.waitUntil(
            lambda: not ctrl.isBuildingThumbs and not ctrl.isIndexing,
            timeout=30_000,
        )

        # Assert — at most one thumb-build start during the rescan
        assert len(build_starts) <= 1, (
            f"Expected ≤1 thumb-build start during rescan, got {len(build_starts)}: "
            "multiple starts indicate Worker A was not properly cancelled."
        )

        # Assert — the only extra False transition is from cancelling Worker A
        # before indexing starts.  The sequence must be: [False(cancel A), True(B
        # starts), False(B done)].  build_stops - build_starts == 1 is correct;
        # a larger gap means Worker A's late 'canceled' fired _on_thumb_canceled
        # while Worker B was running.
        assert len(build_stops) <= len(build_starts) + 1, (
            f"isBuildingThumbs went False {len(build_stops)} times vs "
            f"True {len(build_starts)} times: more than one extra False means "
            "Worker A's 'canceled' signal is still firing _on_thumb_canceled "
            "while Worker B is running."
        )

        # All thumbnails must be present at the end
        sources = _thumb_sources(ctrl)
        assert all(src.startswith("file://") for src in sources), (
            f"Expected all thumbnails populated after rescan, got: {sources}"
        )

    finally:
        _shutdown(ctrl)
