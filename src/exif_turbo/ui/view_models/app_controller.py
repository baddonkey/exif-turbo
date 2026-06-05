from __future__ import annotations

import html as html_lib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from ..providers.preview_image_provider import PreviewImageProvider
    from ..providers.thumb_image_provider import ThumbnailImageProvider

import sqlcipher3
from PySide6.QtCore import Property, QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication

from ...data.image_index_repository import ImageIndexRepository
from ...data.indexed_folder_repository import IndexedFolderRepository
from ...i18n import _
from ...indexing.exif_metadata_extractor import get_exiftool_version
from ...indexing.image_utils import RAW_EXTENSIONS
from ...models.search_result import SearchResult
from ...utils.preview_cache import (
    clear_cached_previews_for,
    count_cached_previews,
    list_existing_previews,
    preview_cache_name_from_stamp,
    preview_dir,
)
from ...utils.thumb_cache import thumb_cache_name_from_stamp
from ..models.checked_filter_proxy_model import CheckedFilterProxyModel
from ..models.exif_list_model import ExifListModel
from ..models.folder_list_model import FolderListModel
from ..models.search_list_model import SearchListModel
from ..models.settings_model import SettingsModel
from ..workers.ai_scan_worker import AiScanWorker
from ..workers.ai_search_worker import AiSearchWorker
from ..workers.bulk_op_worker import BulkOpWorker
from ..workers.folder_tree_worker import FolderTreeWorker
from ..workers.index_worker import IndexWorker
from ..workers.password_change_worker import PasswordChangeWorker
from ..workers.preview_build_worker import PreviewBuildWorker
from ..workers.search_worker import SearchPageWorker, SearchWorker
from ..workers.thumb_worker import ThumbWorker
from ...utils.preview_render import MAX_PREVIEW_PX, render_preview

_PAGE_SIZE = 50
_BROWSE_JUMP_PAGE_SIZE = 500
_DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) // 2)
# Pillow LANCZOS resampling is GIL-bound; running too many thumb threads while
# IndexWorker is active starves the scan thread and GUI event loop on Windows.
# 2 threads gives a mild throughput boost without measurable GIL pressure.
_MAX_THUMB_WORKERS = 2
_log = logging.getLogger(__name__)


def _pyinstaller_clean_env() -> dict[str, str]:
    """Return os.environ with LD_LIBRARY_PATH restored to its pre-bundle value.

    PyInstaller's bootloader prepends the _internal/ bundle directory to
    LD_LIBRARY_PATH so that bundled .so files are found.  Any subprocess
    launched from the app inherits this polluted path, which causes system
    tools like xdg-open to pick up incompatible bundled libraries and fail
    silently.  PyInstaller saves the original value as LD_LIBRARY_PATH_ORIG.
    """
    env = os.environ.copy()
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


class AppController(QObject):
    statusTextChanged = Signal()
    isIndexingChanged = Signal()
    isBuildingThumbsChanged = Signal()
    isBuildingPreviewsChanged = Signal()
    isAiScanningChanged = Signal()
    isAiSearchModeChanged = Signal()
    aiEnabledChanged = Signal()
    aiScanFolderIdChanged = Signal()
    aiScanIsFullRescanChanged = Signal()
    aiScanCurrentChanged = Signal()
    aiScanTotalChanged = Signal()
    aiScanCurrentFileChanged = Signal()
    previewBuildFolderIdChanged = Signal()
    previewCurrentChanged = Signal()
    previewTotalChanged = Signal()
    previewCurrentFileChanged = Signal()
    useRawPreviewChanged = Signal()
    isCancelingChanged = Signal()
    detailsHtmlChanged = Signal()
    geoLocationUrlChanged = Signal()
    geoGoogleMapsUrlChanged = Signal()
    geoWikipediaUrlChanged = Signal()
    findScrollFractionChanged = Signal()
    selectedImageSourceChanged = Signal()
    selectedThumbSourceChanged = Signal()
    selectedHasPreviewChanged = Signal()
    totalResultsChanged = Signal()
    loadedResultsChanged = Signal()
    searchErrorChanged = Signal()
    isLockedChanged = Signal()
    isNewDatabaseChanged = Signal()
    unlockErrorChanged = Signal()
    indexCurrentChanged = Signal()
    indexTotalChanged = Signal()
    indexCurrentFileChanged = Signal()
    thumbCurrentChanged = Signal()
    thumbTotalChanged = Signal()
    thumbCurrentFileChanged = Signal()
    sortByChanged = Signal()
    extFilterChanged = Signal()
    currentResultRowChanged = Signal()
    availableFormatsChanged = Signal()
    folderTreeChanged = Signal()
    folderFilterChanged = Signal()
    searchFolderFiltersChanged = Signal()
    indexedFoldersChanged = Signal()
    indexQueuePositionChanged = Signal()
    indexQueueTotalChanged = Signal()
    checkedCountChanged = Signal()
    checkedOnlyFilterChanged = Signal()
    currentProxyResultRowChanged = Signal()
    isBusyChanged = Signal()
    isSearchingChanged = Signal()
    busyLabelChanged = Signal()
    bulkProgressChanged = Signal()
    isUnlockingChanged = Signal()
    passwordChangeFinished = Signal(bool, str)  # (success, message)
    busyCancelableChanged = Signal()
    exiftoolMissingChanged = Signal()
    exiftoolVersionChanged = Signal()
    clipboardCopyDone = Signal(str)  # message to show in toast
    dateFilterChanged = Signal()
    yearCountsChanged = Signal()

    def __init__(
        self,
        db_path: Path,
        search_model: SearchListModel,
        exif_model: ExifListModel,
        folder_model: FolderListModel,
        settings: SettingsModel | None = None,
        cache_dir: Path | None = None,
        thumb_provider: "ThumbnailImageProvider | None" = None,
        preview_provider: "PreviewImageProvider | None" = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._settings = settings
        self._cache_dir = cache_dir
        self._thumb_provider = thumb_provider
        self._preview_provider = preview_provider
        self._repo: ImageIndexRepository | None = None
        self._folder_repo: IndexedFolderRepository | None = None
        self._key = ""
        self._search_model = search_model
        self._exif_model = exif_model
        self._folder_model = folder_model
        self._status_text = _("Enter the database password to continue")
        self._is_locked = True
        self._is_new_database = not db_path.exists()
        self._unlock_error = ""
        self._is_indexing = False
        self._is_building_thumbs = False
        self._is_canceling = False
        self._index_current = 0
        self._index_total = 0
        self._index_current_file = ""
        self._thumb_current = 0
        self._thumb_total = 0
        self._thumb_current_file = ""
        self._details_html = ""
        self._geo_location_url = ""
        self._geo_google_maps_url = ""
        self._geo_wikipedia_url = ""
        self._find_scroll_fraction = 0.0
        self._selected_image_source = ""
        self._selected_thumb_source = ""
        self._selected_has_preview = False
        self._current_result_row: int = -1
        self._preview_bust: int = 0
        self._total_results = 0
        self._loaded_results = 0
        self._loaded_offset = 0
        self._loading = False
        self._search_error: str = ""
        self._details_plain_text = ""
        self._query_text = ""
        self._find_text = ""
        self._find_positions: List[Tuple[int, int]] = []
        self._find_index = -1
        self._sort_by = self._settings.sort_by if self._settings else "captured_desc"
        self._ext_filter = ""
        self._available_formats: str = "[]"
        self._folder_filter: str = ""
        self._search_folder_filters: set[str] = set()
        # Snapshot of Search-tab filter state, captured when the user switches
        # to the Browse tab so the Browse view can show un-filtered folder
        # contents. Restored when the user returns to the Search tab.
        # `None` means no snapshot is currently held.
        self._search_state_snapshot: dict | None = None
        # When restoring from Browse → Search, load enough pages of results so
        # the previously-selected image (identified by its DB id) is included in
        # the model.  0 means no pending restore.
        self._pending_restore_image_id: int = 0
        # When jumping from Search → Browse, keep the target image id here
        # until it is actually loaded and selected in the Browse model.
        self._pending_browse_jump_id: int = 0
        self._folder_tree: str = "[]"
        self._folder_tree_dirty: bool = False
        self._folder_tree_worker: FolderTreeWorker | None = None
        self._folder_tree_worker_shows_busy_ui: bool = False
        self._pending_preview_path: str = ""
        # DB-stored (mtime, size) for the pending preview; used to compute the
        # on-disk cache filename without statting the (possibly missing) source.
        self._pending_preview_stamp: tuple[float, int] | None = None
        # Pixel count (width * height) from indexed exiftool metadata; passed
        # to providers so they can route large images to pyvips without probing.
        self._pending_preview_pixel_count: int | None = None
        self._index_worker: IndexWorker | None = None
        self._thumb_worker: ThumbWorker | None = None
        self._preview_worker: PreviewBuildWorker | None = None
        self._is_building_previews: bool = False
        self._preview_build_folder_id: int = 0
        self._preview_current: int = 0
        self._preview_total: int = 0
        self._preview_current_file: str = ""
        self._preview_oversized_skipped: int = 0
        self._ai_scan_worker: AiScanWorker | None = None
        self._is_ai_scanning: bool = False
        self._is_ai_search_mode: bool = False
        self._ai_enabled: bool = self._settings.ai_enabled if self._settings else False
        self._ai_search_worker: AiSearchWorker | None = None
        self._last_ai_query: str = ""
        self._last_ai_precision: str = "normal"
        self._has_ai_search_run: bool = False
        # Set to True by aiSearch() so _on_search_finished always selects row 0
        # for a fresh AI search (not a browse-restore).
        self._ai_select_first: bool = False
        # All AI result rows held in memory so we can page them without SQL.
        self._ai_result_cache: list[SearchResult] = []
        self._ai_scan_folder_id: int = 0
        self._ai_scan_is_full_rescan: bool = False
        self._ai_scan_current: int = 0
        self._ai_scan_total: int = 0
        self._ai_scan_current_file: str = ""
        self._use_raw_preview: bool = False
        self._scanning_folder_id: int | None = None
        self._scan_queue: list[tuple[int, bool]] = []
        self._index_queue_position = 0
        self._index_queue_total = 0
        self._app_closing = False
        self._pending_thumb_restart = False
        self._search_worker: SearchWorker | None = None
        self._load_more_worker: SearchPageWorker | None = None
        self._page_load_mode = "append"
        self._search_serial: int = 0
        self._date_from: int | None = None
        self._date_to: int | None = None
        self._year_counts: str = "[]"
        # Workers that have emitted results_ready but whose QThread cleanup has
        # not yet completed.  We keep them in this set so the Python object is
        # not garbage-collected while QThreadWrapper::run() is still unwinding
        # its C++ stack (which holds a reference via AutoDecRef).  Each worker
        # is removed in _on_search_worker_done, which is connected to
        # QThread.finished — emitted only after run() has fully returned.
        self._finishing_search_workers: set[QThread] = set()
        # Params for a search that arrived while one was already in-flight.
        # Consumed immediately when the current worker finishes.
        self._pending_search_params: dict | None = None
        self._pending_search_show_busy_ui: bool = True
        self._search_shows_busy_ui: bool = False
        self._filter_proxy: CheckedFilterProxyModel | None = None
        self._checked_only_filter_active: bool = False
        self._checked_total_count: int = 0
        self._checked_in_results_count: int = 0
        self._is_busy: bool = False
        self._is_searching: bool = False
        self._busy_cancelable: bool = True
        self._busy_label: str = ""
        self._bulk_progress: int = 0
        self._bulk_progress_total: int = 0
        self._bulk_worker: BulkOpWorker | None = None
        self._pending_export_path: Path | None = None
        self._is_unlocking: bool = False
        self._exiftool_missing: bool = False
        self._exiftool_version: str = ""  # populated lazily by checkExiftool slot
        self._password_change_worker: PasswordChangeWorker | None = None
        self._password_change_old: str = ""
        self._password_change_new: str = ""
        # Timer: kick off a batch thumb build while indexing runs. Fires 5 s
        # after indexing begins so the DB has a first batch of rows to process.
        self._thumb_batch_timer = QTimer(self)
        self._thumb_batch_timer.setInterval(5_000)
        self._thumb_batch_timer.timeout.connect(self._start_auto_thumbs)
        # Timer: refresh the search list with newly written thumbs every 10 s
        # during a thumb build — ensures mid-batch thumbnails appear on macOS
        # where LowestPriority threads are aggressively throttled by the OS.
        self._thumb_refresh_timer = QTimer(self)
        self._thumb_refresh_timer.setInterval(10_000)
        self._thumb_refresh_timer.timeout.connect(self._on_thumb_refresh_tick)
        # Timer: resume workers after yielding I/O bandwidth to a preview load.
        # This is a fallback only — the primary trigger is onPreviewStatusChanged()
        # called by QML when the image reaches Ready or Error status.  The timer
        # fires after 10 s so workers are not stuck paused if QML never reports
        # (e.g. empty source, app minimised, or the image provider crashes).
        self._preview_resume_timer = QTimer(self)
        self._preview_resume_timer.setSingleShot(True)
        self._preview_resume_timer.setInterval(10_000)
        self._preview_resume_timer.timeout.connect(self._resume_thumb_for_preview)
        # Timer: delay the full preview load by 150 ms so visible card thumbnails
        # in the list get a chance to render before the heavier preview decode starts.
        self._preview_delay_timer = QTimer(self)
        self._preview_delay_timer.setSingleShot(True)
        self._preview_delay_timer.setInterval(150)
        self._preview_delay_timer.timeout.connect(self._load_pending_preview)
        self._last_progress_update: float = 0.0
        self._last_thumb_progress_update: float = 0.0

    # ── Properties ───────────────────────────────────────────────────────────

    @Property(bool, notify=isLockedChanged)
    def isLocked(self) -> bool:
        return self._is_locked

    @Property(bool, notify=isNewDatabaseChanged)
    def isNewDatabase(self) -> bool:
        return self._is_new_database

    @Property(str, notify=unlockErrorChanged)
    def unlockError(self) -> str:
        return self._unlock_error

    @Property(str, constant=True)
    def appVersion(self) -> str:
        from exif_turbo import __version__
        return __version__

    @Property(str, notify=statusTextChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(bool, notify=isIndexingChanged)
    def isIndexing(self) -> bool:
        return self._is_indexing

    @Property(bool, notify=isBuildingThumbsChanged)
    def isBuildingThumbs(self) -> bool:
        return self._is_building_thumbs

    # ── Preview cache build state ──────────────────────────────────────────────

    @Property(bool, notify=isBuildingPreviewsChanged)
    def isBuildingPreviews(self) -> bool:
        return self._is_building_previews

    @Property(int, notify=previewBuildFolderIdChanged)
    def previewBuildFolderId(self) -> int:
        return self._preview_build_folder_id

    @Property(int, notify=previewCurrentChanged)
    def previewCurrent(self) -> int:
        return self._preview_current

    @Property(int, notify=previewTotalChanged)
    def previewTotal(self) -> int:
        return self._preview_total

    @Property(str, notify=previewCurrentFileChanged)
    def previewCurrentFile(self) -> str:
        return self._preview_current_file

    @Property(bool, notify=useRawPreviewChanged)
    def useRawPreview(self) -> bool:
        return self._use_raw_preview

    # ── AI-scan state ──────────────────────────────────────────────────────────

    @Property(bool, notify=isAiScanningChanged)
    def isAiScanning(self) -> bool:
        return self._is_ai_scanning

    @Property(int, notify=aiScanFolderIdChanged)
    def aiScanFolderId(self) -> int:
        return self._ai_scan_folder_id

    @Property(bool, notify=aiScanIsFullRescanChanged)
    def aiScanIsFullRescan(self) -> bool:
        return self._ai_scan_is_full_rescan

    @Property(int, notify=aiScanCurrentChanged)
    def aiScanCurrent(self) -> int:
        return self._ai_scan_current

    @Property(int, notify=aiScanTotalChanged)
    def aiScanTotal(self) -> int:
        return self._ai_scan_total

    @Property(str, notify=aiScanCurrentFileChanged)
    def aiScanCurrentFile(self) -> str:
        return self._ai_scan_current_file

    # ── AI-search mode ─────────────────────────────────────────────────────────

    @Property(bool, notify=isAiSearchModeChanged)
    def isAiSearchMode(self) -> bool:
        return self._is_ai_search_mode

    @Property(bool, notify=aiEnabledChanged)
    def aiEnabled(self) -> bool:
        return self._ai_enabled

    @Slot(bool)
    def setAiEnabled(self, value: bool) -> None:
        if self._ai_enabled == value:
            return
        self._ai_enabled = value
        if self._settings:
            self._settings.setAiEnabled(value)
        # If AI is turned off while in AI mode, revert to EXIF mode.
        if not value and self._is_ai_search_mode:
            self._is_ai_search_mode = False
            self.isAiSearchModeChanged.emit()
        self.aiEnabledChanged.emit()

    @Property(bool, notify=isCancelingChanged)
    def isCanceling(self) -> bool:
        return self._is_canceling

    @Property(str, notify=detailsHtmlChanged)
    def detailsHtml(self) -> str:
        return self._details_html

    @Property(str, notify=detailsHtmlChanged)
    def detailsPlainText(self) -> str:
        return self._details_plain_text

    @Property(str, notify=geoLocationUrlChanged)
    def geoLocationUrl(self) -> str:
        return self._geo_location_url

    @Property(str, notify=geoGoogleMapsUrlChanged)
    def geoGoogleMapsUrl(self) -> str:
        return self._geo_google_maps_url

    @Property(str, notify=geoWikipediaUrlChanged)
    def geoWikipediaUrl(self) -> str:
        return self._geo_wikipedia_url

    @Property(float, notify=findScrollFractionChanged)
    def findScrollFraction(self) -> float:
        return self._find_scroll_fraction

    @Property(str, notify=selectedImageSourceChanged)
    def selectedImageSource(self) -> str:
        return self._selected_image_source

    @Property(str, notify=selectedImageSourceChanged)
    def pendingPreviewPath(self) -> str:
        return self._pending_preview_path

    @Property(str, notify=selectedThumbSourceChanged)
    def selectedThumbSource(self) -> str:
        return self._selected_thumb_source

    @Property(bool, notify=selectedHasPreviewChanged)
    def selectedHasPreview(self) -> bool:
        return self._selected_has_preview

    @Property(int, notify=currentResultRowChanged)
    def currentResultRow(self) -> int:
        return self._current_result_row

    @Property(int, notify=totalResultsChanged)
    def totalResults(self) -> int:
        return self._total_results

    @Property(int, notify=loadedResultsChanged)
    def loadedResults(self) -> int:
        return self._loaded_results

    @Property(str, notify=searchErrorChanged)
    def searchError(self) -> str:
        return self._search_error

    @Property(int, notify=indexCurrentChanged)
    def indexCurrent(self) -> int:
        return self._index_current

    @Property(int, notify=indexTotalChanged)
    def indexTotal(self) -> int:
        return self._index_total

    @Property(str, notify=indexCurrentFileChanged)
    def indexCurrentFile(self) -> str:
        return self._index_current_file

    @Property(int, notify=thumbCurrentChanged)
    def thumbCurrent(self) -> int:
        return self._thumb_current

    @Property(int, notify=thumbTotalChanged)
    def thumbTotal(self) -> int:
        return self._thumb_total

    @Property(str, notify=thumbCurrentFileChanged)
    def thumbCurrentFile(self) -> str:
        return self._thumb_current_file

    @Property(str, notify=sortByChanged)
    def sortBy(self) -> str:
        return self._sort_by

    @Property(str, notify=extFilterChanged)
    def extFilter(self) -> str:
        return self._ext_filter

    @Property(str, notify=availableFormatsChanged)
    def availableFormats(self) -> str:
        return self._available_formats

    @Property(str, notify=folderFilterChanged)
    def folderFilter(self) -> str:
        return self._folder_filter

    @Property(str, notify=searchFolderFiltersChanged)
    def searchFolderFilters(self) -> str:
        return json.dumps(sorted(self._search_folder_filters))

    @Property(int, notify=indexedFoldersChanged)
    def indexedFolderCount(self) -> int:
        return self._folder_model.rowCount()

    @Property(str, notify=indexedFoldersChanged)
    def searchFolderListJson(self) -> str:
        return json.dumps([
            {"path": f.path, "name": f.display_name}
            for f in self._folder_model._rows
            if f.enabled
        ])

    @Property(str, notify=folderTreeChanged)
    def folderTree(self) -> str:
        return self._folder_tree

    @Property(int, notify=indexQueuePositionChanged)
    def indexQueuePosition(self) -> int:
        return self._index_queue_position

    @Property(int, notify=indexQueueTotalChanged)
    def indexQueueTotal(self) -> int:
        return self._index_queue_total

    @Property(int, notify=checkedCountChanged)
    def checkedCount(self) -> int:
        return self._checked_total_count

    @Property(int, notify=checkedCountChanged)
    def checkedInResultsCount(self) -> int:
        return self._checked_in_results_count

    @Property(bool, notify=checkedOnlyFilterChanged)
    def checkedOnlyFilter(self) -> bool:
        return self._checked_only_filter_active

    @Property(int, notify=currentProxyResultRowChanged)
    def currentProxyResultRow(self) -> int:
        if self._filter_proxy is None or self._current_result_row < 0:
            return self._current_result_row
        return self._filter_proxy.proxy_row_for(self._current_result_row)

    @Property(bool, notify=isBusyChanged)
    def isBusy(self) -> bool:
        return self._is_busy

    @Property(bool, notify=isSearchingChanged)
    def isSearching(self) -> bool:
        return self._is_searching

    @Property(str, notify=busyLabelChanged)
    def busyLabel(self) -> str:
        return self._busy_label

    @Property(bool, notify=busyCancelableChanged)
    def busyCancelable(self) -> bool:
        return self._busy_cancelable

    @Property(int, notify=bulkProgressChanged)
    def bulkProgress(self) -> int:
        return self._bulk_progress

    @Property(int, notify=bulkProgressChanged)
    def bulkProgressTotal(self) -> int:
        return self._bulk_progress_total

    @Property(bool, notify=isUnlockingChanged)
    def isUnlocking(self) -> bool:
        return self._is_unlocking

    @Property(bool, notify=exiftoolMissingChanged)
    def exiftoolMissing(self) -> bool:
        return self._exiftool_missing

    @Property(str, notify=exiftoolVersionChanged)
    def exiftoolVersion(self) -> str:
        return self._exiftool_version

    @Property(float, notify=dateFilterChanged)
    def dateFrom(self) -> float:
        return float(self._date_from) if self._date_from is not None else -1.0

    @Property(float, notify=dateFilterChanged)
    def dateTo(self) -> float:
        return float(self._date_to) if self._date_to is not None else -1.0

    @Property(str, notify=yearCountsChanged)
    def yearCounts(self) -> str:
        return self._year_counts

    @Slot()
    def checkExiftool(self) -> None:
        """Re-probe exiftool and update exiftoolMissing / exiftoolVersion."""
        version = get_exiftool_version()
        missing = version == ""
        version_changed = version != self._exiftool_version
        missing_changed = missing != self._exiftool_missing
        self._exiftool_version = version
        self._exiftool_missing = missing
        if version_changed:
            self.exiftoolVersionChanged.emit()
        if missing_changed:
            self.exiftoolMissingChanged.emit()

    def set_filter_proxy(self, proxy: CheckedFilterProxyModel) -> None:
        self._filter_proxy = proxy
        proxy.filterActiveChanged.connect(self._on_filter_active_changed)

    def _on_filter_active_changed(self) -> None:
        self.checkedOnlyFilterChanged.emit()
        self.currentProxyResultRowChanged.emit()

    def _recompute_checked_in_results(self) -> None:
        """Recompute total + in-result mark counts respecting enabled folders."""
        if self._repo is None:
            self._checked_total_count = 0
            self._checked_in_results_count = 0
            return
        if self._search_model.checked_count == 0:
            self._checked_total_count = 0
            self._checked_in_results_count = 0
            return
        self._checked_total_count = self._repo.count_images(
            "",
            restrict_to_enabled_folders=(self._folder_repo is not None),
            marked_only=True,
        )
        path_filter = self._current_path_filter()
        self._checked_in_results_count = self._repo.count_images(
            self._query_text, ext_filter=self._ext_filter,
            path_filter=path_filter,
            restrict_to_enabled_folders=(self._folder_repo is not None),
            marked_only=True,
            date_from=self._date_from,
            date_to=self._date_to,
        )

    def _load_marks(self) -> None:
        """Restore marked image paths from the database into the in-memory set."""
        if self._repo is None:
            return
        try:
            paths = self._repo.get_marked_paths()
            self._search_model.set_checked_paths(paths)
            self._recompute_checked_in_results()
            self.checkedCountChanged.emit()
        except Exception as exc:
            _log.warning("Failed to load marks from DB: %s", exc)

    # ── Slots ─────────────────────────────────────────────────────────────────

    # ── Selection slots ───────────────────────────────────────────────────

    @Slot(bool)
    def setCheckedOnlyFilter(self, active: bool) -> None:
        if self._checked_only_filter_active == active:
            return
        self._checked_only_filter_active = active
        self.checkedOnlyFilterChanged.emit()
        self._run_search()

    def _current_path_filter(self) -> list[str] | None:
        if self._folder_filter:
            return [self._folder_filter]
        if self._search_folder_filters:
            return sorted(self._search_folder_filters)
        return None

    @Slot(int)
    def toggleChecked(self, proxy_row: int) -> None:
        row = self._filter_proxy.source_row_for(proxy_row) if self._filter_proxy else proxy_row
        is_checked_now = self._search_model.toggle_checked(row)
        path = self._search_model.get_path(row)
        if path is not None and self._repo is not None:
            self._repo.mark_image(path, is_checked_now)
        self._recompute_checked_in_results()
        self.checkedCountChanged.emit()

    @Slot()
    def selectAll(self) -> None:
        if self._repo is None:
            return
        self._start_bulk_op(
            "select_all",
            _("Selecting all matching images\u2026"),
            mark_value=True,
        )

    @Slot()
    def deselectAll(self) -> None:
        if self._repo is None:
            return
        self._start_bulk_op(
            "deselect_all",
            _("Deselecting all matching images\u2026"),
            mark_value=False,
        )

    @Slot()
    def invertSelection(self) -> None:
        if self._repo is None:
            return
        self._start_bulk_op(
            "invert",
            _("Inverting selection\u2026"),
        )

    @Slot()
    def selectMissingThumbnails(self) -> None:
        """Mark every matching image whose thumbnail is not yet cached.

        Images flagged unthumbnailable (``.skip`` sentinel) are excluded so
        running this repeatedly converges on the empty set.
        """
        if self._repo is None or self._cache_dir is None:
            return
        self._start_bulk_op(
            "select_missing_thumbs",
            _("Selecting images without a cached thumbnail\u2026"),
            cache_dir=self._cache_dir,
        )

    @Slot()
    def deleteMarkedImages(self) -> None:
        """Permanently delete every marked image from disk and the index.

        QML must confirm the destructive action with the user before invoking
        this slot.  Cached thumbnails / previews for the deleted images are
        also removed.
        """
        if self._repo is None:
            return
        if self._checked_total_count == 0:
            self._set_status(_("No marked images to delete."))
            return
        self._start_bulk_op(
            "delete_marked",
            _("Deleting marked images\u2026"),
            cache_dir=self._cache_dir,
        )

    @Slot(str)
    def exportMarkedMetadataJson(self, file_url: str) -> None:
        file_path = Path(QUrl(file_url).toLocalFile())
        if self._repo is None:
            return
        if self._checked_total_count == 0:
            self._set_status(_("No marked images to export."))
            return
        self._pending_export_path = file_path
        self._start_bulk_op(
            "export_json",
            _("Exporting metadata\u2026"),
            file_path=file_path,
            sort_by=self._sort_by,
        )

    @Slot()
    def cancelBulkOp(self) -> None:
        if self._bulk_worker is not None:
            self._bulk_worker.cancel()

    # ── Bulk-op worker helpers ────────────────────────────────────────────

    def _start_bulk_op(
        self,
        operation: str,
        label: str,
        *,
        mark_value: bool = True,
        file_path: Path | None = None,
        sort_by: str = "path_asc",
        cache_dir: Path | None = None,
    ) -> None:
        """Spawn a BulkOpWorker and show the busy overlay."""
        if self._is_busy:
            return
        self._bulk_worker = BulkOpWorker(
            self._db_path,
            self._key,
            operation,
            query=self._query_text,
            ext_filter=self._ext_filter,
            path_filter=self._current_path_filter(),
            restrict_to_enabled_folders=(self._folder_repo is not None),
            marked_only=self._checked_only_filter_active,
            mark_value=mark_value,
            file_path=file_path,
            sort_by=sort_by,
            cache_dir=cache_dir,
            date_from=self._date_from,
            date_to=self._date_to,
        )
        self._bulk_worker.progress.connect(self._on_bulk_progress)
        self._bulk_worker.finished.connect(self._on_bulk_finished)
        self._bulk_worker.failed.connect(self._on_bulk_failed)
        self._bulk_worker.canceled.connect(self._on_bulk_canceled)
        self._bulk_progress = 0
        self._bulk_progress_total = 0
        self._busy_label = label
        self._busy_cancelable = True
        self._is_busy = True
        self.isBusyChanged.emit()
        self.busyLabelChanged.emit()
        self.busyCancelableChanged.emit()
        self.bulkProgressChanged.emit()
        self._bulk_worker.start()

    def _on_bulk_progress(self, done: int, total: int) -> None:
        self._bulk_progress = done
        self._bulk_progress_total = total
        self.bulkProgressChanged.emit()

    def _on_bulk_finished(self) -> None:
        worker = self._bulk_worker
        self._is_busy = False
        self._bulk_worker = None
        self.isBusyChanged.emit()
        if worker is None:
            return
        if worker._operation == "select_all":
            # RETURNING paths come directly from the UPDATE transaction \u2014
            # no cold-cache SELECT needed.  For a plain select-all the new
            # checked-in-results count equals the total result count.
            self._search_model.add_to_checked(worker.result_paths)
            self._recompute_checked_in_results()
            self.checkedCountChanged.emit()
        elif worker._operation == "deselect_all":
            self._search_model.remove_from_checked(worker.result_paths)
            self._recompute_checked_in_results()
            self.checkedCountChanged.emit()
        elif worker._operation == "invert":
            self._search_model.add_to_checked(worker.result_paths_added)
            self._search_model.remove_from_checked(worker.result_paths_removed)
            self._recompute_checked_in_results()
            self.checkedCountChanged.emit()
        elif worker._operation == "select_missing_thumbs":
            self._search_model.set_checked_paths(worker.result_paths)
            self._recompute_checked_in_results()
            self.checkedCountChanged.emit()
        elif worker._operation == "delete_marked":
            # Refresh the search list so deleted rows disappear, and report
            # the outcome in the status bar.
            self._search_model.set_checked_paths(worker.result_paths)
            self._load_formats()
            self._invalidate_folder_tree()
            self._load_indexed_folders()
            self.search(self._query_text)
            parts = [
                _("Deleted {n} image(s).").format(n=worker.result_deleted_count)
            ]
            if worker.result_missing_count:
                parts.append(
                    _("{n} were already missing.").format(
                        n=worker.result_missing_count
                    )
                )
            if worker.result_failed_count:
                parts.append(
                    _("{n} could not be deleted.").format(
                        n=worker.result_failed_count
                    )
                )
            self._set_status(" ".join(parts))
        elif worker._operation == "export_json":
            fp = self._pending_export_path
            self._pending_export_path = None
            if fp is not None:
                self._set_status(
                    _("Exported {count} image(s) to {name}").format(
                        count=worker.result_export_count, name=fp.name
                    )
                )

    def _on_bulk_failed(self, msg: str) -> None:
        self._is_busy = False
        self._bulk_worker = None
        self.isBusyChanged.emit()
        self._set_status(_("Operation failed: {}").format(msg))

    def _on_bulk_canceled(self) -> None:
        self._is_busy = False
        self._bulk_worker = None
        self.isBusyChanged.emit()
        self._set_status(_("Operation canceled."))


    @Slot(str)
    def unlock(self, password: str) -> None:
        """Show the unlock spinner, then run the actual DB open after one paint frame."""
        if self._is_unlocking:
            return
        self._is_unlocking = True
        self._unlock_error = ""
        self.isUnlockingChanged.emit()
        self.unlockErrorChanged.emit()
        # Defer the blocking DB open by 50 ms so QML can repaint with the
        # spinner before the main thread is occupied with key derivation.
        QTimer.singleShot(50, lambda: self._do_unlock(password))

    def _do_unlock(self, password: str) -> None:
        repo: ImageIndexRepository | None = None
        folder_repo: IndexedFolderRepository | None = None
        try:
            repo = ImageIndexRepository(self._db_path, key=password)
            repo.count_images("")  # verify key — raises DatabaseError on wrong key
            folder_repo = IndexedFolderRepository(self._db_path, key=password)
            self._repo = repo
            self._folder_repo = folder_repo
            self._key = password
            self._unlock_error = ""
            self._is_locked = False
            self._is_new_database = False
            self._ext_filter = ""
            self._sort_by = self._settings.sort_by if self._settings else "captured_desc"
            self._folder_filter = ""
            self._search_folder_filters = set()
            self._date_from = None
            self._date_to = None
            self._status_text = ""
            self._is_unlocking = False
            self.isUnlockingChanged.emit()
            # Wipe plain PNG thumbs on first unlock with a password (one-time migration
            # to encrypted cache).  Thumbs are rebuilt as .enc by ThumbWorker.
            cache_dir = self._search_model.cache_dir
            if password and cache_dir.exists():
                plain_pngs = [
                    f for f in cache_dir.iterdir()
                    if f.suffix in (".png", ".skip") or f.name == "thumbs_skipped.log"
                ]
                if plain_pngs:
                    for f in plain_pngs:
                        try:
                            f.unlink()
                        except OSError:
                            pass
            # Configure the thumbnail provider and search model encryption mode.
            if self._thumb_provider is not None:
                self._thumb_provider.set_key(password, cache_dir)
            if self._preview_provider is not None:
                self._preview_provider.set_cache(cache_dir, password)
            self._search_model.set_encryption(bool(password))
            self.isLockedChanged.emit()
            self.unlockErrorChanged.emit()
            self.statusTextChanged.emit()
            # Check exiftool availability once after unlock and warn if missing.
            version = get_exiftool_version()
            self._exiftool_version = version
            self.exiftoolVersionChanged.emit()
            if version == "":
                self._exiftool_missing = True
                self.exiftoolMissingChanged.emit()
            self._load_formats()
            self._folder_tree_dirty = True  # loaded on demand when Browse tab is opened
            self._load_indexed_folders()
            self._load_marks()
            self.search("")
            # Resume only folders whose scan was interrupted in a previous session
            # (status = 'queued' or 'scanning').  Do NOT re-queue folders that are
            # already 'indexed' — that would trigger a full incremental re-scan of
            # all enabled folders on every startup.
            if self._folder_repo:
                for folder in self._folder_repo.get_pending_folders():
                    self._start_managed_folder_indexing(folder, force=False)
            # If no folder scan was queued (e.g. opening a pre-existing fully-indexed
            # DB), kick off thumbnail generation immediately so search-result cards
            # are populated without the user having to trigger an index run.
            if not self._scan_queue and not self._is_indexing:
                self._start_auto_thumbs()
        except sqlcipher3.DatabaseError:
            self._unlock_error = _("Wrong password — please try again.")
            self._is_unlocking = False
            self.isUnlockingChanged.emit()
            self.unlockErrorChanged.emit()
            if repo is not None:
                repo.close()
            if folder_repo is not None:
                folder_repo.close()
            self._repo = None
            self._folder_repo = None
            self._is_locked = True
        except Exception as exc:
            self._unlock_error = _("Failed to open database: {error}").format(error=exc)
            self._is_unlocking = False
            self.isUnlockingChanged.emit()
            self.unlockErrorChanged.emit()
            if repo is not None:
                repo.close()
            if folder_repo is not None:
                folder_repo.close()
            self._repo = None
            self._folder_repo = None
            self._is_locked = True

    @Slot(str, str)
    def changePassword(self, old_password: str, new_password: str) -> None:
        """Re-encrypt the SQLCipher database under *new_password*.

        SQLCipher's ``PRAGMA rekey`` rewrites every page of the database
        and can take several seconds on a large index, so the work runs on
        a :class:`PasswordChangeWorker` background thread.  While it runs
        the busy overlay blocks all GUI interaction (no Cancel button —
        rekey cannot be safely interrupted mid-flight).

        Emits :py:attr:`passwordChangeFinished` ``(success, message)`` on
        completion.
        """
        if self._is_locked or self._repo is None:
            self.passwordChangeFinished.emit(False, _("Database is locked."))
            return
        if self._is_indexing or self._is_building_thumbs or self._is_busy:
            self.passwordChangeFinished.emit(
                False,
                _("Cannot change password while indexing or thumb-building is running."),
            )
            return
        if old_password != self._key:
            self.passwordChangeFinished.emit(False, _("Current password is incorrect."))
            return
        if not new_password:
            self.passwordChangeFinished.emit(False, _("New password must not be empty."))
            return
        if new_password == old_password:
            self.passwordChangeFinished.emit(
                False, _("New password must differ from the current password.")
            )
            return
        # Close our long-lived connections so the worker is the sole writer
        # while the rekey is in flight.
        if self._folder_repo is not None:
            try:
                self._folder_repo.close()
            except Exception:  # noqa: BLE001
                _log.exception("Failed to close folder repository before rekey")
            self._folder_repo = None
        try:
            self._repo.close()
        except Exception:  # noqa: BLE001
            _log.exception("Failed to close image repository before rekey")
        self._repo = None
        # Configure busy overlay (non-cancelable).
        cache_dir = self._search_model.cache_dir
        self._busy_label = _("Changing password\u2026")
        self._busy_cancelable = False
        self._bulk_progress = 0
        self._bulk_progress_total = 0
        self._is_busy = True
        self.busyLabelChanged.emit()
        self.busyCancelableChanged.emit()
        self.bulkProgressChanged.emit()
        self.isBusyChanged.emit()
        # Spawn the worker.  Stash inputs on the controller for the result
        # handlers — keep separate fields so a concurrent bulk op can't
        # clobber them.
        self._password_change_worker = PasswordChangeWorker(
            self._db_path, old_password, new_password, cache_dir
        )
        self._password_change_old = old_password
        self._password_change_new = new_password
        self._password_change_worker.finished.connect(self._on_password_change_finished)
        self._password_change_worker.failed.connect(self._on_password_change_failed)
        self._password_change_worker.start()

    def _clear_busy_after_password_change(self) -> None:
        self._is_busy = False
        self._busy_cancelable = True
        self._busy_label = ""
        self.isBusyChanged.emit()
        self.busyCancelableChanged.emit()
        self.busyLabelChanged.emit()

    def _on_password_change_finished(self) -> None:
        new_password = self._password_change_new
        # Re-open the long-lived connections under the new key.
        try:
            self._repo = ImageIndexRepository(self._db_path, key=new_password)
            self._folder_repo = IndexedFolderRepository(self._db_path, key=new_password)
        except Exception as exc:  # noqa: BLE001
            _log.exception("Failed to reopen database after rekey")
            self._password_change_worker = None
            self._clear_busy_after_password_change()
            self.passwordChangeFinished.emit(
                False,
                _("Database password changed, but reopening failed: {error}").format(error=str(exc)),
            )
            return
        self._key = new_password
        if self._thumb_provider is not None:
            self._thumb_provider.set_key(new_password, self._search_model.cache_dir)
        if self._preview_provider is not None:
            self._preview_provider.set_cache(self._search_model.cache_dir, new_password)
        self._password_change_worker = None
        self._clear_busy_after_password_change()
        self.passwordChangeFinished.emit(True, _("Password changed successfully."))

    def _on_password_change_failed(self, message: str) -> None:
        old_password = self._password_change_old
        # Best-effort: try to reopen with the OLD key so the app stays usable.
        # If the failure was during rewrap (DB rekey already succeeded),
        # reopening with the old key will fail too — fall back to new key
        # and clear the thumb cache.
        reopened_key = old_password
        try:
            self._repo = ImageIndexRepository(self._db_path, key=old_password)
            self._repo.count_images("")  # verify
            self._folder_repo = IndexedFolderRepository(self._db_path, key=old_password)
        except Exception:  # noqa: BLE001
            _log.warning("Reopening with old key failed; trying new key (rewrap stage)")
            try:
                if self._repo is not None:
                    self._repo.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                new_password = self._password_change_new
                self._repo = ImageIndexRepository(self._db_path, key=new_password)
                self._folder_repo = IndexedFolderRepository(self._db_path, key=new_password)
                self._key = new_password
                reopened_key = new_password
                # Thumb cache may now be unreadable — clear it.
                cache_dir = self._search_model.cache_dir
                self._purge_thumb_cache(cache_dir)
                if self._thumb_provider is not None:
                    self._thumb_provider.set_key(new_password, cache_dir)
                if self._preview_provider is not None:
                    self._preview_provider.set_cache(cache_dir, new_password)
            except Exception:  # noqa: BLE001
                _log.exception("Failed to reopen database with either key")
                self._repo = None
                self._folder_repo = None
        self._password_change_worker = None
        self._clear_busy_after_password_change()
        if reopened_key == old_password:
            self.passwordChangeFinished.emit(
                False, _("Failed to change password: {error}").format(error=message)
            )
        else:
            self.passwordChangeFinished.emit(
                False,
                _("Password changed but thumbnail cache could not be re-wrapped ({error}). The cache has been cleared and will be rebuilt.").format(error=message),
            )

    @staticmethod
    def _purge_thumb_cache(cache_dir: Path) -> None:
        if not cache_dir.exists():
            return
        for entry in cache_dir.iterdir():
            if entry.is_file():
                try:
                    entry.unlink()
                except OSError:
                    pass

    def _set_search_error(self, message: str) -> None:
        if self._search_error == message:
            return
        self._search_error = message
        self.searchErrorChanged.emit()

    @Slot(str)
    def search(self, query: str) -> None:
        if self._repo is None:
            return
        new_query = query.strip()
        if new_query != self._query_text:
            self._current_result_row = 0  # new query — start from top
        self._query_text = new_query
        self._run_search()

    @Slot(str)
    def setSortBy(self, sort: str) -> None:
        if self._sort_by == sort:
            return
        self._sort_by = sort
        if self._settings:
            self._settings.setSortBy(sort)
        self._current_result_row = 0
        self.sortByChanged.emit()
        self._run_search()

    @Slot(str)
    def setExtFilter(self, ext: str) -> None:
        if self._ext_filter == ext:
            return
        self._ext_filter = ext
        self._current_result_row = 0
        self.extFilterChanged.emit()
        if self._rerun_ai_search_for_filter_change():
            return
        self._run_search()

    @Slot(str)
    def setFolderFilter(self, path: str) -> None:
        if self._folder_filter == path:
            return
        self._folder_filter = path
        self._current_result_row = 0
        self.folderFilterChanged.emit()
        if self._rerun_ai_search_for_filter_change():
            return
        self._run_search()

    @Slot(str)
    def toggleSearchFolderFilter(self, path: str) -> None:
        if path in self._search_folder_filters:
            self._search_folder_filters.discard(path)
        else:
            self._search_folder_filters.add(path)
        self._current_result_row = 0
        self.searchFolderFiltersChanged.emit()
        if self._rerun_ai_search_for_filter_change():
            return
        self._run_search()

    @Slot()
    def clearSearchFolderFilters(self) -> None:
        if not self._search_folder_filters:
            return
        self._search_folder_filters.clear()
        self._current_result_row = 0
        self.searchFolderFiltersChanged.emit()
        if self._rerun_ai_search_for_filter_change():
            return
        self._run_search()

    @Slot(str)
    def setSearchFolderFilter(self, path: str) -> None:
        new_set: set[str] = {path} if path else set()
        if new_set == self._search_folder_filters:
            return
        self._search_folder_filters = new_set
        self._current_result_row = 0
        self.searchFolderFiltersChanged.emit()
        if self._rerun_ai_search_for_filter_change():
            return
        self._run_search()

    def _rerun_ai_search_for_filter_change(self) -> bool:
        if not self._is_ai_search_mode:
            return False
        if not self._has_ai_search_run or self._db_path is None:
            return False
        self._ai_select_first = True
        self._start_ai_search_worker(self._last_ai_query, self._last_ai_precision)
        return True

    @Slot(str)
    @Slot(str, int)
    def browseFolder(self, path: str, target_id: int = 0) -> None:
        """Navigate to a folder in the Browse tab.

        Clears any active search query so the full folder contents are shown.
        Clicking the already-selected folder clears the filter.

        *target_id* is the DB primary key of the image to pre-scroll to once
        the folder results have loaded (passed from the "Browse →" button in
        QML).  0 means no pre-scroll target.
        """
        if self._folder_filter == path:
            self._folder_filter = ""
            self._pending_browse_jump_id = 0
            search_offset = 0
        else:
            self._query_text = ""
            self._folder_filter = path
            self._pending_browse_jump_id = target_id
            search_offset = 0
            if target_id and self._repo is not None:
                target_offset = self._repo.find_image_offset(
                    target_id,
                    query=self._query_text,
                    sort_by=self._sort_by,
                    ext_filter=self._ext_filter,
                    path_filter=[path],
                    restrict_to_enabled_folders=(self._folder_repo is not None),
                    marked_only=self._checked_only_filter_active,
                    date_from=self._date_from,
                    date_to=self._date_to,
                )
                if target_offset is not None:
                    search_offset = max(0, target_offset - (_PAGE_SIZE // 2))
        show_busy_ui = self._pending_browse_jump_id != 0
        self.folderFilterChanged.emit()
        self._run_search(show_busy_ui=show_busy_ui, offset=search_offset)

    @Slot(str)
    def enterBrowseTab(self, query_text: str = "") -> None:
        """Snapshot Search-tab filter state and clear it for Browse mode.

        Called by QML when the user switches from the Search tab to the
        Browse tab. Captures the current query text (passed in from the
        searchField QML control), search-folder-filters, extension filter
        and date range so they can be restored on return. The cleared
        state ensures Browse shows un-filtered folder contents.

        No-op if a snapshot is already held (e.g. Browse -> Settings ->
        Browse navigation should not overwrite the original snapshot).
        """
        if self._search_state_snapshot is not None:
            return
        self._search_state_snapshot = {
            "query_text": query_text,
            "search_folder_filters": set(self._search_folder_filters),
            "ext_filter": self._ext_filter,
            "date_from": self._date_from,
            "date_to": self._date_to,
            "checked_only_filter": self._checked_only_filter_active,
            "was_ai_search_mode": self._is_ai_search_mode,
            "current_image_id": self._search_model.get_image_id(self._current_result_row) or 0,
            "ai_rows": list(self._ai_result_cache) if self._is_ai_search_mode else None,
            "ai_total_results": self._total_results if self._is_ai_search_mode else 0,
            "ai_loaded_results": self._loaded_results if self._is_ai_search_mode else 0,
        }
        if self._is_ai_search_mode:
            self._is_ai_search_mode = False
            self.isAiSearchModeChanged.emit()
        self._query_text = ""
        if self._search_folder_filters:
            self._search_folder_filters.clear()
            self.searchFolderFiltersChanged.emit()
        if self._ext_filter:
            self._ext_filter = ""
            self.extFilterChanged.emit()
        if self._date_from is not None or self._date_to is not None:
            self._date_from = None
            self._date_to = None
        if self._checked_only_filter_active:
            self._checked_only_filter_active = False
            self.checkedOnlyFilterChanged.emit()
            self.dateFilterChanged.emit()
        # Do not run a search here — the Browse tab triggers its own
        # query when the user picks a folder (browseFolder).

    @Slot(result=str)
    def leaveBrowseTab(self) -> str:
        """Restore the Search-tab filter snapshot captured by enterBrowseTab.

        Clears the Browse-side folder filter, restores the saved search
        state and re-runs the search. Returns the previously-saved query
        text so the QML searchField can be repopulated. Returns an empty
        string if no snapshot was held.
        """
        snapshot = self._search_state_snapshot
        self._search_state_snapshot = None
        # Discard any in-flight forward Browse-jump target — it belongs to
        # the Browse session we are now leaving.
        self._pending_browse_jump_id = 0
        # Always drop the Browse-tab folder filter when returning.
        if self._folder_filter:
            self._folder_filter = ""
            self.folderFilterChanged.emit()
        if snapshot is None:
            self._query_text = ""
            self._run_search()
            return ""
        restore_ai_search_mode = bool(snapshot.get("was_ai_search_mode", False))
        if self._is_ai_search_mode != restore_ai_search_mode:
            self._is_ai_search_mode = restore_ai_search_mode
            self.isAiSearchModeChanged.emit()
        self._query_text = snapshot["query_text"]
        image_id = snapshot.get("current_image_id", 0)
        restored_search_folders = snapshot["search_folder_filters"]
        if restored_search_folders != self._search_folder_filters:
            self._search_folder_filters = restored_search_folders
            self.searchFolderFiltersChanged.emit()
        if snapshot["ext_filter"] != self._ext_filter:
            self._ext_filter = snapshot["ext_filter"]
            self.extFilterChanged.emit()
        if (
            snapshot["date_from"] != self._date_from
            or snapshot["date_to"] != self._date_to
        ):
            self._date_from = snapshot["date_from"]
            self._date_to = snapshot["date_to"]
            self.dateFilterChanged.emit()
        if snapshot.get("checked_only_filter", False) != self._checked_only_filter_active:
            self._checked_only_filter_active = snapshot.get("checked_only_filter", False)
            self.checkedOnlyFilterChanged.emit()
        if self._is_ai_search_mode and snapshot.get("ai_rows") is not None:
            # Restore AI results directly — no re-search, no model reload.
            saved_rows = snapshot["ai_rows"]
            self._ai_result_cache = saved_rows
            self._loaded_offset = 0
            self._loading = True
            self._search_model.set_rows(saved_rows[:_PAGE_SIZE])
            self._recompute_checked_in_results()
            self.checkedCountChanged.emit()
            self._total_results = snapshot["ai_total_results"]
            self._loaded_results = min(len(saved_rows), _PAGE_SIZE)
            if image_id and self._loaded_results > 0:
                if self.selectResultById(image_id) < 0:
                    self._select_source_row(0)
            elif self._loaded_results > 0:
                self._select_source_row(
                    self._current_result_row
                    if 0 <= self._current_result_row < self._loaded_results
                    else 0
                )
            self.totalResultsChanged.emit()
            self.loadedResultsChanged.emit()
            self._loading = False
            self._load_year_counts()
        else:
            if image_id:
                self._pending_restore_image_id = image_id
            self._run_search()
        return self._query_text

    @Slot(float, float)
    def setDateFilter(self, date_from: float, date_to: float) -> None:
        """Set captured_at filter bounds (Unix timestamps, -1 = unset)."""
        new_from = int(date_from) if date_from != -1 else None
        new_to = int(date_to) if date_to != -1 else None
        if new_from == self._date_from and new_to == self._date_to:
            return
        self._date_from = new_from
        self._date_to = new_to
        self._current_result_row = 0
        self.dateFilterChanged.emit()
        if self._rerun_ai_search_for_filter_change():
            return
        self._run_search()

    @Slot()
    def clearDateFilter(self) -> None:
        if self._date_from is None and self._date_to is None:
            return
        self._date_from = None
        self._date_to = None
        self._current_result_row = 0
        self.dateFilterChanged.emit()
        if self._rerun_ai_search_for_filter_change():
            return
        self._run_search()

    def _set_search_busy_ui(self, active: bool) -> None:
        if self._is_searching == active:
            return
        self._is_searching = active
        if active:
            QGuiApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        else:
            QGuiApplication.restoreOverrideCursor()
        self.isSearchingChanged.emit()

    def _run_search(self, show_busy_ui: bool = True, offset: int = 0) -> None:
        if self._repo is None or self._db_path is None:
            return
        path_filter = self._current_path_filter()
        params = dict(
            query=self._query_text,
            page_size=_PAGE_SIZE,
            offset=offset,
            sort_by=self._sort_by,
            ext_filter=self._ext_filter,
            path_filter=path_filter,
            restrict_to_enabled_folders=(self._folder_repo is not None),
            marked_only=self._checked_only_filter_active,
            date_from=self._date_from,
            date_to=self._date_to,
        )
        if self._search_worker is not None:
            # A search is already running.  Record the latest params so
            # _on_search_finished fires another search immediately after
            # the current one closes its connection.  This keeps at most
            # one SearchWorker (and one extra DB connection) alive at a time.
            self._pending_search_params = params
            self._pending_search_show_busy_ui = show_busy_ui
            self._search_serial += 1  # serial bump marks in-flight result stale
            return

        self._search_serial += 1
        serial = self._search_serial

        worker = SearchWorker(
            self._db_path,
            self._key,
            serial=serial,
            **params,
        )
        worker.results_ready.connect(self._on_search_finished)
        worker.failed.connect(self._on_search_failed)
        worker.finished.connect(self._on_search_worker_done)
        self._search_worker = worker
        self._search_shows_busy_ui = show_busy_ui
        self._set_search_busy_ui(show_busy_ui)
        worker.start()

    def _on_search_worker_done(self) -> None:
        """Slot connected to QThread.finished (emitted after run() fully exits).

        Releases the Python reference to the old worker only after Qt has
        confirmed the thread has fully unwound — preventing the GC from
        destroying the QThread wrapper while its C++ run() is still live.
        """
        worker = self.sender()
        self._finishing_search_workers.discard(worker)  # type: ignore[arg-type]

    def _on_search_finished(
        self,
        rows: list,
        total: int,
        format_counts: list,
        serial: int,
    ) -> None:
        if self.sender() is self._ai_search_worker:
            self._ai_search_worker = None
        old_worker = self._search_worker
        self._search_worker = None
        # Keep a Python reference to the outgoing worker until QThread.finished
        # fires (_on_search_worker_done).  Without this, the GC can destroy the
        # Python wrapper while QThreadWrapper::run() is still unwinding its
        # C++ stack, causing Qt to call abort().
        if old_worker is not None:
            self._finishing_search_workers.add(old_worker)
        # If newer params are waiting, fire a follow-up search and discard
        # these (now stale) results — only the latest request matters.
        if self._pending_search_params is not None:
            pending = self._pending_search_params
            self._pending_search_params = None
            pending_show_busy_ui = self._pending_search_show_busy_ui
            serial_now = self._search_serial
            worker = SearchWorker(
                self._db_path,
                self._key,
                serial=serial_now,
                **pending,
            )
            worker.results_ready.connect(self._on_search_finished)
            worker.failed.connect(self._on_search_failed)
            worker.finished.connect(self._on_search_worker_done)
            self._search_worker = worker
            self._search_shows_busy_ui = pending_show_busy_ui
            self._set_search_busy_ui(pending_show_busy_ui)
            worker.start()
            return
        # Discard results that belong to a superseded search.
        if serial != self._search_serial:
            self._search_shows_busy_ui = False
            self._set_search_busy_ui(False)
            return
        self._set_search_error("")
        search_offset = 0
        sender = self.sender()
        if isinstance(sender, SearchWorker):
            search_offset = sender._offset  # type: ignore[attr-defined]
        all_results = [
            SearchResult(image_id=r[0], path=r[1], filename=r[2], metadata_json=r[3], size=r[4], mtime=r[5])
            for r in rows
        ]
        # For AI searches, store all results in-memory and load only the first
        # page into the model; further pages are served from _ai_result_cache
        # by loadMore() without touching the database.
        if self._is_ai_search_mode:
            self._ai_result_cache = all_results
            first_page = all_results[:_PAGE_SIZE]
            self._loaded_offset = 0
        else:
            self._ai_result_cache = []
            first_page = all_results
            self._loaded_offset = search_offset
        # Block loadMore for the duration of the model reset.  Without this
        # guard, endResetModel() causes the Browse ListView to fire loadMore
        # (stale _loaded_results < _total_results), which emits
        # loadedResultsChanged prematurely and consumes _pendingBrowseTarget
        # before the real emission at the end of this method.
        self._loading = True
        self._search_model.set_rows(first_page)
        self._recompute_checked_in_results()
        self.checkedCountChanged.emit()
        self._total_results = total
        self._loaded_results = len(first_page)
        # Returning from Browse: synchronously load enough additional pages
        # so the previously-selected image is reachable in the model before
        # the QML scroll-restore handler runs.  Uses the DB image id so a
        # concurrent indexer run that changes row counts doesn't land on the
        # wrong image.
        if self._pending_restore_image_id and self._repo is not None:
            target_id = self._pending_restore_image_id
            while (
                self._search_model.find_row_by_id(target_id) < 0
                and self._loaded_results < self._total_results
            ):
                more_rows = self._repo.search_images(
                    self._query_text,
                    _PAGE_SIZE,
                    self._loaded_results,
                    sort_by=self._sort_by,
                    ext_filter=self._ext_filter,
                    path_filter=self._current_path_filter(),
                    restrict_to_enabled_folders=(self._folder_repo is not None),
                    marked_only=self._checked_only_filter_active,
                    date_from=self._date_from,
                    date_to=self._date_to,
                )
                if not more_rows:
                    break
                more_results = [
                    SearchResult(
                        image_id=r[0], path=r[1], filename=r[2], metadata_json=r[3],
                        size=r[4], mtime=r[5],
                    )
                    for r in more_rows
                ]
                self._search_model.append_rows(more_results)
                self._loaded_results += len(more_results)
        # Restore: select the target image BEFORE emitting loadedResultsChanged
        # so that QML's onLoadedResultsChanged reads the correct
        # currentProxyResultRow when it schedules the positionViewAtIndex call.
        # If selection happens after the emit, QML captures a stale row from
        # the previous search and scrolls to the wrong image.
        _did_restore = False
        if self._loaded_results > 0 and self._pending_restore_image_id:
            restore_id = self._pending_restore_image_id
            self._pending_restore_image_id = 0
            if self.selectResultById(restore_id) < 0:
                # Image was deleted from the index while browsing; fall back.
                self._select_source_row(0)
            _did_restore = True
        # Fresh AI search: always land on row 0 (FAISS best match).
        if self._ai_select_first:
            self._ai_select_first = False
            if self._loaded_results > 0 and not _did_restore:
                self._select_source_row(0)
                _did_restore = True
        # Keep _loading=True through both emits so loadMore cannot fire
        # prematurely during totalResultsChanged or loadedResultsChanged and
        # consume _pendingBrowseTarget before onLoadedResultsChanged handles it.
        pending_browse_jump_id = self._pending_browse_jump_id
        had_pending_browse_jump = pending_browse_jump_id != 0
        if (
            had_pending_browse_jump
            and self._search_model.find_row_by_id(pending_browse_jump_id) < 0
        ):
            self._clear_details()
        self.totalResultsChanged.emit()
        self.loadedResultsChanged.emit()
        self._loading = False
        if self._is_ai_search_mode and self._repo is not None:
            ai_paths = self._ai_format_facet_source_paths()
            format_counts = self._repo.get_format_counts_by_paths(ai_paths)
        self._apply_format_counts(format_counts)
        self._load_year_counts()
        if self._loaded_results > 0:
            if not _did_restore and not had_pending_browse_jump:
                row = (
                    self._current_result_row
                    if 0 <= self._current_result_row < self._loaded_results
                    else 0
                )
                self._select_source_row(row)
        else:
            self._clear_details()
        self._search_shows_busy_ui = False
        self._set_search_busy_ui(False)

    def _on_search_failed(self, error: str) -> None:
        if self.sender() is self._ai_search_worker:
            self._ai_search_worker = None
        old_worker = self._search_worker
        self._search_worker = None
        if old_worker is not None:
            self._finishing_search_workers.add(old_worker)
        _log.error("Search failed: %s", error)
        self._set_search_error(error)
        self._search_model.set_rows([])
        self._total_results = 0
        self._loaded_results = 0
        self._loaded_offset = 0
        self._loading = False
        self._recompute_checked_in_results()
        self.checkedCountChanged.emit()
        self.totalResultsChanged.emit()
        self.loadedResultsChanged.emit()
        self._clear_details()
        self._search_shows_busy_ui = False
        self._set_search_busy_ui(False)

    def _apply_format_counts(self, counts: list) -> None:
        """Update the available-formats property from a pre-fetched counts list."""
        items = [{"ext": ext, "count": cnt} for ext, cnt in counts]
        if self._ext_filter and not any(it["ext"] == self._ext_filter for it in items):
            items.append({"ext": self._ext_filter, "count": 0})
        self._available_formats = json.dumps(items)
        self.availableFormatsChanged.emit()

    def _ai_facet_source_paths(self) -> list[str]:
        """Return source paths used for AI mode facet/timeline counts.

        Empty AI text query keeps facets broad (folder-scope only), while a
        non-empty query follows the semantic result set.
        """
        if self._repo is None:
            return []
        if self._last_ai_query.strip():
            return [res.path for res in self._ai_result_cache]
        return sorted(
            self._repo.get_filtered_paths(
                path_filter=self._current_path_filter(),
                restrict_to_enabled_folders=(self._folder_repo is not None),
            )
        )

    def _ai_format_facet_source_paths(self) -> list[str]:
        """Return source paths used for AI format chips.

        In empty AI text mode, timeline/date selection scopes formats, but
        ext-chip selection itself does not (facet behavior).
        """
        if self._repo is None:
            return []
        if self._last_ai_query.strip():
            return [res.path for res in self._ai_result_cache]
        return sorted(
            self._repo.get_filtered_paths(
                path_filter=self._current_path_filter(),
                restrict_to_enabled_folders=(self._folder_repo is not None),
                date_from=self._date_from,
                date_to=self._date_to,
            )
        )

    def _load_year_counts(self) -> None:
        if self._repo is None:
            return
        if self._is_ai_search_mode:
            ai_paths = self._ai_facet_source_paths()
            counts = self._repo.get_year_counts_by_paths(ai_paths)
        else:
            counts = self._repo.get_year_counts(
                query=self._query_text,
                ext_filter=self._ext_filter,
                path_filter=self._current_path_filter(),
                restrict_to_enabled_folders=(self._folder_repo is not None),
            )
        self._year_counts = json.dumps([{"year": y, "count": c} for y, c in counts])
        self.yearCountsChanged.emit()

    def _load_formats(
        self,
        query: str = "",
        path_filter: list[str] | None = None,
        restrict_to_enabled_folders: bool = False,
    ) -> None:
        if self._repo is None:
            return
        import json as _json
        counts = self._repo.get_format_counts(
            query=query,
            path_filter=path_filter,
            restrict_to_enabled_folders=restrict_to_enabled_folders,
        )
        self._apply_format_counts(counts)

    def _invalidate_folder_tree(self) -> None:
        """Mark the folder tree as stale; it will be rebuilt on next Browse tab visit."""
        self._folder_tree_dirty = True

    def _start_folder_tree_worker(self, show_busy_ui: bool) -> None:
        if self._repo is None or self._folder_tree_worker is not None:
            return
        self._folder_tree_worker_shows_busy_ui = show_busy_ui
        if show_busy_ui:
            self._is_searching = True
            self.isSearchingChanged.emit()
        self._folder_tree_worker = FolderTreeWorker(self._db_path, self._key)
        self._folder_tree_worker.results_ready.connect(self._on_folder_tree_ready)
        self._folder_tree_worker.failed.connect(self._on_folder_tree_failed)
        # Clear the Python reference only after run() has fully returned.
        # Qt emits finished() after QThreadWrapper::run() exits, so by the time
        # this slot fires the C++ thread infrastructure is fully unwound and it
        # is safe to drop the last Python reference.  Setting self._folder_tree_worker
        # to None inside a results_ready/failed handler races with run() still
        # being on the C++ call stack, which causes Qt to call qFatal().
        self._folder_tree_worker.finished.connect(self._on_folder_tree_finished)
        self._folder_tree_worker.start()

    @Slot()
    def loadFolderTree(self) -> None:
        """Load the folder tree in the background when Browse becomes visible."""
        if self._repo is None or not self._folder_tree_dirty:
            return
        self._start_folder_tree_worker(show_busy_ui=False)

    def _load_folder_tree(self) -> None:
        if self._repo is None:
            return
        nodes = self._repo.get_folder_tree()
        self._folder_tree = json.dumps(nodes)
        self.folderTreeChanged.emit()

    @Slot()
    def reloadFolderTree(self) -> None:
        """Force-rebuild the folder tree off the GUI thread.

        Uses the search overlay to dim the UI while the query runs, so
        the grey-out is actually visible (the worker thread keeps the
        event loop free for rendering).
        """
        if self._repo is None or self._folder_tree_worker is not None:
            return
        self._start_folder_tree_worker(show_busy_ui=True)

    def _on_folder_tree_finished(self) -> None:
        """Release the worker reference after the thread has fully exited."""
        self._folder_tree_worker = None

    def _on_folder_tree_ready(self, json_str: str) -> None:
        self._folder_tree = json_str
        self._folder_tree_dirty = False
        if self._folder_tree_worker_shows_busy_ui:
            self._is_searching = False
            self.isSearchingChanged.emit()
            self._set_status(_("Folder list reloaded."))
        self._folder_tree_worker_shows_busy_ui = False
        self.folderTreeChanged.emit()

    def _on_folder_tree_failed(self, error: str) -> None:
        if self._folder_tree_worker_shows_busy_ui:
            self._is_searching = False
            self.isSearchingChanged.emit()
        self._folder_tree_worker_shows_busy_ui = False
        _log.error("Folder tree reload failed: %s", error)

    @Slot(result=bool)
    def loadMore(self) -> bool:
        if self._loading:
            return False
        if self._is_ai_search_mode:
            if self._loaded_results >= self._total_results:
                return False
            next_page = self._ai_result_cache[
                self._loaded_results : self._loaded_results + _PAGE_SIZE
            ]
            if not next_page:
                return False
            self._loading = True
            self._search_model.append_rows(next_page)
            self._loaded_results += len(next_page)
            self.loadedResultsChanged.emit()
            self._loading = False
            return True
        if self._loaded_offset + self._loaded_results >= self._total_results:
            return False
        if self._db_path is None:
            return False
        page_size = _PAGE_SIZE
        if self._pending_browse_jump_id:
            page_size = _BROWSE_JUMP_PAGE_SIZE
        self._loading = True
        self._page_load_direction = "append"
        worker = SearchPageWorker(
            self._db_path,
            self._key,
            query=self._query_text,
            page_size=page_size,
            offset=self._loaded_offset + self._loaded_results,
            sort_by=self._sort_by,
            ext_filter=self._ext_filter,
            path_filter=self._current_path_filter(),
            restrict_to_enabled_folders=(self._folder_repo is not None),
            marked_only=self._checked_only_filter_active,
            serial=self._search_serial,
            date_from=self._date_from,
            date_to=self._date_to,
        )
        worker.results_ready.connect(self._on_load_more_finished)
        worker.failed.connect(self._on_load_more_failed)
        worker.finished.connect(lambda: self._finishing_search_workers.discard(worker))
        self._load_more_worker = worker
        self._finishing_search_workers.add(worker)
        worker.start()
        return True

    @Slot(result=bool)
    def loadPrevious(self) -> bool:
        if self._loading or self._is_ai_search_mode:
            return False
        if self._loaded_offset <= 0 or self._db_path is None:
            return False
        page_size = min(_PAGE_SIZE, self._loaded_offset)
        if page_size <= 0:
            return False
        self._loading = True
        self._page_load_direction = "prepend"
        worker = SearchPageWorker(
            self._db_path,
            self._key,
            query=self._query_text,
            page_size=page_size,
            offset=self._loaded_offset - page_size,
            sort_by=self._sort_by,
            ext_filter=self._ext_filter,
            path_filter=self._current_path_filter(),
            restrict_to_enabled_folders=(self._folder_repo is not None),
            marked_only=self._checked_only_filter_active,
            serial=self._search_serial,
            date_from=self._date_from,
            date_to=self._date_to,
        )
        worker.results_ready.connect(self._on_load_more_finished)
        worker.failed.connect(self._on_load_more_failed)
        worker.finished.connect(lambda: self._finishing_search_workers.discard(worker))
        self._load_more_worker = worker
        self._finishing_search_workers.add(worker)
        worker.start()
        return True

    def _on_load_more_finished(self, rows: list, serial: int) -> None:
        self._load_more_worker = None
        if serial != self._search_serial:
            self._loading = False
            return
        results = [
            SearchResult(
                image_id=r[0], path=r[1], filename=r[2], metadata_json=r[3],
                size=r[4], mtime=r[5],
            )
            for r in rows
        ]
        if self._page_load_direction == "prepend":
            inserted = len(results)
            self._search_model.prepend_rows(results)
            self._loaded_offset = max(0, self._loaded_offset - inserted)
            self._loaded_results += inserted
            if self._current_result_row >= 0:
                self._current_result_row += inserted
                self.currentResultRowChanged.emit()
                self.currentProxyResultRowChanged.emit()
        else:
            self._search_model.append_rows(results)
            self._loaded_results += len(results)
        self.loadedResultsChanged.emit()
        self._loading = False

    def _on_load_more_failed(self, error: str) -> None:
        self._load_more_worker = None
        _log.error("Load-more failed: %s", error)
        self._loading = False

    @Slot(int)
    def selectResult(self, proxy_row: int) -> None:
        # Map proxy row → source row when the checked-only filter is active.
        row = self._filter_proxy.source_row_for(proxy_row) if self._filter_proxy else proxy_row
        self._select_source_row(row)

    @Slot(int, result=int)
    def selectResultById(self, image_id: int) -> int:
        """Find the image with *image_id* in the current results, select it,
        and return its proxy row (or -1 if not found).

        Used by QML to scroll Browse tab to a specific image after
        navigating from a Search result card.
        """
        n = self._search_model.rowCount()
        for source_row in range(n):
            if self._search_model.get_image_id(source_row) == image_id:
                self._select_source_row(source_row)
                if self._pending_browse_jump_id == image_id:
                    self._pending_browse_jump_id = 0
                pr = (
                    self._filter_proxy.proxy_row_for(source_row)
                    if self._filter_proxy
                    else source_row
                )
                return pr
        return -1

    @Slot(str, result=int)
    def selectResultByPath(self, path: str) -> int:
        """Find the image at *path* in the current results, select it, and
        return its proxy row (or -1 if not found).
        """
        n = self._search_model.rowCount()
        for source_row in range(n):
            if self._search_model.get_path(source_row) == path:
                self._select_source_row(source_row)
                pr = (
                    self._filter_proxy.proxy_row_for(source_row)
                    if self._filter_proxy
                    else source_row
                )
                return pr
        return -1

    def _select_source_row(self, row: int) -> None:
        """Select a result by its source-model row (no proxy mapping)."""
        # A new selection supersedes any in-flight preview.  Resume workers
        # immediately so card thumbnails can render during the debounce window.
        self._preview_resume_timer.stop()
        self._resume_thumb_for_preview()
        meta_json = self._search_model.get_metadata_json(row)
        path = self._search_model.get_path(row)
        if not meta_json:
            self._clear_details()
            return
        try:
            parsed = json.loads(meta_json)
            plain_text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            plain_text = meta_json
        self._details_plain_text = plain_text
        self._find_text = ""
        self._find_positions = []
        self._find_index = -1
        self._update_details_html()
        self._update_exif_table(meta_json)
        self._current_result_row = row
        self.currentResultRowChanged.emit()
        self.currentProxyResultRowChanged.emit()
        # Show thumb placeholder immediately from local cache (instant, no disk I/O)
        thumb_uri = self._search_model.data(
            self._search_model.index(row, 0),
            SearchListModel.ThumbnailSourceRole,
        )
        self._selected_thumb_source = thumb_uri or ""
        self.selectedThumbSourceChanged.emit()
        # Debounce the full preview load — lets visible card thumbnails in the
        # list render before the heavier preview decode starts.
        self._pending_preview_path = path or ""
        self._pending_preview_stamp = self._search_model.get_stamp(row)
        self._pending_preview_pixel_count = self._search_model.get_pixel_count(row)
        # Selecting a new image always falls back to the cached preview
        # (per-image scope for the toggle).  When no cached preview exists
        # for this image we transparently switch to the original instead;
        # the toggle is hidden in that case (see selectedHasPreview).
        has_preview = self._compute_has_preview(
            self._pending_preview_path, self._pending_preview_stamp
        )
        if has_preview != self._selected_has_preview:
            self._selected_has_preview = has_preview
            self.selectedHasPreviewChanged.emit()
        desired_raw = not has_preview
        if self._use_raw_preview != desired_raw:
            self._use_raw_preview = desired_raw
            self.useRawPreviewChanged.emit()
        self._preview_delay_timer.start()  # resets if already running

    @Slot(str)
    def findNext(self, find_text: str) -> None:
        if find_text != self._find_text:
            self._find_text = find_text
            self._find_positions = self._find_all(self._details_plain_text, find_text)
            self._find_index = -1
        if not self._find_positions:
            return
        self._find_index = (self._find_index + 1) % len(self._find_positions)
        self._update_details_html()
        self._update_find_scroll()

    @Slot(str)
    def findPrev(self, find_text: str) -> None:
        if find_text != self._find_text:
            self._find_text = find_text
            self._find_positions = self._find_all(self._details_plain_text, find_text)
            self._find_index = len(self._find_positions)
        if not self._find_positions:
            return
        self._find_index = (self._find_index - 1) % len(self._find_positions)
        self._update_details_html()
        self._update_find_scroll()

    # ── Indexed-folder management slots ──────────────────────────────────

    @Slot(str)
    def addIndexedFolder(self, folder_url: str) -> None:
        if self._repo is None or self._folder_repo is None:
            return
        folder = Path(QUrl(folder_url).toLocalFile())
        if not folder.is_dir():
            return
        path_str = str(folder)
        if self._folder_repo.exists(path_str):
            self._set_status(_("Folder already tracked: {}").format(folder.name))
            return
        folder_obj = self._folder_repo.add(path_str)
        self._folder_model.add_folder(folder_obj)
        self.indexedFoldersChanged.emit()
        self._start_managed_folder_indexing(folder_obj, force=False)

    @Slot(int)
    def removeIndexedFolder(self, folder_id: int) -> None:
        if self._repo is None or self._folder_repo is None:
            return
        folder = self._folder_repo.get_by_id(folder_id)
        if folder is None:
            return
        # Remove from pending queue before deleting
        self._scan_queue = [(fid, f) for fid, f in self._scan_queue if fid != folder_id]
        if self._scanning_folder_id == folder_id and self._index_worker:
            self._index_worker.cancel()
        # Drop any preview-cache files belonging to this folder before its
        # rows leave the database, otherwise we lose the stamps needed to
        # locate the cached files.
        try:
            stamps = self._repo.get_folder_stamps(folder_id)
            clear_cached_previews_for(
                self._search_model.cache_dir,
                stamps,
                encrypted=bool(self._key),
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("Failed to clean preview cache on folder removal: %s", exc)
        self._folder_repo.remove(folder_id)
        self._folder_model.remove_folder(folder_id)
        self._repo.delete_folder_associations(folder_id)
        self._repo.delete_orphans_under_prefix(folder.path)
        # Drop the removed folder from the active search-filter selection
        # so the search reverts to "all folders" instead of filtering on a
        # path that no longer exists.
        if folder.path in self._search_folder_filters:
            self._search_folder_filters.discard(folder.path)
            self.searchFolderFiltersChanged.emit()
        if self._folder_filter == folder.path:
            self._folder_filter = ""
            self.folderFilterChanged.emit()
        self.indexedFoldersChanged.emit()
        self._invalidate_folder_tree()
        self._load_formats()
        self._run_search()

    @Slot(int, bool)
    def setFolderEnabled(self, folder_id: int, enabled: bool) -> None:
        if self._folder_repo is None:
            return
        if not enabled:
            # Remove from scan queue when disabling
            self._scan_queue = [(fid, f) for fid, f in self._scan_queue if fid != folder_id]
            if self._scanning_folder_id == folder_id and self._index_worker:
                self._index_worker.cancel()
        self._folder_repo.set_enabled(folder_id, enabled)
        updated = self._folder_repo.get_by_id(folder_id)
        if updated:
            self._folder_model.update_folder(updated)
        # If the folder being disabled is the current search/browse filter,
        # drop the filter so the search reverts to "all enabled folders"
        # instead of producing 0 results for an excluded path.
        if not enabled and updated is not None:
            if updated.path in self._search_folder_filters:
                self._search_folder_filters.discard(updated.path)
                self.searchFolderFiltersChanged.emit()
            if self._folder_filter == updated.path:
                self._folder_filter = ""
                self.folderFilterChanged.emit()
        self.indexedFoldersChanged.emit()
        self._run_search()

    @Slot(int)
    def rescanFolder(self, folder_id: int) -> None:
        if self._folder_repo is None:
            return
        folder = self._folder_repo.get_by_id(folder_id)
        if folder is None:
            return
        self._start_managed_folder_indexing(folder, force=False)

    @Slot(int)
    def fullRescanFolder(self, folder_id: int) -> None:
        if self._folder_repo is None:
            return
        folder = self._folder_repo.get_by_id(folder_id)
        if folder is None:
            return
        self._start_managed_folder_indexing(folder, force=True)

    @Slot()
    def rescanAllFolders(self) -> None:
        if self._folder_repo is None:
            return
        folders = self._folder_repo.get_enabled_folders()
        for folder in folders:
            self._start_managed_folder_indexing(folder, force=False)

    @Slot()
    def fullRescanAllFolders(self) -> None:
        if self._folder_repo is None:
            return
        folders = self._folder_repo.get_enabled_folders()
        for folder in folders:
            self._start_managed_folder_indexing(folder, force=True)

    def _load_indexed_folders(self) -> None:
        if self._folder_repo is None:
            return
        folders = self._folder_repo.get_all()
        self._folder_model.set_rows(folders)
        self._refresh_all_preview_counts()
        self.indexedFoldersChanged.emit()

    def _refresh_all_preview_counts(self) -> None:
        """Recount cached previews for every folder currently in the model."""
        if self._repo is None:
            return
        cache_dir = self._search_model.cache_dir
        encrypted = bool(self._key)
        try:
            existing = list_existing_previews(cache_dir, encrypted=encrypted)
        except Exception:  # noqa: BLE001
            existing = set()
        for f in list(self._folder_model._rows):
            try:
                stamps = self._repo.get_folder_stamps(f.id)
            except Exception:  # noqa: BLE001
                stamps = {}
            cached = count_cached_previews(
                cache_dir, stamps, encrypted=encrypted, existing=existing
            )
            self._folder_model.set_preview_count(f.id, cached, len(stamps))

    def _refresh_preview_count(self, folder_id: int) -> None:
        """Recount cached previews for a single folder."""
        if self._repo is None or folder_id <= 0:
            return
        cache_dir = self._search_model.cache_dir
        encrypted = bool(self._key)
        try:
            stamps = self._repo.get_folder_stamps(folder_id)
        except Exception:  # noqa: BLE001
            stamps = {}
        cached = count_cached_previews(cache_dir, stamps, encrypted=encrypted)
        self._folder_model.set_preview_count(folder_id, cached, len(stamps))

    def _start_managed_folder_indexing(self, folder_obj, *, force: bool = False) -> None:
        """Enqueue a folder for indexing and start the queue if idle."""
        if self._repo is None or self._folder_repo is None:
            return
        entry = (folder_obj.id, force)
        if entry not in self._scan_queue:
            self._scan_queue.append(entry)
            self._index_queue_total += 1
            self.indexQueueTotalChanged.emit()
            # Mark as queued in DB/model unless it is already being scanned
            if folder_obj.status not in ("scanning",):
                self._folder_repo.update_status(folder_obj.id, "queued")
                updated = self._folder_repo.get_by_id(folder_obj.id)
                if updated:
                    self._folder_model.update_folder(updated)
        self._process_next_in_queue()

    def _process_next_in_queue(self) -> None:
        """Start the next folder in the scan queue if not already indexing."""
        if self._is_indexing or not self._scan_queue:
            return
        folder_id, force = self._scan_queue.pop(0)
        self._index_queue_position += 1
        self.indexQueuePositionChanged.emit()
        folder_obj = self._folder_repo.get_by_id(folder_id) if self._folder_repo else None
        if folder_obj is None:
            # Folder was removed while queued — skip and try the next one
            self._process_next_in_queue()
            return
        self._actually_start_indexing(folder_obj, force=force)

    def _actually_start_indexing(self, folder_obj, *, force: bool) -> None:
        """Immediately start an IndexWorker for the given folder."""
        if self._repo is None:
            return
        if self._exiftool_missing:
            # Surface the warning again in case the user dismissed the dialog
            # and then tried to start a scan from the folder actions.
            self.exiftoolMissingChanged.emit()
            return
        # Bail out early if the folder is not reachable (network drive detached).
        if not Path(folder_obj.path).exists():
            if self._folder_repo:
                self._folder_repo.update_status(
                    folder_obj.id, "error",
                    error_message=_("Folder not accessible"),
                )
                updated = self._folder_repo.get_by_id(folder_obj.id)
                if updated:
                    self._folder_model.update_folder(updated)
            self._set_status(
                _("Folder not accessible: {}").format(folder_obj.display_name)
            )
            self._process_next_in_queue()
            return
        # Cancel any thumb worker that is still running (e.g. the one started at
        # unlock time).  A definitive build will be triggered after indexing
        # finishes, so there is no value in letting the two workers race.
        if self._thumb_worker and self._thumb_worker.isRunning():
            # Disconnect all callbacks BEFORE cancelling.  The 'canceled' signal
            # is emitted asynchronously on the worker thread; without this it can
            # arrive after the post-index Worker B has already started, causing
            # _on_thumb_canceled to stop Worker B's refresh timer and flip
            # _is_building_thumbs to False while B is still running.
            try:
                self._thumb_worker.progress.disconnect(self._on_thumb_progress)
                self._thumb_worker.finished.disconnect(self._on_thumb_done)
                self._thumb_worker.failed.disconnect(self._on_thumb_failed)
                self._thumb_worker.canceled.disconnect(self._on_thumb_canceled)
            except RuntimeError:
                pass  # already disconnected
            self._thumb_refresh_timer.stop()
            self._thumb_worker.cancel()
            self._is_building_thumbs = False
            self._pending_thumb_restart = False
            self.isBuildingThumbsChanged.emit()
        self._scanning_folder_id = folder_obj.id
        if self._folder_repo:
            self._folder_repo.update_status(folder_obj.id, "scanning")
            updated = self._folder_repo.get_by_id(folder_obj.id)
            if updated:
                self._folder_model.update_folder(updated)
        self._is_indexing = True
        self._index_current = 0
        self._index_total = 0
        self._index_current_file = ""
        self.isIndexingChanged.emit()
        self.indexCurrentChanged.emit()
        self.indexTotalChanged.emit()
        self.indexCurrentFileChanged.emit()
        self._set_status(_("Indexing {}\u2026").format(folder_obj.display_name))
        self._index_worker = IndexWorker(
            self._db_path,
            [Path(folder_obj.path)],
            workers=self._settings.workerCount if self._settings else _DEFAULT_WORKERS,
            key=self._key,
            force=force,
            blacklist=self._settings.blacklist_patterns if self._settings else [],
            folder_id=folder_obj.id,
        )
        self._index_worker.finished.connect(self._on_managed_folder_index_done)
        self._index_worker.failed.connect(self._on_managed_folder_index_failed)
        self._index_worker.progress.connect(self._on_index_progress)
        self._index_worker.canceled.connect(self._on_managed_folder_index_canceled)
        # Run below normal priority so the GUI and preview thread get preference.
        self._index_worker.start(QThread.Priority.LowPriority)
        # Arm the thumb timer immediately so ThumbWorker starts ~5 s into indexing
        # and already-indexed images get thumbnails without waiting for the full
        # scan to complete. ThumbWorker is capped at _MAX_THUMB_WORKERS threads
        # to limit GIL pressure during the scan phase on Windows.
        self._thumb_batch_timer.start()

    def _on_managed_folder_index_done(self, count: int, error_count: int = 0) -> None:
        self._thumb_batch_timer.stop()
        self._is_indexing = False
        self.isIndexingChanged.emit()
        if self._folder_repo and self._scanning_folder_id is not None:
            self._folder_repo.update_status(
                self._scanning_folder_id, "indexed", image_count=count
            )
            updated = self._folder_repo.get_by_id(self._scanning_folder_id)
            if updated:
                self._folder_model.update_folder(updated)
        self._scanning_folder_id = None
        if error_count:
            self._set_status(
                _("Indexed {count} images ({errors} skipped due to errors)").format(
                    count=count, errors=error_count
                )
            )
        else:
            self._set_status(_("Indexed {} images").format(count))
        self._load_formats()
        self._invalidate_folder_tree()
        self.search(self._query_text)
        if self._scan_queue:
            # More folders waiting — keep going before building thumbs
            self._process_next_in_queue()
        else:
            # Entire queue drained — reset counters and build thumbnails
            self._index_queue_position = 0
            self._index_queue_total = 0
            self.indexQueuePositionChanged.emit()
            self.indexQueueTotalChanged.emit()
            if self._is_building_thumbs:
                # A thumb worker started by the 8-second timer is still running
                # with a stale DB snapshot.  Flag it to restart when it finishes
                # so it picks up any images added since it began.
                self._pending_thumb_restart = True
            else:
                self._start_auto_thumbs()

    def _on_managed_folder_index_failed(self, error: str) -> None:
        self._thumb_batch_timer.stop()
        self._is_indexing = False
        self.isIndexingChanged.emit()
        if self._folder_repo and self._scanning_folder_id is not None:
            self._folder_repo.update_status(
                self._scanning_folder_id, "error", error_message=error
            )
            updated = self._folder_repo.get_by_id(self._scanning_folder_id)
            if updated:
                self._folder_model.update_folder(updated)
        self._scanning_folder_id = None
        self._set_status(_("Index failed: {}").format(error))
        if self._scan_queue:
            self._process_next_in_queue()
        else:
            self._index_queue_position = 0
            self._index_queue_total = 0
            self.indexQueuePositionChanged.emit()
            self.indexQueueTotalChanged.emit()


    def _on_managed_folder_index_canceled(self, count: int) -> None:
        self._thumb_batch_timer.stop()
        self._is_indexing = False
        self.isIndexingChanged.emit()
        if not self._app_closing:
            # User-initiated cancel: reset folder to new
            if self._folder_repo and self._scanning_folder_id is not None:
                self._folder_repo.update_status(
                    self._scanning_folder_id, "new", image_count=count
                )
                updated = self._folder_repo.get_by_id(self._scanning_folder_id)
                if updated:
                    self._folder_model.update_folder(updated)
        self._scanning_folder_id = None
        # Reset queue counters (cancel stops the whole queue)
        self._index_queue_position = 0
        self._index_queue_total = 0
        self.indexQueuePositionChanged.emit()
        self.indexQueueTotalChanged.emit()
        if not self._app_closing:
            self._is_canceling = False
            self.isCancelingChanged.emit()
            self._set_status(_("Index canceled"))
            self.search(self._query_text)

    @Slot()
    def cancelIndex(self) -> None:
        try:
            # Reset all queued (not yet started) folders back to "new"
            if self._folder_repo:
                for folder_id, _force in self._scan_queue:
                    self._folder_repo.update_status(folder_id, "new")
                    updated = self._folder_repo.get_by_id(folder_id)
                    if updated:
                        self._folder_model.update_folder(updated)
            self._scan_queue.clear()
            if self._thumb_worker and self._thumb_worker.isRunning():
                self._thumb_batch_timer.stop()
                self._thumb_worker.cancel()
            if self._index_worker and self._index_worker.isRunning():
                self._is_canceling = True
                self.isCancelingChanged.emit()
                self._set_status(_("Canceling\u2026"))
                self._index_worker.cancel()
        except Exception:
            _log.exception("cancelIndex failed")
            # Reset stuck UI state so the button is usable again.
            self._is_canceling = False
            self.isCancelingChanged.emit()

    @Slot()
    def onAppClosing(self) -> None:
        """Called when the application window is about to close.

        Persists the currently-scanning folder as 'queued' so that it resumes
        on the next launch, then cancels any running workers.
        """
        self._app_closing = True
        if self._folder_repo and self._scanning_folder_id is not None:
            self._folder_repo.update_status(self._scanning_folder_id, "queued")
        if self._index_worker and self._index_worker.isRunning():
            self._index_worker.cancel()
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.cancel()
        if self._preview_worker and self._preview_worker.isRunning():
            self._preview_worker.cancel()
        self._scan_queue.clear()

    @Slot()
    def cancelThumbnails(self) -> None:
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.cancel()

    # ── Preview-cache build ───────────────────────────────────────────────

    @Slot(int)
    def buildPreviewsForFolder(self, folder_id: int) -> None:
        """Render the preview-cache for every image in *folder_id*.

        No-op while another preview build is already running — the user must
        cancel it first.  Runs independently of the thumbnail worker; both
        may be active at once.
        """
        if self._repo is None or self._is_building_previews:
            return
        cache_dir = self._search_model.cache_dir
        target = self._settings.previewMaxSize if self._settings else 2048
        workers = self._settings.workerCount if self._settings else _DEFAULT_WORKERS
        self._preview_worker = PreviewBuildWorker(
            self._db_path,
            cache_dir,
            folder_id,
            target,
            workers=workers,
            key=self._key,
        )
        self._preview_worker.progress.connect(self._on_preview_progress)
        self._preview_worker.finished.connect(self._on_preview_done)
        self._preview_worker.failed.connect(self._on_preview_failed)
        self._preview_worker.canceled.connect(self._on_preview_canceled)
        self._preview_worker.oversized.connect(self._on_preview_oversized)
        self._is_building_previews = True
        self._preview_build_folder_id = folder_id
        self._preview_current = 0
        self._preview_total = 0
        self._preview_current_file = ""
        self._preview_oversized_skipped = 0
        self.isBuildingPreviewsChanged.emit()
        self.previewBuildFolderIdChanged.emit()
        self.previewCurrentChanged.emit()
        self.previewTotalChanged.emit()
        self.previewCurrentFileChanged.emit()
        self._preview_worker.start(QThread.Priority.LowPriority)

    @Slot()
    def cancelPreviewBuild(self) -> None:
        if self._preview_worker and self._preview_worker.isRunning():
            self._preview_worker.cancel()

    # ── AI-scan ───────────────────────────────────────────────────────────────

    @Slot(int)
    def aiScanFolder(self, folder_id: int) -> None:
        """Build CLIP vectors for images in *folder_id* that are not indexed yet.

        No-op while another AI scan is already running — the user must cancel
        it first.  Progress is reported via the aiScanCurrent / aiScanTotal /
        aiScanCurrentFile properties.
        """
        self._start_ai_scan(folder_id, force_rebuild=False)

    @Slot(int)
    def aiFullRescanFolder(self, folder_id: int) -> None:
        """Rebuild the CLIP vector index for every image in *folder_id*."""
        self._start_ai_scan(folder_id, force_rebuild=True)

    def _start_ai_scan(self, folder_id: int, *, force_rebuild: bool) -> None:
        if self._folder_repo is None or self._is_ai_scanning:
            return
        folder = self._folder_repo.get_by_id(folder_id)
        if folder is None:
            return
        self._ai_scan_worker = AiScanWorker(
            self._db_path,
            folder_id,
            folder.path,
            key=self._key,
            force_rebuild=force_rebuild,
        )
        self._ai_scan_worker.progress.connect(self._on_ai_scan_progress)
        self._ai_scan_worker.finished.connect(self._on_ai_scan_finished)
        self._ai_scan_worker.failed.connect(self._on_ai_scan_failed)
        self._ai_scan_worker.canceled.connect(self._on_ai_scan_canceled)
        self._is_ai_scanning = True
        self._ai_scan_folder_id = folder_id
        self._ai_scan_is_full_rescan = force_rebuild
        self._ai_scan_current = 0
        self._ai_scan_total = 0
        self._ai_scan_current_file = ""
        self.isAiScanningChanged.emit()
        self.aiScanFolderIdChanged.emit()
        self.aiScanIsFullRescanChanged.emit()
        self.aiScanCurrentChanged.emit()
        self.aiScanTotalChanged.emit()
        self.aiScanCurrentFileChanged.emit()
        self._ai_scan_worker.start(QThread.Priority.LowPriority)

    @Slot()
    def cancelAiScan(self) -> None:
        if self._ai_scan_worker and self._ai_scan_worker.isRunning():
            self._ai_scan_worker.cancel()

    @Slot(bool)
    def setAiSearchMode(self, enabled: bool) -> None:
        if self._is_ai_search_mode == enabled:
            return
        self._is_ai_search_mode = enabled
        self.isAiSearchModeChanged.emit()

    @Slot(str, str)
    def aiSearch(self, query: str, precision: str = "normal") -> None:
        """Kick off a CLIP vector search with *query* text."""
        query = query.strip()
        if self._db_path is None:
            return
        self._last_ai_query = query
        self._last_ai_precision = precision
        self._has_ai_search_run = True
        self._ai_select_first = True
        self._start_ai_search_worker(query, precision)

    def _start_ai_search_worker(self, query: str, precision: str) -> None:
        """Internal helper: create and start an AiSearchWorker."""
        self._search_serial += 1
        serial = self._search_serial
        worker = AiSearchWorker(
            self._db_path,
            self._key,
            query,
            serial,
            precision=precision,
            path_filter=self._current_path_filter(),
            ext_filter=self._ext_filter,
            date_from=self._date_from,
            date_to=self._date_to,
        )
        worker.results_ready.connect(self._on_search_finished)
        worker.failed.connect(self._on_search_failed)
        worker.finished.connect(lambda: self._finishing_search_workers.discard(worker))
        self._ai_search_worker = worker
        self._finishing_search_workers.add(worker)
        self._search_shows_busy_ui = True
        self._set_search_busy_ui(True)
        worker.start()

    def _on_ai_scan_progress(self, done: int, total: int, path: str) -> None:
        self._ai_scan_current = done
        self._ai_scan_total = total
        self._ai_scan_current_file = path
        self.aiScanCurrentChanged.emit()
        self.aiScanTotalChanged.emit()
        self.aiScanCurrentFileChanged.emit()

    def _clear_ai_scan_state(self) -> None:
        self._is_ai_scanning = False
        self._ai_scan_folder_id = 0
        self._ai_scan_is_full_rescan = False
        self.isAiScanningChanged.emit()
        self.aiScanFolderIdChanged.emit()
        self.aiScanIsFullRescanChanged.emit()

    def _on_ai_scan_finished(self, indexed: int, errors: int) -> None:
        was_full_rescan = self._ai_scan_is_full_rescan
        self._clear_ai_scan_state()
        if was_full_rescan:
            msg = _("AI full rescan complete: {n} image(s) vectorised.").format(n=indexed)
        else:
            msg = _("AI-Scan complete: {n} image(s) vectorised.").format(n=indexed)
        if errors:
            msg += " " + _("{n} file(s) could not be processed.").format(n=errors)
        self._set_status(msg)

    def _on_ai_scan_failed(self, error: str) -> None:
        was_full_rescan = self._ai_scan_is_full_rescan
        self._clear_ai_scan_state()
        if was_full_rescan:
            self._set_status(_("AI full rescan failed: {error}").format(error=error))
        else:
            self._set_status(_("AI-Scan failed: {error}").format(error=error))

    def _on_ai_scan_canceled(self, indexed: int) -> None:
        was_full_rescan = self._ai_scan_is_full_rescan
        self._clear_ai_scan_state()
        if was_full_rescan:
            self._set_status(
                _("AI full rescan canceled ({n} image(s) vectorised so far).").format(n=indexed)
            )
        else:
            self._set_status(
                _("AI-Scan canceled ({n} image(s) vectorised so far).").format(n=indexed)
            )

    def _on_preview_progress(self, done: int, total: int, path: str) -> None:
        self._preview_current = done
        self._preview_total = total
        self._preview_current_file = path
        self.previewCurrentChanged.emit()
        self.previewTotalChanged.emit()
        self.previewCurrentFileChanged.emit()

    def _clear_preview_build_state(self) -> None:
        self._is_building_previews = False
        self._preview_build_folder_id = 0
        self.isBuildingPreviewsChanged.emit()
        self.previewBuildFolderIdChanged.emit()

    def _on_preview_oversized(self, count: int) -> None:
        self._preview_oversized_skipped = count

    def _on_preview_done(self, built: int, total: int) -> None:
        folder_id = self._preview_build_folder_id
        oversized = self._preview_oversized_skipped
        self._clear_preview_build_state()
        if folder_id > 0:
            self._refresh_preview_count(folder_id)
        msg = _("Built {built} preview(s) of {total}.").format(
            built=built, total=total
        )
        if oversized:
            msg += " " + _("{n} image(s) skipped — too large to decode safely.").format(
                n=oversized
            )
        self._set_status(msg)

    def _on_preview_failed(self, error: str) -> None:
        folder_id = self._preview_build_folder_id
        self._clear_preview_build_state()
        if folder_id > 0:
            self._refresh_preview_count(folder_id)
        self._set_status(_("Preview build failed: {error}").format(error=error))

    def _on_preview_canceled(self, built: int, total: int) -> None:
        folder_id = self._preview_build_folder_id
        self._clear_preview_build_state()
        if folder_id > 0:
            self._refresh_preview_count(folder_id)
        self._set_status(
            _("Preview build canceled ({built} of {total} done).").format(
                built=built, total=total
            )
        )

    @Slot(int)
    def clearPreviewsForFolder(self, folder_id: int) -> None:
        """Delete every cached preview belonging to *folder_id*."""
        if self._repo is None or folder_id <= 0:
            return
        if self._is_building_previews and self._preview_build_folder_id == folder_id:
            # Don't race the worker — make the user cancel first.
            self._set_status(
                _("Cancel the running preview build before clearing the cache.")
            )
            return
        cache_dir = self._search_model.cache_dir
        encrypted = bool(self._key)
        try:
            stamps = self._repo.get_folder_stamps(folder_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(
                _("Failed to clear preview cache: {error}").format(error=str(exc))
            )
            return
        removed = clear_cached_previews_for(cache_dir, stamps, encrypted=encrypted)
        self._refresh_preview_count(folder_id)
        self._set_status(
            _("Removed {n} cached preview(s).").format(n=removed)
        )

    # ── Preview source toggle ─────────────────────────────────────────────

    def _load_preview_for_clipboard(self, path: str) -> "Image.Image":
        """Return a Pillow image for *path* matching what is currently on screen.

        - "Show Original" mode (``_use_raw_preview`` is True): decode the
          source file directly so the user copies the full-resolution original.
        - Preview mode (default): read from the local preview cache when
          available, so clipboard copy works even when the source volume is
          disconnected.
        """
        from PIL import Image  # noqa: PLC0415

        if self._use_raw_preview:
            # User is viewing the full-resolution source — copy that.
            return render_preview(path, MAX_PREVIEW_PX)

        stamp = self._pending_preview_stamp
        if self._preview_provider is not None and self._preview_provider._cache_dir is not None:
            cached = self._preview_provider._try_load_cached(path, stamp)
            if cached is not None:
                return cached
        return render_preview(path, MAX_PREVIEW_PX)

    @Slot()
    def recreateThumbnail(self) -> None:
        """Delete the cached thumbnail for the selected image and rebuild it."""
        path = self._pending_preview_path
        stamp = self._pending_preview_stamp
        if not path:
            return
        cache_dir = self._search_model.cache_dir
        if stamp is not None:
            cache_name = thumb_cache_name_from_stamp(path, stamp[0], stamp[1])
        else:
            from ...utils.thumb_cache import thumb_cache_path as _tcp
            cache_name = _tcp(path, cache_dir).name
        base = cache_dir / cache_name          # always .png stem
        encrypted = bool(self._key)
        for suffix in (".enc" if encrypted else ".png", ".skip"):
            try:
                base.with_suffix(suffix).unlink(missing_ok=True)
            except OSError:
                pass
        # Clear the displayed thumb immediately so the UI shows a blank placeholder.
        self._selected_thumb_source = ""
        self.selectedThumbSourceChanged.emit()
        # Bust the left-grid thumbnail URI so QML's pixmap cache refetches the
        # rebuilt PNG once the worker finishes (the filename is identical so
        # without a busted URL QML would keep serving the stale cached image).
        if self._current_result_row >= 0:
            self._search_model.bust_thumbnail(self._current_result_row)
        # Rebuild: ensure the thumb worker runs a fresh scan that includes this
        # file.  If a worker is already running it has already captured its
        # `paths` list (before we deleted the skip), so cancel it and let the
        # `_pending_thumb_restart` flag trigger a new run once it exits.
        if self._is_building_thumbs and self._thumb_worker is not None:
            self._pending_thumb_restart = True
            self._thumb_worker.cancel()
        elif not self._is_building_thumbs:
            self._start_auto_thumbs()

    @Slot()
    def recreatePreview(self) -> None:
        """Delete the cached preview for the selected image and re-render it."""
        path = self._pending_preview_path
        stamp = self._pending_preview_stamp
        if not path:
            return
        cache_dir = self._search_model.cache_dir
        if stamp is not None:
            cache_name = preview_cache_name_from_stamp(path, stamp[0], stamp[1])
        else:
            from ...utils.preview_cache import preview_cache_path as _pcp
            cache_name = _pcp(path, cache_dir).name
        encrypted = bool(self._key)
        cached_file = preview_dir(cache_dir) / cache_name  # always ends in .jpg
        # Worker saves as <sha1>.jpg (plain) or <sha1>.jpg.enc (encrypted).
        # Use with_suffix on the full compound extension to get the right filename.
        enc_file = cached_file.with_name(cache_name + ".enc")  # <sha1>.jpg.enc
        for f in (enc_file if encrypted else cached_file, cached_file):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        # Bust the URL cache so QML Image reloads from the provider.
        self._preview_bust += 1
        # Update hasPreview flag then force the provider to re-render.
        has_preview = self._compute_has_preview(path, stamp)
        if has_preview != self._selected_has_preview:
            self._selected_has_preview = has_preview
            self.selectedHasPreviewChanged.emit()
        self._refresh_selected_image_source()

    @Slot()
    def copyPreviewToClipboard(self) -> None:
        """Copy the currently displayed preview image to the system clipboard.

        Falls back to copying the file path (as plain text) when the image
        cannot be decoded (e.g. source file on a disconnected drive).
        """
        path = self._pending_preview_path
        if not path:
            return
        if not os.path.exists(path):
            QGuiApplication.clipboard().setText(path)
            self.clipboardCopyDone.emit(_("File not accessible \u2014 path copied"))
            return
        try:
            import io
            from PySide6.QtCore import QByteArray, QMimeData
            from PySide6.QtGui import QImage

            pil_img = self._load_preview_for_clipboard(path)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            mime = QMimeData()
            # image/png → public.png UTI on macOS and MIME on Linux so that
            # native apps (Messages, Mail, GIMP, etc.) receive a real image.
            mime.setData("image/png", QByteArray(png_bytes))
            # setImageData → CF_DIB on Windows so legacy Win32 apps (Paint,
            # older Office builds) that only read CF_DIB still work.
            rgba = pil_img.convert("RGBA")
            raw = bytes(rgba.tobytes("raw", "RGBA"))
            qimage = QImage(
                raw, rgba.width, rgba.height, QImage.Format.Format_RGBA8888
            ).copy()
            mime.setImageData(qimage)
            QGuiApplication.clipboard().setMimeData(mime)
            self.clipboardCopyDone.emit(_("Image copied to clipboard"))
        except Exception:  # noqa: BLE001
            _log.exception("copyPreviewToClipboard failed for %r, falling back to path", path)
            QGuiApplication.clipboard().setText(path)
            self.clipboardCopyDone.emit(_("Path copied to clipboard"))

    @Slot(str)
    def doSavePreview(self, file_url: str) -> None:
        """Save the currently displayed preview image to the path chosen in QML."""
        path = self._pending_preview_path
        if not path:
            return
        if not os.path.exists(path):
            self.clipboardCopyDone.emit(_("File not accessible"))
            return
        dest = Path(QUrl(file_url).toLocalFile())
        try:
            pil_img = self._load_preview_for_clipboard(path)
            if dest.suffix.lower() == ".png":
                pil_img.save(str(dest), format="PNG")
            else:
                pil_img.convert("RGB").save(str(dest), format="JPEG", quality=95)
            self.clipboardCopyDone.emit(_("Preview saved"))
        except Exception:  # noqa: BLE001
            _log.exception("doSavePreview failed for %r → %r", path, dest)

    @Slot(str)
    def doSaveOriginal(self, file_url: str) -> None:
        """Copy the original source file to the path chosen in QML."""
        path = self._pending_preview_path
        if not path:
            return
        if not os.path.exists(path):
            self.clipboardCopyDone.emit(_("File not accessible"))
            return
        dest = Path(QUrl(file_url).toLocalFile())
        try:
            shutil.copy2(path, str(dest))
            self.clipboardCopyDone.emit(_("Original saved"))
        except Exception:  # noqa: BLE001
            _log.exception("doSaveOriginal failed for %r → %r", path, dest)

    @Slot(bool)
    def setUseRawPreview(self, use_raw: bool) -> None:
        """Switch the big preview between cached preview and full-res raw."""
        if self._use_raw_preview == use_raw:
            return
        self._use_raw_preview = use_raw
        self.useRawPreviewChanged.emit()
        # Re-resolve the source so the QML Image picks up the new scheme.
        self._refresh_selected_image_source()

    def _refresh_selected_image_source(self) -> None:
        path = self._pending_preview_path
        if not path:
            return
        scheme = "raw" if self._use_raw_preview else "preview"
        self._selected_image_source = self._build_preview_uri(path, scheme)
        self.selectedImageSourceChanged.emit()

    def _build_preview_uri(self, path: str, scheme: str) -> str:
        """Build an ``image://<scheme>/<encoded-path>`` URI.

        When a DB-stored stamp is known for the pending preview, append it as
        a query string so the provider can locate the cached preview without
        statting the source file (which may live on a disconnected drive).
        """
        encoded = urllib.parse.quote(path, safe="")
        stamp = self._pending_preview_stamp
        px = self._pending_preview_pixel_count
        bust = f"&t={self._preview_bust}" if self._preview_bust else ""
        if stamp is not None:
            px_param = f"&px={px}" if px else ""
            return f"image://{scheme}/{encoded}?m={stamp[0]}&s={stamp[1]}{px_param}{bust}"
        if bust:
            return f"image://{scheme}/{encoded}?{bust[1:]}"  # strip leading &
        return f"image://{scheme}/{encoded}"

    @Slot()
    def resetDatabase(self) -> None:
        """Wipe all images, indexed-folder records, and the thumbnail cache."""
        if self._repo is None or self._folder_repo is None:
            return
        try:
            self._repo.clear_all()
            self._folder_repo.clear_all()
            if self._cache_dir and self._cache_dir.exists():
                shutil.rmtree(self._cache_dir)
                self._cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            _log.exception("resetDatabase failed")
            return
        # Re-configure providers so they generate a fresh master key against
        # the newly-empty cache dir.  Without this the providers keep the old
        # in-memory ThumbCrypto (keyed to the deleted .thumb_key) and every
        # subsequent thumbnail request silently fails with InvalidTag.
        if self._thumb_provider is not None and self._cache_dir is not None:
            self._thumb_provider.set_key(self._key, self._cache_dir)
        if self._preview_provider is not None and self._cache_dir is not None:
            self._preview_provider.set_cache(self._cache_dir, self._key)
        self._search_model.set_rows([])
        self._exif_model.set_rows([])
        self._folder_model.set_rows([])
        self._total_results = 0
        self.totalResultsChanged.emit()
        self._clear_details()
        self._folder_tree_dirty = True
        self.folderTreeChanged.emit()
        self._set_status(_("Database reset"))

    @Slot(str)
    def openUrl(self, url: str) -> None:
        """Open an arbitrary URL (http/https/file) in the system default app."""
        if not url:
            return
        if sys.platform == "linux":
            subprocess.Popen(["xdg-open", url], env=_pyinstaller_clean_env())
        else:
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def openImage(self, path: str) -> None:
        if not path:
            return
        if not os.path.exists(path):
            self._set_status(_("File not found: {}").format(Path(path).name))
            return
        if sys.platform == "linux":
            subprocess.Popen(["xdg-open", path], env=_pyinstaller_clean_env())
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def openFolder(self, path: str) -> None:
        if not path:
            return
        if not os.path.exists(path):
            self._set_status(_("File not found: {}").format(Path(path).name))
            return
        if os.name == "nt":
            # /select,"<path>" must be passed as a shell string so the quoted
            # path survives argument splitting even when it contains spaces.
            # Windows NTFS paths cannot contain " so the quoting is safe.
            norm = os.path.normpath(path)
            subprocess.Popen(f'explorer /select,"{norm}"', shell=True)
        elif sys.platform == "darwin":
            # -R reveals (selects) the item in Finder.
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(
                ["xdg-open", str(Path(path).parent)],
                env=_pyinstaller_clean_env(),
            )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        if self._status_text != text:
            self._status_text = text
            self.statusTextChanged.emit()

    def _clear_details(self) -> None:
        self._preview_delay_timer.stop()
        self._pending_preview_path = ""
        self._pending_preview_stamp = None
        self._pending_preview_pixel_count = None
        self._details_plain_text = ""
        self._details_html = ""
        self.detailsHtmlChanged.emit()
        if self._geo_location_url:
            self._geo_location_url = ""
            self.geoLocationUrlChanged.emit()
        if self._geo_google_maps_url:
            self._geo_google_maps_url = ""
            self.geoGoogleMapsUrlChanged.emit()
        if self._geo_wikipedia_url:
            self._geo_wikipedia_url = ""
            self.geoWikipediaUrlChanged.emit()
        self._exif_model.set_rows([])
        self._selected_image_source = ""
        self._selected_thumb_source = ""
        self._current_result_row = -1
        self.selectedImageSourceChanged.emit()
        self.selectedThumbSourceChanged.emit()
        self.currentResultRowChanged.emit()
        self.currentProxyResultRowChanged.emit()
        if self._selected_has_preview:
            self._selected_has_preview = False
            self.selectedHasPreviewChanged.emit()

    def _compute_has_preview(
        self, path: str, stamp: tuple[float, int] | None
    ) -> bool:
        """Return True when a rendered preview exists in the on-disk cache.

        Uses DB-stored ``stamp`` (mtime, size) to compute the cache filename so
        the lookup works even when the source drive is disconnected.  Falls
        back to ``False`` for legacy rows without a stamp — the cache key is
        derived from those values, so without them we cannot locate the file.
        """
        if not path or self._cache_dir is None or stamp is None:
            return False
        try:
            name = preview_cache_name_from_stamp(path, stamp[0], stamp[1])
        except Exception:
            return False
        cache_path = preview_dir(self._cache_dir) / name
        if cache_path.exists():
            return True
        # Encrypted variant used when a DB key is set.
        return cache_path.with_suffix(".jpg.enc").exists()

    def _update_exif_table(self, meta_json: str) -> None:
        try:
            parsed = json.loads(meta_json)
            if isinstance(parsed, dict):
                rows = sorted(
                    [(str(k), str(v)) for k, v in parsed.items()],
                    key=lambda r: r[0].lower(),
                )
                self._exif_model.set_rows(rows)
                osm_url, gmaps_url, wiki_url = self._extract_geo_urls(parsed)
                if osm_url != self._geo_location_url:
                    self._geo_location_url = osm_url
                    self.geoLocationUrlChanged.emit()
                if gmaps_url != self._geo_google_maps_url:
                    self._geo_google_maps_url = gmaps_url
                    self.geoGoogleMapsUrlChanged.emit()
                if wiki_url != self._geo_wikipedia_url:
                    self._geo_wikipedia_url = wiki_url
                    self.geoWikipediaUrlChanged.emit()
                return
        except Exception:
            pass
        self._exif_model.set_rows([])
        if self._geo_location_url:
            self._geo_location_url = ""
            self.geoLocationUrlChanged.emit()
        if self._geo_google_maps_url:
            self._geo_google_maps_url = ""
            self.geoGoogleMapsUrlChanged.emit()
        if self._geo_wikipedia_url:
            self._geo_wikipedia_url = ""
            self.geoWikipediaUrlChanged.emit()

    @staticmethod
    def _extract_geo_urls(parsed: dict) -> tuple[str, str, str]:
        lat_raw = parsed.get("GPS:GPSLatitude")
        lon_raw = parsed.get("GPS:GPSLongitude")
        if lat_raw is None or lon_raw is None:
            return "", "", ""
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except (TypeError, ValueError):
            return "", "", ""
        lat_ref = str(parsed.get("GPS:GPSLatitudeRef", "N")).strip().upper()
        lon_ref = str(parsed.get("GPS:GPSLongitudeRef", "E")).strip().upper()
        if lat_ref == "S":
            lat = -lat
        if lon_ref == "W":
            lon = -lon
        osm = f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}&zoom=14"
        gmaps = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
        # GeoHack is the official Wikimedia coordinate hub — shows Wikipedia articles
        # and other geo tools for exact coordinates without any geolocation prompt.
        lat_hemi = "N" if lat >= 0 else "S"
        lon_hemi = "E" if lon >= 0 else "W"
        wiki = (
            f"https://geohack.toolforge.org/geohack.php"
            f"?params={abs(lat):.6f}_{lat_hemi}_{abs(lon):.6f}_{lon_hemi}_"
        )
        return osm, gmaps, wiki

    def _update_details_html(self) -> None:
        text = self._details_plain_text
        ranges: List[Tuple[int, int, str]] = []
        if self._query_text:
            # Strip FTS5 phrase-quote characters and trailing prefix-wildcards
            # so a query like `"GPS:"` or `Canon*` highlights the literal
            # substring rather than the syntax-decorated form.
            highlight_query = self._query_text.replace('"', "").rstrip("*").strip()
            if highlight_query:
                for s, e in self._find_all(text, highlight_query):
                    ranges.append((s, e, "#fff176"))
        if self._find_positions and self._find_index >= 0:
            s, e = self._find_positions[self._find_index]
            ranges.append((s, e, "#ffab40"))
        self._details_html = self._build_html(text, ranges)
        self.detailsHtmlChanged.emit()

    def _update_find_scroll(self) -> None:
        if not self._find_positions or self._find_index < 0:
            return
        char_pos = self._find_positions[self._find_index][0]
        text_len = len(self._details_plain_text)
        self._find_scroll_fraction = char_pos / text_len if text_len else 0.0
        self.findScrollFractionChanged.emit()

    def _on_index_progress(self, current: int, total: int, path: str) -> None:
        # Cache GC sentinel: emitted once after build_index, before the
        # finished signal, while orphaned thumb/preview files are unlinked.
        if current == -1 and total == -1:
            self._set_status(_("Cleaning up cache\u2026"))
            return
        # current == 0 and total > 0 is the scan-complete sentinel emitted by
        # IndexerService once the directory walk finishes and the file count is
        # known.  Never throttle it — it fires exactly once per run and is the
        # trigger to start the thumbnail batch timer.
        is_scan_complete = current == 0 and total > 0
        # Throttle UI updates to at most ~10 Hz — prevents flooding the event loop
        # on large folders with thousands of files.
        now = time.monotonic()
        if not is_scan_complete and now - self._last_progress_update < 0.1 and current != total:
            return
        self._last_progress_update = now
        self._index_current = current
        self._index_total = total
        self._index_current_file = Path(path).name if path else ""
        self.indexCurrentChanged.emit()
        self.indexTotalChanged.emit()
        self.indexCurrentFileChanged.emit()
        if total == 0 and current > 0:
            self._set_status(_("Indexing\u2026 {} (scanning)").format(current))
        elif is_scan_complete:
            self._set_status(_("Indexing\u2026 0 / {}").format(total))
        else:
            self._set_status(_("Indexing\u2026 {} / {}").format(current, total))
        if is_scan_complete:
            pass  # timer already running since indexing started

    def _on_thumb_progress(self, current: int, total: int, path: str) -> None:
        # Throttle to ~5 Hz — ThumbWorker can fire thousands of signals per second
        # with multi-threaded workers, which floods the GUI event loop.
        now = time.monotonic()
        if now - self._last_thumb_progress_update < 0.2 and current != total:
            return
        self._last_thumb_progress_update = now
        self._thumb_current = current
        self._thumb_total = total
        self._thumb_current_file = Path(path).name if path else ""
        self.thumbCurrentChanged.emit()
        self.thumbTotalChanged.emit()
        self.thumbCurrentFileChanged.emit()

    def _start_auto_thumbs(self) -> None:
        """Queue thumbnail generation for all images not yet cached."""
        if self._repo is None or self._is_building_thumbs:
            return
        self._is_building_thumbs = True
        self._thumb_current = 0
        self._thumb_total = 0  # indeterminate until ThumbWorker reports total
        self._thumb_current_file = ""
        self.isBuildingThumbsChanged.emit()
        self.thumbCurrentChanged.emit()
        self.thumbTotalChanged.emit()
        self.thumbCurrentFileChanged.emit()
        self._thumb_worker = ThumbWorker(
            self._db_path,
            self._search_model.cache_dir,
            workers=min(
                self._settings.workerCount if self._settings else _DEFAULT_WORKERS,
                _MAX_THUMB_WORKERS,
            ),
            key=self._key,
        )
        self._thumb_worker.progress.connect(self._on_thumb_progress)
        self._thumb_worker.finished.connect(self._on_thumb_done)
        self._thumb_worker.failed.connect(self._on_thumb_failed)
        self._thumb_worker.canceled.connect(self._on_thumb_canceled)
        # LowPriority (QoS utility) instead of LowestPriority (QoS background):
        # on macOS, LowestPriority maps to QOS_CLASS_BACKGROUND which the scheduler
        # starves whenever IndexWorker (LowPriority/utility) is active, making thumbs
        # appear to generate only after indexing finishes.
        self._thumb_worker.start(QThread.Priority.LowPriority)
        self._thumb_refresh_timer.start()

    def _load_pending_preview(self) -> None:
        """Fire the full preview load after the debounce delay."""
        path = self._pending_preview_path
        if path:
            scheme = "raw" if self._use_raw_preview else "preview"
            self._selected_image_source = self._build_preview_uri(path, scheme)
        else:
            self._selected_image_source = ""
        self.selectedImageSourceChanged.emit()
        # Pause background workers to yield I/O bandwidth to the preview load
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.pause()
        if self._index_worker and self._index_worker.isRunning():
            self._index_worker.pause()
        self._preview_resume_timer.start()  # resets if already running

    def _resume_thumb_for_preview(self) -> None:
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.resume()
        if self._index_worker and self._index_worker.isRunning():
            self._index_worker.resume()

    @Slot()
    def onPreviewStatusChanged(self) -> None:
        """Called by QML when the full-res preview image reaches Ready or Error.

        Cancels the fallback timer and immediately resumes background workers
        so they are not kept paused longer than necessary.  On macOS, the scan
        phase can hold off disk I/O long enough that a NAS preview read takes
        more than the old 2-second fixed timeout; signalling from QML means
        workers resume the instant the decode finishes, no earlier and no later.
        """
        self._preview_resume_timer.stop()
        self._resume_thumb_for_preview()

    def _refresh_selected_thumb_source(self) -> None:
        """Re-read the thumbnail URI for the current row and emit if changed."""
        row = self._current_result_row
        if row < 0:
            return
        uri = self._search_model.data(
            self._search_model.index(row, 0),
            SearchListModel.ThumbnailSourceRole,
        )
        new_uri = uri or ""
        if new_uri != self._selected_thumb_source:
            self._selected_thumb_source = new_uri
            self.selectedThumbSourceChanged.emit()

    def _on_thumb_refresh_tick(self) -> None:
        """Periodic mid-batch refresh so thumbnails appear as they are written."""
        if self._is_building_thumbs:
            self._search_model.refresh_thumbnails()
            self._refresh_selected_thumb_source()

    def _on_thumb_done(self, cached: int, total: int) -> None:
        self._thumb_refresh_timer.stop()
        self._is_building_thumbs = False
        self.isBuildingThumbsChanged.emit()
        self._search_model.refresh_thumbnails()
        self._refresh_selected_thumb_source()
        if self._pending_thumb_restart:
            self._pending_thumb_restart = False
            self._start_auto_thumbs()

    def _on_thumb_failed(self, error: str) -> None:
        self._thumb_refresh_timer.stop()
        self._is_building_thumbs = False
        self.isBuildingThumbsChanged.emit()

    def _on_thumb_canceled(self, cached: int, total: int) -> None:
        self._thumb_refresh_timer.stop()
        self._is_building_thumbs = False
        self.isBuildingThumbsChanged.emit()
        self._search_model.refresh_thumbnails()
        if self._pending_thumb_restart:
            self._pending_thumb_restart = False
            self._start_auto_thumbs()

    def close(self) -> None:
        # Stop any running background QThread workers before closing the DB
        # connections they may still be using.  Without this, a worker that
        # is mid-flight (e.g. ThumbWorker hashing files) can outlive the
        # repository and crash the process when it next touches the closed
        # connection — observed both on app exit and across pytest fixtures.
        for worker in (
            self._thumb_worker,
            self._preview_worker,
            self._index_worker,
            self._password_change_worker,
        ):
            if worker is not None and worker.isRunning():
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
                else:
                    worker.requestInterruption()
                worker.quit()
                worker.wait(5000)
        self._thumb_worker = None
        self._preview_worker = None
        self._index_worker = None
        self._password_change_worker = None

        if self._repo is not None:
            self._repo.close()
            self._repo = None
        if self._folder_repo is not None:
            self._folder_repo.close()
            self._folder_repo = None


    @staticmethod
    def _find_all(text: str, query: str) -> List[Tuple[int, int]]:
        if not query:
            return []
        positions: List[Tuple[int, int]] = []
        lower_text = text.lower()
        lower_query = query.lower()
        start = 0
        while True:
            pos = lower_text.find(lower_query, start)
            if pos == -1:
                break
            positions.append((pos, pos + len(query)))
            start = pos + 1
        return positions

    @staticmethod
    def _build_html(text: str, ranges: List[Tuple[int, int, str]]) -> str:
        sorted_ranges = sorted(ranges, key=lambda r: r[0])
        parts: List[str] = [
            "<pre style=\"font-family: 'Courier New', monospace;"
            " white-space: pre-wrap; word-break: break-all;"
            " font-size: 11pt; margin: 0; padding: 8px;\">"
        ]
        last = 0
        for start, end, color in sorted_ranges:
            if start < last:
                continue
            parts.append(html_lib.escape(text[last:start]))
            # Force dark text on the (light) yellow/orange highlight so the
            # contrast is readable in both light and dark themes — without an
            # explicit color the span inherits the panel's foreground (white
            # on dark theme), which is unreadable on yellow.
            parts.append(
                f'<span style="background-color:{color};color:#000000">'
            )
            parts.append(html_lib.escape(text[start:end]))
            parts.append("</span>")
            last = end
        parts.append(html_lib.escape(text[last:]))
        parts.append("</pre>")
        return "".join(parts)
