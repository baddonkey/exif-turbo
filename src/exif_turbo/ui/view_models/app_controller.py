from __future__ import annotations

import html as html_lib
import io
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
from PySide6.QtCore import (
    Property,
    QObject,
    QByteArray,
    QMimeData,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication, QImage

from ...data.image_index_repository import ImageIndexRepository
from ...data.indexed_folder_repository import IndexedFolderRepository
from ...config import tgm_snapshot_path, tgm_vector_metadata_path
from ...i18n import _
from ...indexing.exif_metadata_extractor import get_exiftool_version
from ...indexing.ai_indexer_service import (
    CLIP_MODEL_NAME,
    CLIP_PRETRAINED,
    CLIP_VECTOR_DIMENSION,
)
from ...indexing.image_utils import RAW_EXTENSIONS
from ...models.indexed_folder import IndexedFolder
from ...models.search_result import SearchResult
from ...models.tgm import TgmCategory
from ...tagging.derivative_export_service import (
    extract_embedded_keyword_labels,
    merge_keyword_labels,
)
from ...tagging.sidecar_repository import FilesystemSidecarRepository
from ...tagging.tagging_service import TaggingService
from ...tagging.tgm_snapshot_repository import TgmSnapshotRepository
from ...tagging.tgm_prompt_builder import TgmPromptBuilder
from ...utils.preview_cache import (
    clear_cached_previews_for,
    count_cached_previews,
    list_existing_previews,
    preview_cache_name_from_stamp,
    preview_dir,
)
from ...utils.json_export import JsonExportFormat
from ...utils.thumb_cache import thumb_cache_name_from_stamp
from ..models.checked_filter_proxy_model import CheckedFilterProxyModel
from ..models.accepted_tag_list_model import AcceptedTagListModel
from ..models.exif_list_model import ExifListModel
from ..models.embedded_tag_list_model import EmbeddedTagListModel
from ..models.folder_list_model import FolderListModel
from ..models.free_tag_list_model import FreeTagListModel
from ..models.marked_tag_list_model import MarkedTagListModel
from ..models.pending_proposal_list_model import PendingProposalListModel
from ..models.search_list_model import SearchListModel
from ..models.settings_model import SettingsModel
from ..models.tgm_search_list_model import TgmSearchListModel
from ..workers.ai_scan_worker import AiScanWorker
from ..workers.ai_search_worker import AiSearchWorker
from ..workers.bulk_op_worker import BulkOpWorker
from ..workers.bulk_tag_worker import BulkTagWorker
from ..workers.copy_tags_worker import CopyTagsWorker
from ..workers.derivative_export_worker import DerivativeExportWorker
from ..workers.folder_tree_worker import FolderTreeWorker
from ..workers.index_worker import IndexWorker
from ..workers.maintenance_worker import MaintenanceWorker
from ..workers.password_change_worker import PasswordChangeWorker
from ..workers.preview_build_worker import PreviewBuildWorker
from ..workers.search_worker import SearchPageWorker, SearchWorker
from ..workers.thumb_worker import ThumbWorker
from ..workers.tgm_proposal_worker import TgmProposalWorker
from ..workers.tgm_update_worker import TgmUpdateWorker
from ..workers.tgm_vector_build_worker import TgmVectorBuildWorker
from ..workers.year_counts_worker import YearCountsWorker
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
    searchRestoreReady = Signal()
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
    busyDetailChanged = Signal()
    bulkProgressChanged = Signal()
    isUnlockingChanged = Signal()
    passwordChangeFinished = Signal(bool, str)  # (success, message)
    busyCancelableChanged = Signal()
    exiftoolMissingChanged = Signal()
    exiftoolVersionChanged = Signal()
    clipboardCopyDone = Signal(str)  # message to show in toast
    dateFilterChanged = Signal()
    yearCountsChanged = Signal()
    taggingStateChanged = Signal()
    tgmOperationChanged = Signal()
    proposalOperationChanged = Signal()
    bulkTagOperationChanged = Signal()
    derivativeOperationChanged = Signal()

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
        self._status_is_error = False
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
        self._pending_load_more_request = False
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
        # Semantic result paths BEFORE the date filter is applied.  Drives the
        # AI-mode year histogram so selecting a single year does not collapse
        # the other selectable years.
        self._ai_facet_paths: list[str] = []
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
        self._year_counts_worker: YearCountsWorker | None = None
        self._pending_year_counts_serial: int = 0
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
        self._busy_detail: str = ""
        self._bulk_progress: int = 0
        self._bulk_progress_total: int = 0
        self._bulk_worker: BulkOpWorker | None = None
        self._maint_worker: MaintenanceWorker | None = None
        self._maint_operation: str = ""
        self._pending_remove_folder: IndexedFolder | None = None
        self._pending_export_path: Path | None = None
        self._is_unlocking: bool = False
        self._exiftool_missing: bool = False
        self._exiftool_version: str = ""  # populated lazily by checkExiftool slot
        self._password_change_worker: PasswordChangeWorker | None = None
        self._password_change_old: str = ""
        self._password_change_new: str = ""
        self._tgm_repository: TgmSnapshotRepository | None = None
        self._tagging_service: TaggingService | None = None
        self._accepted_tags_model = AcceptedTagListModel()
        self._embedded_tags_model = EmbeddedTagListModel()
        self._derivative_tags_model = FreeTagListModel()
        self._embedded_tags: tuple[str, ...] = ()
        self._excluded_embedded_tags: tuple[str, ...] = ()
        self._exclude_all_embedded_tags = False
        self._free_tags_model = FreeTagListModel()
        self._free_tag_suggestions_model = FreeTagListModel()
        self._tgm_search_model = TgmSearchListModel()
        self._pending_proposals_model = PendingProposalListModel()
        self._marked_tags_model = MarkedTagListModel()
        self._marked_tag_total = 0
        self._marked_tagged_total = 0
        self._selected_tagging_error = ""
        self._tgm_metadata: dict[str, object] = {}
        self._tgm_vectors_current = False
        self._tgm_operation = False
        self._tgm_progress = (0, 0)
        self._tgm_error = ""
        self._proposal_operation = False
        self._proposal_progress = (0, 0)
        self._proposal_error = ""
        self._bulk_tag_operation = False
        self._bulk_tag_progress = (0, 0)
        self._bulk_tag_summary = ""
        self._bulk_tag_action = ""
        self._derivative_operation = False
        self._derivative_progress = (0, 0)
        self._derivative_summary = ""
        self._tgm_update_worker: TgmUpdateWorker | None = None
        self._tgm_vector_worker: TgmVectorBuildWorker | None = None
        self._proposal_worker: TgmProposalWorker | None = None
        self._bulk_tag_worker: BulkTagWorker | None = None
        self._copy_tags_worker: CopyTagsWorker | None = None
        self._derivative_worker: DerivativeExportWorker | None = None
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

    @Property(bool, notify=statusTextChanged)
    def statusIsError(self) -> bool:
        return self._status_is_error

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
        if value and self._settings and not self._settings.aiFeatureAvailable:
            value = False
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

    # ── Tagging ───────────────────────────────────────────────────────────────

    @Property(bool, notify=taggingStateChanged)
    def taggingEnabled(self) -> bool:
        return self._settings.tagging_enabled if self._settings else False

    @Property(bool, notify=taggingStateChanged)
    def taggingAvailable(self) -> bool:
        return self.taggingEnabled and bool(self._tgm_metadata) and not self._is_locked

    @Property(bool, notify=taggingStateChanged)
    def freeTaggingAvailable(self) -> bool:
        return self.taggingEnabled and not self._is_locked

    @Property(bool, notify=taggingStateChanged)
    def taggingProposalAvailable(self) -> bool:
        return self.taggingAvailable and self._ai_enabled and self._tgm_vectors_current

    @Property(QObject, constant=True)
    def acceptedTagsModel(self) -> QObject:
        return self._accepted_tags_model

    @Property(QObject, constant=True)
    def embeddedTagsModel(self) -> QObject:
        return self._embedded_tags_model

    @Property(bool, notify=taggingStateChanged)
    def excludeAllEmbeddedTags(self) -> bool:
        return self._exclude_all_embedded_tags

    @Property(QObject, constant=True)
    def derivativeTagsModel(self) -> QObject:
        return self._derivative_tags_model

    @Property(QObject, constant=True)
    def freeTagsModel(self) -> QObject:
        return self._free_tags_model

    @Property(QObject, constant=True)
    def freeTagSuggestionsModel(self) -> QObject:
        return self._free_tag_suggestions_model

    @Property(QObject, constant=True)
    def tgmSearchModel(self) -> QObject:
        return self._tgm_search_model

    @Property(QObject, constant=True)
    def pendingProposalsModel(self) -> QObject:
        return self._pending_proposals_model

    @Property(QObject, constant=True)
    def markedTagsModel(self) -> QObject:
        return self._marked_tags_model

    @Property(int, notify=taggingStateChanged)
    def markedTagImageCount(self) -> int:
        return self._marked_tag_total

    @Property(int, notify=taggingStateChanged)
    def markedTaggedImageCount(self) -> int:
        return self._marked_tagged_total

    @Property(str, notify=taggingStateChanged)
    def selectedTaggingError(self) -> str:
        return self._selected_tagging_error

    @Property(bool, notify=taggingStateChanged)
    def tgmInstalled(self) -> bool:
        return bool(self._tgm_metadata)

    @Property(str, notify=taggingStateChanged)
    def tgmStatus(self) -> str:
        if not self._tgm_metadata:
            return "not_installed"
        return "ready" if self._tgm_vectors_current else "vectors_required"

    @Property(str, notify=taggingStateChanged)
    def tgmSourceDate(self) -> str:
        return str(self._tgm_metadata.get("source_date", ""))

    @Property(str, notify=taggingStateChanged)
    def tgmChecksum(self) -> str:
        return str(self._tgm_metadata.get("checksum", ""))

    @Property(int, notify=taggingStateChanged)
    def tgmSubjectCount(self) -> int:
        return int(self._tgm_metadata.get("subject_count", 0))

    @Property(int, notify=taggingStateChanged)
    def tgmGenreFormatCount(self) -> int:
        return int(self._tgm_metadata.get("genre_count", 0))

    @Property(str, notify=taggingStateChanged)
    def tgmDiagnosticsSummary(self) -> str:
        return str(self._tgm_metadata.get("diagnostics", ""))

    @Property(bool, notify=tgmOperationChanged)
    def isTgmUpdating(self) -> bool:
        return self._tgm_operation

    @Property(int, notify=tgmOperationChanged)
    def tgmUpdateCurrent(self) -> int:
        return self._tgm_progress[0]

    @Property(int, notify=tgmOperationChanged)
    def tgmUpdateTotal(self) -> int:
        return self._tgm_progress[1]

    @Property(str, notify=tgmOperationChanged)
    def tgmUpdateError(self) -> str:
        return self._tgm_error

    @Property(bool, notify=proposalOperationChanged)
    def isGeneratingTagProposals(self) -> bool:
        return self._proposal_operation

    @Property(int, notify=proposalOperationChanged)
    def proposalGenerationCurrent(self) -> int:
        return self._proposal_progress[0]

    @Property(int, notify=proposalOperationChanged)
    def proposalGenerationTotal(self) -> int:
        return self._proposal_progress[1]

    @Property(str, notify=proposalOperationChanged)
    def proposalGenerationError(self) -> str:
        return self._proposal_error

    @Property(bool, notify=bulkTagOperationChanged)
    def isTaggingBulk(self) -> bool:
        return self._bulk_tag_operation

    @Property(int, notify=bulkTagOperationChanged)
    def taggingBulkCurrent(self) -> int:
        return self._bulk_tag_progress[0]

    @Property(int, notify=bulkTagOperationChanged)
    def taggingBulkTotal(self) -> int:
        return self._bulk_tag_progress[1]

    @Property(str, notify=bulkTagOperationChanged)
    def taggingBulkSummary(self) -> str:
        return self._bulk_tag_summary

    @Property(bool, notify=derivativeOperationChanged)
    def isExportingDerivatives(self) -> bool:
        return self._derivative_operation

    @Property(int, notify=derivativeOperationChanged)
    def derivativeCurrent(self) -> int:
        return self._derivative_progress[0]

    @Property(int, notify=derivativeOperationChanged)
    def derivativeTotal(self) -> int:
        return self._derivative_progress[1]

    @Property(str, notify=derivativeOperationChanged)
    def derivativeResultSummary(self) -> str:
        return self._derivative_summary

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

    @Property(str, notify=currentResultRowChanged)
    def selectedFilename(self) -> str:
        path = self._search_model.get_path(self._current_result_row)
        return Path(path).name if path else ""

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

    @Property(str, notify=busyDetailChanged)
    def busyDetail(self) -> str:
        return self._busy_detail

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
        self._refresh_marked_tagging_state()

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
            json_format=self._settings.json_export_format if self._settings else None,
        )

    @Slot()
    def cancelBulkOp(self) -> None:
        if self._bulk_worker is not None:
            self._bulk_worker.cancel()
        if self._maint_worker is not None:
            self._maint_worker.cancel()

    # ── Bulk-op worker helpers ────────────────────────────────────────────

    def _start_bulk_op(
        self,
        operation: str,
        label: str,
        *,
        mark_value: bool = True,
        file_path: Path | None = None,
        sort_by: str = "path_asc",
        json_format: JsonExportFormat | None = None,
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
            json_format=json_format,
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
        self._refresh_marked_tagging_state()

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

    # ── Maintenance-op worker helpers (remove folder / reset database) ────────

    def _start_maintenance_op(
        self,
        operation: str,
        label: str,
        *,
        folder_id: int | None = None,
        folder_path: str | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        """Spawn a MaintenanceWorker and show the busy overlay."""
        if self._is_busy:
            return
        self._maint_operation = operation
        self._maint_worker = MaintenanceWorker(
            self._db_path,
            self._key,
            operation,
            folder_id=folder_id,
            folder_path=folder_path,
            cache_dir=cache_dir,
        )
        self._maint_worker.progress.connect(self._on_maint_progress)
        self._maint_worker.cancelable.connect(self._on_maint_cancelable)
        self._maint_worker.finished.connect(self._on_maint_finished)
        self._maint_worker.failed.connect(self._on_maint_failed)
        self._maint_worker.canceled.connect(self._on_maint_canceled)
        self._bulk_progress = 0
        self._bulk_progress_total = 0
        self._busy_detail = ""
        self._busy_label = label
        self._busy_cancelable = True
        self._is_busy = True
        self.isBusyChanged.emit()
        self.busyLabelChanged.emit()
        self.busyDetailChanged.emit()
        self.busyCancelableChanged.emit()
        self.bulkProgressChanged.emit()
        self._maint_worker.start()

    def _on_maint_progress(self, done: int, total: int, message: str) -> None:
        self._bulk_progress = done
        self._bulk_progress_total = total
        self.bulkProgressChanged.emit()
        if message and message != self._busy_detail:
            self._busy_detail = message
            self.busyDetailChanged.emit()

    def _on_maint_cancelable(self, flag: bool) -> None:
        if self._busy_cancelable != flag:
            self._busy_cancelable = flag
            self.busyCancelableChanged.emit()

    def _clear_maint_busy(self) -> None:
        self._maint_worker = None
        self._is_busy = False
        self._busy_detail = ""
        self.isBusyChanged.emit()
        self.busyDetailChanged.emit()

    def _on_maint_finished(self) -> None:
        operation = self._maint_operation
        worker = self._maint_worker
        self._maint_operation = ""
        self._clear_maint_busy()
        if operation == "remove_folder":
            self._finish_remove_folder()
        elif operation == "reset_database":
            self._finish_reset_database()
        elif operation == "refresh_sidecars" and worker is not None:
            self._finish_refresh_sidecars(
                worker.sidecar_image_count,
                worker.sidecar_error_count,
            )

    def _on_maint_failed(self, msg: str) -> None:
        self._maint_operation = ""
        self._pending_remove_folder = None
        self._clear_maint_busy()
        self._set_status(_("Operation failed: {}").format(msg))

    def _on_maint_canceled(self) -> None:
        self._maint_operation = ""
        self._pending_remove_folder = None
        self._clear_maint_busy()
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
            self._initialize_tagging_services()
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
            self._status_is_error = False
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
            self._folder_tree_dirty = True  # loaded on demand when Browse tab is opened
            self._load_indexed_folders()
            self._load_marks()
            self._refresh_marked_tagging_state()
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

    def _ai_search_is_unfiltered_empty(self) -> bool:
        """True when AI mode should fall back to a normal empty search.

        When the AI query is blank and neither the timeline (date) filter nor
        any search-field-area filter (folder, format, marked-only) is active,
        the semantic result set is simply "everything in scope". In that case
        the normal paginated search yields the same images without touching the
        FAISS/AI database or hydrating every indexed row at once.
        """
        return (
            not self._last_ai_query.strip()
            and self._date_from is None
            and self._date_to is None
            and not self._ext_filter
            and not self._checked_only_filter_active
            and self._current_path_filter() is None
        )

    def _results_use_ai_pipeline(self) -> bool:
        """Whether result handling should use the in-memory AI result pipeline.

        AI mode with an active query or filter caches the full ranked result
        set in memory and derives facets from it. The unfiltered-empty case
        instead flows through the normal paginated pipeline (see
        :meth:`_ai_search_is_unfiltered_empty`).
        """
        return self._is_ai_search_mode and not self._ai_search_is_unfiltered_empty()

    def _run_empty_ai_fallback_search(self) -> None:
        """Show all in-scope images via the normal paginated search pipeline.

        Used when AI mode has a blank query and no active filters, avoiding the
        cost of loading the FAISS index and hydrating every indexed row at once.
        """
        self._query_text = ""
        self._current_result_row = 0
        self._run_search()

    def _rerun_ai_search_for_filter_change(self) -> bool:
        if not self._is_ai_search_mode:
            return False
        if not self._has_ai_search_run or self._db_path is None:
            return False
        self._ai_select_first = True
        if self._ai_search_is_unfiltered_empty():
            self._run_empty_ai_fallback_search()
            return True
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
            jump_page_size = _PAGE_SIZE
        else:
            self._query_text = ""
            self._folder_filter = path
            self._pending_browse_jump_id = target_id
            search_offset = 0
            jump_page_size = _PAGE_SIZE
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
                    # Always load from the START of the folder through the target
                    # (plus one screen of forward buffer).  This keeps
                    # _loaded_offset == 0, so scrolling up never triggers a
                    # front-prepend.  A prepend would have to insert the earlier
                    # rows and shift contentY by their full height to stay put —
                    # a large instantaneous jump that macOS renders as a dark area
                    # and that desyncs the scrollbar thumb.  Loading forward-only
                    # (append via loadMore) never moves existing rows, so the view
                    # and scrollbar stay consistent.
                    search_offset = 0
                    jump_page_size = max(_PAGE_SIZE, target_offset + _PAGE_SIZE)
        show_busy_ui = self._pending_browse_jump_id != 0
        self.folderFilterChanged.emit()
        self._run_search(
            show_busy_ui=show_busy_ui, offset=search_offset, page_size=jump_page_size
        )

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
            "ai_facet_paths": list(self._ai_facet_paths) if self._is_ai_search_mode else None,
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
            self._ai_facet_paths = (
                snapshot.get("ai_facet_paths")
                or [res.path for res in saved_rows]
            )
            self._loaded_offset = 0
            self._loading = True
            target_source_row = -1
            if image_id:
                for idx, result in enumerate(saved_rows):
                    if result.image_id == image_id:
                        target_source_row = idx
                        break
            rows_to_restore = _PAGE_SIZE
            if target_source_row >= 0:
                rows_to_restore = max(_PAGE_SIZE, target_source_row + 1)
            self._search_model.set_rows(saved_rows[:rows_to_restore])
            self._recompute_checked_in_results()
            self.checkedCountChanged.emit()
            self._total_results = snapshot["ai_total_results"]
            self._loaded_results = min(len(saved_rows), rows_to_restore)
            did_restore = False
            if image_id and self._loaded_results > 0:
                if self.selectResultById(image_id) < 0:
                    row = (
                        self._current_result_row
                        if 0 <= self._current_result_row < self._loaded_results
                        else 0
                    )
                    self._select_source_row(row)
                did_restore = True
            elif self._loaded_results > 0:
                self._select_source_row(
                    self._current_result_row
                    if 0 <= self._current_result_row < self._loaded_results
                    else 0
                )
            self.totalResultsChanged.emit()
            self.loadedResultsChanged.emit()
            if did_restore:
                QTimer.singleShot(0, self.searchRestoreReady.emit)
            self._loading = False
            self._consume_pending_load_more_request()
            self._schedule_year_counts_reload(self._search_serial)
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

    def _run_search(
        self, show_busy_ui: bool = True, offset: int = 0, page_size: int = _PAGE_SIZE
    ) -> None:
        if self._repo is None or self._db_path is None:
            return
        self._clear_status_for_primary_action()
        path_filter = self._current_path_filter()
        params = dict(
            query=self._query_text,
            page_size=page_size,
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
        ai_facet_paths: list[str] | None = None
        if self.sender() is self._ai_search_worker:
            ai_facet_paths = list(
                getattr(self._ai_search_worker, "facet_paths", []) or []
            )
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
        if self._results_use_ai_pipeline():
            self._ai_result_cache = all_results
            # Timeline facet source: the semantic set before date filtering.
            # Fall back to the (date-filtered) result paths if the worker did
            # not supply facet paths. This keeps tests that patch
            # AiSearchWorker.run and emit rows directly from losing the year
            # histogram source.
            self._ai_facet_paths = (
                ai_facet_paths
                if ai_facet_paths
                else [res.path for res in all_results]
            )
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
                # Image was deleted from the index while browsing; keep the
                # previous search context if it is still a valid row.
                row = (
                    self._current_result_row
                    if 0 <= self._current_result_row < self._loaded_results
                    else 0
                )
                self._select_source_row(row)
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
        if _did_restore:
            # Emit one tick later so QML restores viewport state only after
            # tab visibility/layout transitions settle.
            QTimer.singleShot(0, self.searchRestoreReady.emit)
        self._loading = False
        self._consume_pending_load_more_request()
        if self._results_use_ai_pipeline() and self._repo is not None:
            ai_paths = self._ai_format_facet_source_paths()
            format_counts = self._repo.get_format_counts_by_paths(ai_paths)
        self._apply_format_counts(format_counts)
        # Keep first paint responsive: refresh year histogram on next event-loop
        # tick after the result list and selection have already rendered.
        self._schedule_year_counts_reload(serial)
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

    def _schedule_year_counts_reload(self, serial: int) -> None:
        """Refresh year counts after the current search result has rendered."""
        if self._results_use_ai_pipeline():
            # AI-mode year counts currently depend on in-memory AI path sets.
            # Keep the existing synchronous path for that mode.
            def _reload_ai() -> None:
                if serial != self._search_serial:
                    return
                self._load_year_counts()

            QTimer.singleShot(0, _reload_ai)
            return

        if self._db_path is None:
            return
        if self._year_counts_worker is not None:
            self._pending_year_counts_serial = serial
            return

        worker = YearCountsWorker(
            self._db_path,
            self._key,
            serial=serial,
            query=self._query_text,
            ext_filter=self._ext_filter,
            path_filter=self._current_path_filter(),
            restrict_to_enabled_folders=(self._folder_repo is not None),
        )
        worker.results_ready.connect(self._on_year_counts_ready)
        worker.failed.connect(self._on_year_counts_failed)
        worker.finished.connect(self._on_year_counts_finished)
        self._year_counts_worker = worker
        worker.start()

    def _on_year_counts_ready(self, counts: list, serial: int) -> None:
        if serial != self._search_serial:
            return
        self._year_counts = json.dumps([{"year": y, "count": c} for y, c in counts])
        self.yearCountsChanged.emit()

    def _on_year_counts_failed(self, error: str, serial: int) -> None:
        _log.debug("Year-count worker failed (serial=%s): %s", serial, error)

    def _on_year_counts_finished(self) -> None:
        self._year_counts_worker = None
        if self._pending_year_counts_serial:
            serial = self._pending_year_counts_serial
            self._pending_year_counts_serial = 0
            self._schedule_year_counts_reload(serial)

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
        self._consume_pending_load_more_request()
        try:
            self._recompute_checked_in_results()
        except Exception as exc:
            _log.warning("Failed to recompute checked counters after search failure: %s", exc)
            self._checked_total_count = 0
            self._checked_in_results_count = 0
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
        non-empty query follows the semantic result set.  In both cases the
        active date filter is intentionally ignored so picking one year does
        not hide the other years from the histogram.
        """
        if self._repo is None:
            return []
        if self._last_ai_query.strip():
            return list(self._ai_facet_paths)
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
        if self._results_use_ai_pipeline():
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
            self._pending_load_more_request = True
            return False
        if self._results_use_ai_pipeline():
            if self._loaded_results >= self._total_results:
                self._pending_load_more_request = False
                return False
            next_page = self._ai_result_cache[
                self._loaded_results : self._loaded_results + _PAGE_SIZE
            ]
            if not next_page:
                self._pending_load_more_request = False
                return False
            self._loading = True
            self._search_model.append_rows(next_page)
            self._loaded_results += len(next_page)
            self.loadedResultsChanged.emit()
            self._loading = False
            self._consume_pending_load_more_request()
            return True
        if self._loaded_offset + self._loaded_results >= self._total_results:
            self._pending_load_more_request = False
            return False
        if self._db_path is None:
            self._pending_load_more_request = False
            return False
        page_size = _PAGE_SIZE
        if self._pending_browse_jump_id:
            page_size = _BROWSE_JUMP_PAGE_SIZE
        self._loading = True
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

    def _consume_pending_load_more_request(self) -> None:
        if not self._pending_load_more_request or self._loading:
            return
        self._pending_load_more_request = False
        QTimer.singleShot(0, self.loadMore)

    def _on_load_more_finished(self, rows: list, serial: int) -> None:
        self._load_more_worker = None
        if serial != self._search_serial:
            self._loading = False
            self._consume_pending_load_more_request()
            return
        results = [
            SearchResult(
                image_id=r[0], path=r[1], filename=r[2], metadata_json=r[3],
                size=r[4], mtime=r[5],
            )
            for r in rows
        ]
        self._search_model.append_rows(results)
        self._loaded_results += len(results)
        self.loadedResultsChanged.emit()
        self._loading = False
        self._consume_pending_load_more_request()

    def _on_load_more_failed(self, error: str) -> None:
        self._load_more_worker = None
        _log.error("Load-more failed: %s", error)
        self._loading = False
        self._consume_pending_load_more_request()
        # Notify QML so it can clear any pending upward-prepend hold state even
        # though the row count did not change.
        self.loadedResultsChanged.emit()

    @Slot(int)
    def selectResult(self, proxy_row: int) -> None:
        self._clear_status_for_primary_action()
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
        self._clear_status_for_primary_action()
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
        self._clear_status_for_primary_action()
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
        self.refreshSelectedTaggingState()
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
        if self._is_busy:
            return
        folder = self._folder_repo.get_by_id(folder_id)
        if folder is None:
            return
        # Remove from pending queue before deleting
        self._scan_queue = [(fid, f) for fid, f in self._scan_queue if fid != folder_id]
        if self._scanning_folder_id == folder_id and self._index_worker:
            self._index_worker.cancel()
        # The heavy work — clearing this folder's cached previews and purging
        # its index rows — runs on a MaintenanceWorker so the GUI stays
        # responsive and a progress overlay can be shown.  The matching UI /
        # model updates happen in _finish_remove_folder once the worker is done.
        self._pending_remove_folder = folder
        self._start_maintenance_op(
            "remove_folder",
            _("Removing folder\u2026"),
            folder_id=folder_id,
            folder_path=folder.path,
            cache_dir=self._search_model.cache_dir,
        )

    def _finish_remove_folder(self) -> None:
        folder = self._pending_remove_folder
        self._pending_remove_folder = None
        if folder is None:
            return
        self._folder_model.remove_folder(folder.id)
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

    @Slot(int)
    def refreshSidecarsForFolder(self, folder_id: int) -> None:
        if self._folder_repo is None:
            return
        folder = self._folder_repo.get_by_id(folder_id)
        if folder is None:
            return
        self._start_maintenance_op(
            "refresh_sidecars",
            _("Refreshing sidecar tags\u2026"),
            folder_id=folder_id,
        )

    def _finish_refresh_sidecars(self, image_count: int, error_count: int) -> None:
        self._refresh_selected_tagging_state(preserve_proposals=False)
        self._refresh_marked_tagging_state()
        self._run_search()
        if error_count:
            self._set_status(
                _("Refreshed tags for {count} images; {errors} sidecars had errors.").format(
                    count=image_count,
                    errors=error_count,
                ),
                error=True,
            )
        else:
            self._set_status(
                _("Refreshed sidecar tags for {count} images.").format(
                    count=image_count,
                )
            )

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
        self._cancel_tagging_workers(wait=False)
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
        if self._ai_search_is_unfiltered_empty():
            self._run_empty_ai_fallback_search()
            return
        self._start_ai_search_worker(query, precision)

    def _start_ai_search_worker(self, query: str, precision: str) -> None:
        """Internal helper: create and start an AiSearchWorker."""
        self._clear_status_for_primary_action()
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
        try:
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
        dest = Path(QUrl(file_url).toLocalFile())
        try:
            pil_img = self._load_preview_for_clipboard(path)
        except OSError:
            _log.exception("doSavePreview failed to load preview for %r", path)
            self.clipboardCopyDone.emit(_("Preview source file not accessible"))
            return
        try:
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
            self._warn_unavailable(path)
            self.clipboardCopyDone.emit(_("File not accessible"))
            return
        dest = Path(QUrl(file_url).toLocalFile())
        try:
            shutil.copy2(path, str(dest))
            self.clipboardCopyDone.emit(_("Original saved"))
        except OSError:
            _log.exception("doSaveOriginal failed for %r → %r", path, dest)
            self._warn_unavailable(path)
            self.clipboardCopyDone.emit(_("File not accessible"))
        except Exception:  # noqa: BLE001
            _log.exception("doSaveOriginal failed for %r → %r", path, dest)

    @Slot(bool)
    def setUseRawPreview(self, use_raw: bool) -> None:
        """Switch the big preview between cached preview and full-res raw."""
        if self._use_raw_preview == use_raw:
            return
        self._clear_status_for_primary_action()
        if use_raw:
            path = self._pending_preview_path
            if path and not os.path.exists(path):
                self._warn_unavailable(path)
                return
        self._use_raw_preview = use_raw
        self.useRawPreviewChanged.emit()
        # Re-resolve the source so the QML Image picks up the new scheme.
        self._refresh_selected_image_source()

    def _refresh_selected_image_source(self) -> None:
        path = self._pending_preview_path
        if not path:
            return
        scheme = "raw" if (self._use_raw_preview and os.path.exists(path)) else "preview"
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
        if self._is_busy:
            return
        self._cancel_tagging_workers(wait=True)
        # The heavy work — clearing the on-disk cache, deleting every index
        # row and vacuuming the database — runs on a MaintenanceWorker so the
        # GUI stays responsive and a progress overlay can be shown.  The
        # provider/model resets happen in _finish_reset_database afterwards.
        self._start_maintenance_op(
            "reset_database",
            _("Resetting database\u2026"),
            cache_dir=self._cache_dir,
        )

    def _finish_reset_database(self) -> None:
        if self._cache_dir is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
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
        self._clear_tagging_services()
        self._initialize_tagging_services()
        self._total_results = 0
        self.totalResultsChanged.emit()
        self._clear_details()
        self._folder_tree_dirty = True
        self.folderTreeChanged.emit()
        self._set_status(_("Database reset"))

    # ── Tagging application adapter ──────────────────────────────────────────

    def _initialize_tagging_services(self) -> None:
        if self._repo is None:
            return
        self._tgm_repository = TgmSnapshotRepository(tgm_snapshot_path(self._db_path))
        self._tagging_service = TaggingService(
            self._repo,
            FilesystemSidecarRepository(),
            self._tgm_repository,
        )
        self._refresh_tgm_status()

    def _clear_tagging_services(self) -> None:
        self._cancel_tagging_workers(wait=True)
        self._tgm_repository = None
        self._tagging_service = None
        self._tgm_metadata = {}
        self._tgm_vectors_current = False
        self._accepted_tags_model.set_rows([])
        self._free_tags_model.set_rows([])
        self._free_tag_suggestions_model.set_rows([])
        self._tgm_search_model.set_rows([])
        self._pending_proposals_model.set_rows([])
        self._marked_tags_model.set_rows([])
        self._marked_tag_total = 0
        self._marked_tagged_total = 0
        self.taggingStateChanged.emit()

    def _refresh_tgm_status(self) -> None:
        self._tgm_metadata = {}
        self._tgm_vectors_current = False
        repository = self._tgm_repository
        if repository is None or not tgm_snapshot_path(self._db_path).exists():
            self.taggingStateChanged.emit()
            return
        try:
            snapshot = repository.load()
            counts = repository.counts()
            self._tgm_metadata = {
                "source_date": snapshot.distribution_date
                or snapshot.imported_at.date().isoformat(),
                "checksum": snapshot.raw_sha256,
                "subject_count": counts[TgmCategory.SUBJECT],
                "genre_count": counts[TgmCategory.GENRE_FORMAT],
                "diagnostics": (
                    _("TGM source diagnostics: {}").format(len(snapshot.diagnostics))
                    if snapshot.diagnostics
                    else ""
                ),
            }
            metadata_path = tgm_vector_metadata_path(self._db_path)
            if metadata_path.exists():
                vector_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                fingerprint = vector_metadata.get("fingerprint", {})
                self._tgm_vectors_current = fingerprint == {
                    "raw_tgm_sha256": snapshot.raw_sha256,
                    "normalization_version": snapshot.normalization_version,
                    "prompt_version": TgmPromptBuilder.VERSION,
                    "model_name": CLIP_MODEL_NAME,
                    "pretrained": CLIP_PRETRAINED,
                    "dimension": CLIP_VECTOR_DIMENSION,
                }
        except Exception as exc:  # noqa: BLE001
            self._tgm_metadata = {"diagnostics": str(exc)}
        self.taggingStateChanged.emit()

    @Slot(bool)
    def setTaggingEnabled(self, enabled: bool) -> None:
        if self._settings is not None:
            self._settings.setTaggingEnabled(enabled)
            self.taggingStateChanged.emit()

    @Slot(str)
    def searchTgm(self, query: str) -> None:
        if self._tgm_repository is None or not self.tgmInstalled:
            self._tgm_search_model.set_rows([])
            return
        try:
            self._tgm_search_model.set_rows(self._tgm_repository.search(query))
            self._selected_tagging_error = ""
        except Exception as exc:  # noqa: BLE001
            self._selected_tagging_error = str(exc)
        self.taggingStateChanged.emit()

    @Slot(str)
    def searchFreeTags(self, query: str) -> None:
        if self._repo is None or not self.freeTaggingAvailable:
            self._free_tag_suggestions_model.set_rows([])
            return
        try:
            path = self._search_model.get_path(self._current_result_row)
            assigned = {
                tag.casefold()
                for tag in (() if path is None else self._repo.get_free_tags(path))
            }
            self._free_tag_suggestions_model.set_rows(
                tag
                for tag in self._repo.search_free_tags(query)
                if tag.casefold() not in assigned
            )
            self._selected_tagging_error = ""
        except Exception as exc:  # noqa: BLE001
            self._free_tag_suggestions_model.set_rows([])
            self._selected_tagging_error = str(exc)
        self.taggingStateChanged.emit()

    @Slot()
    def refreshSelectedTaggingState(self) -> None:
        self._refresh_selected_tagging_state(preserve_proposals=False)

    def _refresh_selected_tagging_state(self, *, preserve_proposals: bool) -> None:
        path = self._search_model.get_path(self._current_result_row)
        if not path or self._tagging_service is None:
            self._accepted_tags_model.set_rows([])
            self._free_tags_model.set_rows([])
            self._excluded_embedded_tags = ()
            self._exclude_all_embedded_tags = False
            self._refresh_embedded_tag_rows()
            self._derivative_tags_model.set_rows(self._embedded_tags if path else ())
            if not preserve_proposals:
                self._pending_proposals_model.set_rows([])
            return
        try:
            state = self._tagging_service.get_image_tagging_state(path)
            self._accepted_tags_model.set_rows(state.accepted_tags)
            self._free_tags_model.set_rows(state.free_tags)
            sidecar = state.sidecar
            self._excluded_embedded_tags = (
                () if sidecar is None else sidecar.excluded_embedded_tags
            )
            self._exclude_all_embedded_tags = (
                False if sidecar is None else sidecar.exclude_all_embedded_tags
            )
            self._refresh_embedded_tag_rows()
            self._derivative_tags_model.set_rows(
                merge_keyword_labels(
                    (tag.label for tag in state.accepted_tags),
                    state.free_tags,
                    self._included_embedded_tags(),
                )
            )
            if not preserve_proposals:
                self._pending_proposals_model.set_rows([])
            self._selected_tagging_error = ""
        except Exception as exc:  # noqa: BLE001
            self._accepted_tags_model.set_rows([])
            self._free_tags_model.set_rows([])
            self._derivative_tags_model.set_rows(self._included_embedded_tags())
            if not preserve_proposals:
                self._pending_proposals_model.set_rows([])
            self._selected_tagging_error = str(exc)
        self.taggingStateChanged.emit()

    def _included_embedded_tags(self) -> tuple[str, ...]:
        if self._exclude_all_embedded_tags:
            return ()
        excluded_keys = {label.casefold() for label in self._excluded_embedded_tags}
        return tuple(
            label for label in self._embedded_tags if label.casefold() not in excluded_keys
        )

    def _refresh_embedded_tag_rows(self) -> None:
        excluded_keys = {label.casefold() for label in self._excluded_embedded_tags}
        self._embedded_tags_model.set_rows(
            (label, label.casefold() in excluded_keys) for label in self._embedded_tags
        )

    def _refresh_marked_tagging_state(self) -> None:
        if self._tagging_service is None or not self.tgmInstalled:
            self._marked_tags_model.set_rows([])
            self._marked_tag_total = 0
            self._marked_tagged_total = 0
        else:
            try:
                state = self._tagging_service.get_marked_tagging_state()
                self._marked_tags_model.set_rows(state.concepts)
                self._marked_tag_total = state.total_marked
                self._marked_tagged_total = state.tagged_marked
            except Exception as exc:  # noqa: BLE001
                self._selected_tagging_error = str(exc)
        self.taggingStateChanged.emit()

    @Slot(str)
    def addSelectedTgmConcept(self, concept_reference: str) -> None:
        self._mutate_selected_tag(concept_reference, remove=False)

    @Slot(str)
    def removeSelectedTgmConcept(self, concept_id: str) -> None:
        self._mutate_selected_tag(concept_id, remove=True)

    @Slot(str)
    def addSelectedFreeTag(self, label: str) -> None:
        self._mutate_selected_free_tag(label, remove=False)

    @Slot(str)
    def removeSelectedFreeTag(self, label: str) -> None:
        self._mutate_selected_free_tag(label, remove=True)

    @Slot(str, bool)
    def setSelectedEmbeddedTagExcluded(self, label: str, excluded: bool) -> None:
        path = self._search_model.get_path(self._current_result_row)
        if path is None or self._tagging_service is None or not self.freeTaggingAvailable:
            return
        try:
            self._tagging_service.set_embedded_tag_excluded(path, label, excluded)
            self._selected_tagging_error = ""
            self._refresh_selected_tagging_state(preserve_proposals=True)
        except Exception as exc:  # noqa: BLE001
            self._selected_tagging_error = str(exc)
            self.taggingStateChanged.emit()

    @Slot(bool)
    def setExcludeAllSelectedEmbeddedTags(self, excluded: bool) -> None:
        path = self._search_model.get_path(self._current_result_row)
        if path is None or self._tagging_service is None or not self.freeTaggingAvailable:
            return
        try:
            self._tagging_service.set_all_embedded_tags_excluded(path, excluded)
            self._selected_tagging_error = ""
            self._refresh_selected_tagging_state(preserve_proposals=True)
        except Exception as exc:  # noqa: BLE001
            self._selected_tagging_error = str(exc)
            self.taggingStateChanged.emit()

    def _mutate_selected_free_tag(self, label: str, *, remove: bool) -> None:
        if not self.freeTaggingAvailable:
            return
        path = self._search_model.get_path(self._current_result_row)
        if path is None or self._tagging_service is None:
            return
        try:
            if remove:
                self._tagging_service.remove_free_tag(path, label)
            else:
                self._tagging_service.add_free_tag(path, label)
            self._selected_tagging_error = ""
            self._refresh_after_tag_mutation()
            self.searchFreeTags("")
        except Exception as exc:  # noqa: BLE001
            self._selected_tagging_error = str(exc)
            self.taggingStateChanged.emit()

    def _mutate_selected_tag(self, concept_reference: str, *, remove: bool) -> None:
        if not self.taggingAvailable:
            return
        path = self._search_model.get_path(self._current_result_row)
        if path is None or self._tagging_service is None:
            return
        try:
            if remove:
                self._tagging_service.remove_concept(path, concept_reference)
            else:
                self._tagging_service.add_concept(path, concept_reference)
            self._selected_tagging_error = ""
            self._refresh_after_tag_mutation()
        except Exception as exc:  # noqa: BLE001
            self._selected_tagging_error = str(exc)
            self.taggingStateChanged.emit()

    @Slot(str, str)
    def acceptSelectedProposal(self, concept_id: str, fingerprint: str) -> None:
        if not self.taggingAvailable:
            return
        path = self._search_model.get_path(self._current_result_row)
        if path is None or self._tagging_service is None:
            return
        try:
            proposal = self._pending_proposals_model.find(concept_id, fingerprint)
            if proposal is None or proposal.image_path != path:
                return
            self._tagging_service.accept_proposal(proposal)
            self._pending_proposals_model.remove(proposal)
            self._refresh_after_tag_mutation()
        except Exception as exc:  # noqa: BLE001
            self._selected_tagging_error = str(exc)
            self.taggingStateChanged.emit()

    @Slot(str, str)
    def rejectSelectedProposal(self, concept_id: str, fingerprint: str) -> None:
        if not self.taggingAvailable:
            return
        path = self._search_model.get_path(self._current_result_row)
        if path is None or self._tagging_service is None:
            return
        try:
            proposal = self._pending_proposals_model.find(concept_id, fingerprint)
            if proposal is None or proposal.image_path != path:
                return
            self._tagging_service.reject_proposal(proposal)
            self._pending_proposals_model.remove(proposal)
            self.taggingStateChanged.emit()
        except Exception as exc:  # noqa: BLE001
            self._selected_tagging_error = str(exc)
            self.taggingStateChanged.emit()

    def _refresh_after_tag_mutation(self) -> None:
        self._refresh_selected_tagging_state(preserve_proposals=True)
        self._refresh_marked_tagging_state()
        if self._current_result_row >= 0:
            index = self._search_model.index(self._current_result_row)
            self._search_model.dataChanged.emit(index, index, [])

    @Slot()
    def installOrUpdateTgm(self) -> None:
        if self._repo is None or self._tgm_update_worker is not None:
            return
        worker = TgmUpdateWorker(self._db_path, self._key)
        self._tgm_update_worker = worker
        worker.progress.connect(self._on_tgm_progress)
        worker.result_ready.connect(self._on_tgm_update_result)
        worker.failed.connect(self._on_tgm_failed)
        worker.canceled.connect(self._on_tgm_canceled)
        worker.finished.connect(lambda: self._release_worker("_tgm_update_worker", worker))
        self._tgm_operation = True
        self._tgm_error = ""
        self.tgmOperationChanged.emit()
        worker.start()

    @Slot()
    def rebuildTgmVectors(self) -> None:
        if not self.tgmInstalled or not self._ai_enabled or self._tgm_vector_worker is not None:
            return
        worker = TgmVectorBuildWorker(self._db_path)
        self._tgm_vector_worker = worker
        worker.progress.connect(self._on_tgm_progress)
        worker.result_ready.connect(self._on_tgm_vector_result)
        worker.failed.connect(self._on_tgm_failed)
        worker.canceled.connect(lambda _result: self._on_tgm_canceled())
        worker.finished.connect(lambda: self._release_worker("_tgm_vector_worker", worker))
        self._tgm_operation = True
        self._tgm_error = ""
        self.tgmOperationChanged.emit()
        worker.start()

    def _on_tgm_progress(self, done: int, total: int, _detail: str) -> None:
        self._tgm_progress = (done, total)
        self.tgmOperationChanged.emit()

    def _on_tgm_update_result(self, _result: object) -> None:
        self._tgm_operation = False
        self._initialize_tagging_services()
        self.refreshSelectedTaggingState()
        self._refresh_marked_tagging_state()
        self.tgmOperationChanged.emit()

    def _on_tgm_vector_result(self, _result: object) -> None:
        self._tgm_operation = False
        self._refresh_tgm_status()
        self.tgmOperationChanged.emit()

    def _on_tgm_failed(self, error: str) -> None:
        self._tgm_operation = False
        self._tgm_error = error
        self.tgmOperationChanged.emit()

    def _on_tgm_canceled(self) -> None:
        self._tgm_operation = False
        self.tgmOperationChanged.emit()

    @Slot()
    def cancelTgmOperation(self) -> None:
        worker = self._tgm_vector_worker or self._tgm_update_worker
        if worker is not None:
            worker.cancel()

    @Slot()
    def generateSelectedTagProposals(self) -> None:
        path = self._search_model.get_path(self._current_result_row)
        self._start_proposals([] if path is None else [path], auto_accept=False)

    @Slot()
    def generateMarkedTagProposals(self) -> None:
        paths = self._repo.get_marked_paths() if self._repo is not None else []
        self._start_proposals(paths, auto_accept=False)

    @Slot()
    def autoAcceptMarkedTagProposals(self) -> None:
        paths = self._repo.get_marked_paths() if self._repo is not None else []
        self._start_proposals(paths, auto_accept=True)

    def _start_proposals(self, paths: list[str], *, auto_accept: bool) -> None:
        if not paths or not self.taggingProposalAvailable or self._proposal_worker is not None:
            return
        assert self._settings is not None
        worker = TgmProposalWorker(
            self._db_path,
            self._key,
            paths,
            threshold=self._settings.proposal_threshold,
            auto_accept_threshold=self._settings.auto_accept_threshold if auto_accept else None,
        )
        self._proposal_worker = worker
        worker.progress.connect(self._on_proposal_progress)
        worker.result_ready.connect(self._on_proposal_result)
        worker.failed.connect(self._on_proposal_failed)
        worker.canceled.connect(lambda _result: self._on_proposal_canceled())
        worker.finished.connect(lambda: self._release_worker("_proposal_worker", worker))
        self._proposal_operation = True
        self._proposal_error = ""
        if not auto_accept:
            self._pending_proposals_model.set_rows([])
        self.proposalOperationChanged.emit()
        worker.start()

    def _on_proposal_progress(self, done: int, total: int, _detail: str) -> None:
        self._proposal_progress = (done, total)
        self.proposalOperationChanged.emit()

    def _on_proposal_result(self, result: object, _bulk_result: object) -> None:
        self._proposal_operation = False
        selected_path = self._search_model.get_path(self._current_result_row)
        matching_result = next(
            (
                item
                for item in getattr(result, "results", ())
                if getattr(item, "image_path", None) == selected_path
            ),
            None,
        )
        self._pending_proposals_model.set_rows(
            () if matching_result is None else matching_result.proposals
        )
        self._refresh_selected_tagging_state(preserve_proposals=True)
        self.proposalOperationChanged.emit()

    def _on_proposal_failed(self, error: str) -> None:
        self._proposal_operation = False
        self._proposal_error = error
        self.proposalOperationChanged.emit()

    def _on_proposal_canceled(self) -> None:
        self._proposal_operation = False
        self.proposalOperationChanged.emit()

    @Slot()
    def cancelTagProposalGeneration(self) -> None:
        if self._proposal_worker is not None:
            self._proposal_worker.cancel()

    @Slot(str)
    def applyConceptToMarked(self, concept_reference: str) -> None:
        self._start_bulk_tag("add", concept_reference)

    @Slot(str)
    def removeConceptFromMarked(self, concept_id: str) -> None:
        self._start_bulk_tag("remove", concept_id)

    @Slot(str, str)
    def copySelectedTags(self, target_scope: str, mode: str) -> None:
        source_path = self._search_model.get_path(self._current_result_row)
        if (
            source_path is None
            or not self.freeTaggingAvailable
            or self._repo is None
            or self._copy_tags_worker is not None
            or self._bulk_tag_worker is not None
        ):
            return
        if mode not in {"add", "replace"}:
            self._bulk_tag_summary = _("Choose whether to add or replace tags.")
            self.bulkTagOperationChanged.emit()
            return
        worker_kwargs: dict[str, object] = {}
        if target_scope == "marked":
            worker_kwargs = {
                "marked_only": True,
                "restrict_to_enabled_folders": self._folder_repo is not None,
            }
        elif target_scope in {"results", "folder"}:
            if target_scope == "folder" and not self._folder_filter:
                self._bulk_tag_summary = _("Choose a folder in Browse first.")
                self.bulkTagOperationChanged.emit()
                return
            if self._results_use_ai_pipeline():
                worker_kwargs = {
                    "image_paths": [result.path for result in self._ai_result_cache]
                }
            else:
                worker_kwargs = {
                    "query": self._query_text,
                    "ext_filter": self._ext_filter,
                    "path_filter": self._current_path_filter(),
                    "restrict_to_enabled_folders": self._folder_repo is not None,
                    "date_from": self._date_from,
                    "date_to": self._date_to,
                }
        else:
            self._bulk_tag_summary = _("Choose a valid copy target.")
            self.bulkTagOperationChanged.emit()
            return
        worker = CopyTagsWorker(
            self._db_path,
            self._key,
            source_path,
            mode,
            **worker_kwargs,
        )
        self._copy_tags_worker = worker
        worker.progress.connect(self._on_bulk_tag_progress)
        worker.result_ready.connect(self._on_bulk_tag_result)
        worker.failed.connect(self._on_bulk_tag_failed)
        worker.canceled.connect(self._on_bulk_tag_result)
        worker.finished.connect(lambda: self._release_worker("_copy_tags_worker", worker))
        self._bulk_tag_operation = True
        self._bulk_tag_progress = (0, 0)
        self._bulk_tag_summary = ""
        self._bulk_tag_action = f"copy_{mode}"
        self.bulkTagOperationChanged.emit()
        worker.start()

    def _start_bulk_tag(self, operation: str, concept_reference: str) -> None:
        if (
            not self.taggingAvailable
            or self._repo is None
            or self._bulk_tag_worker is not None
        ):
            return
        worker = BulkTagWorker(self._db_path, self._key, operation, concept_reference)
        self._bulk_tag_worker = worker
        worker.progress.connect(self._on_bulk_tag_progress)
        worker.result_ready.connect(self._on_bulk_tag_result)
        worker.failed.connect(self._on_bulk_tag_failed)
        worker.canceled.connect(self._on_bulk_tag_result)
        worker.finished.connect(lambda: self._release_worker("_bulk_tag_worker", worker))
        self._bulk_tag_operation = True
        self._bulk_tag_summary = ""
        self._bulk_tag_action = operation
        self.bulkTagOperationChanged.emit()
        worker.start()

    def _on_bulk_tag_progress(self, done: int, total: int, _item: object) -> None:
        self._bulk_tag_progress = (done, total)
        self.bulkTagOperationChanged.emit()

    def _on_bulk_tag_result(self, result: object) -> None:
        self._bulk_tag_operation = False
        changed_count = getattr(result, "succeeded_count", 0)
        unchanged_count = getattr(result, "skipped_count", 0)
        problem_count = (
            getattr(result, "conflicted_count", 0)
            + getattr(result, "failed_count", 0)
        )
        if self._bulk_tag_action == "remove":
            summary = _("Removed from {} image(s). Already absent: {}. Problems: {}.").format(
                changed_count, unchanged_count, problem_count
            )
        elif self._bulk_tag_action.startswith("copy_"):
            summary = _("Copied tags to {} image(s). Unchanged: {}. Problems: {}.").format(
                changed_count, unchanged_count, problem_count
            )
        else:
            summary = _("Added to {} image(s). Already tagged: {}. Problems: {}.").format(
                changed_count, unchanged_count, problem_count
            )
        if getattr(result, "cancelled", False):
            summary = _("Canceled. {}").format(summary)
        self._bulk_tag_summary = summary.strip()
        self._refresh_after_tag_mutation()
        self.bulkTagOperationChanged.emit()

    def _on_bulk_tag_failed(self, error: str) -> None:
        self._bulk_tag_operation = False
        self._bulk_tag_summary = error
        self.bulkTagOperationChanged.emit()

    @Slot()
    def cancelBulkTagging(self) -> None:
        worker = self._copy_tags_worker or self._bulk_tag_worker
        if worker is not None:
            worker.cancel()

    @Slot(str)
    def generateDerivativesForMarked(self, output_url: str) -> None:
        self._start_derivative_export(output_url)

    @Slot(str)
    def generateDerivativesForCurrentResults(self, output_url: str) -> None:
        if self._results_use_ai_pipeline():
            self._start_derivative_export(
                output_url,
                image_paths=[result.path for result in self._ai_result_cache],
            )
            return
        self._start_derivative_export(
            output_url,
            matching_results=True,
            query=self._query_text,
            ext_filter=self._ext_filter,
            path_filter=self._current_path_filter(),
            restrict_to_enabled_folders=self._folder_repo is not None,
            marked_only=self._checked_only_filter_active,
            date_from=self._date_from,
            date_to=self._date_to,
        )

    def _start_derivative_export(
        self,
        output_url: str,
        **worker_options: object,
    ) -> None:
        if (
            not self.freeTaggingAvailable
            or self._folder_repo is None
            or self._derivative_worker is not None
        ):
            return
        output_root = Path(QUrl(output_url).toLocalFile())
        roots = {
            Path(folder.path): folder.display_name
            for folder in self._folder_repo.get_all()
        }
        worker = DerivativeExportWorker(
            self._db_path,
            self._key,
            roots,
            output_root,
            **worker_options,
        )
        self._derivative_worker = worker
        worker.progress.connect(self._on_derivative_progress)
        worker.result_ready.connect(self._on_derivative_result)
        worker.canceled.connect(self._on_derivative_result)
        worker.failed.connect(self._on_derivative_failed)
        worker.finished.connect(lambda: self._release_worker("_derivative_worker", worker))
        self._derivative_operation = True
        self._derivative_summary = ""
        self.derivativeOperationChanged.emit()
        worker.start()

    def _on_derivative_progress(self, done: int, total: int, _item: object) -> None:
        self._derivative_progress = (done, total)
        self.derivativeOperationChanged.emit()

    def _on_derivative_result(self, result: object) -> None:
        self._derivative_operation = False
        copied_count = getattr(result, "copied_count", 0)
        untagged_count = getattr(result, "skipped_untagged_count", 0)
        existing_count = getattr(result, "skipped_existing_count", 0)
        failed_count = getattr(result, "failed_count", 0)
        canceled_count = getattr(result, "canceled_count", 0)
        items = getattr(result, "items", ())
        copied_destinations = [
            str(item.destination)
            for item in items
            if getattr(getattr(item, "status", None), "value", None) == "copied"
        ]
        parts = []
        if copied_count == 1 and copied_destinations:
            parts.append(_("Created derivative: {}").format(copied_destinations[0]))
        elif copied_count == 1:
            parts.append(_("Created 1 derivative."))
        elif copied_count and copied_destinations:
            common_destination = os.path.commonpath(copied_destinations)
            parts.append(
                _("Created {} derivatives in {}.").format(
                    copied_count, common_destination
                )
            )
        elif copied_count:
            parts.append(_("Created {} derivatives.").format(copied_count))
        else:
            parts.append(_("No derivatives were created."))
        if untagged_count:
            parts.append(
                _("{} image(s) had no accepted tags.").format(untagged_count)
            )
        if existing_count:
            parts.append(
                _("{} destination file(s) already existed.").format(existing_count)
            )
        if failed_count:
            parts.append(_("{} derivative(s) failed.").format(failed_count))
            failed_item = next(
                (
                    item
                    for item in items
                    if getattr(getattr(item, "status", None), "value", None)
                    == "failed"
                ),
                None,
            )
            if failed_item is not None:
                source_name = Path(str(getattr(failed_item, "source", ""))).name
                detail = str(getattr(failed_item, "message", "") or "unknown error")
                parts.append(
                    _("First failure ({}): {}").format(source_name, detail)
                )
        if canceled_count:
            parts.append(_("{} derivative(s) canceled.").format(canceled_count))
        self._derivative_summary = " ".join(parts)
        self.derivativeOperationChanged.emit()

    def _on_derivative_failed(self, error: str) -> None:
        self._derivative_operation = False
        self._derivative_summary = error
        self.derivativeOperationChanged.emit()

    @Slot()
    def cancelDerivativeExport(self) -> None:
        if self._derivative_worker is not None:
            self._derivative_worker.cancel()

    def _release_worker(self, attribute: str, worker: QThread) -> None:
        if getattr(self, attribute) is worker:
            setattr(self, attribute, None)

    def _cancel_tagging_workers(self, *, wait: bool) -> None:
        for worker in (
            self._tgm_update_worker,
            self._tgm_vector_worker,
            self._proposal_worker,
            self._bulk_tag_worker,
            self._copy_tags_worker,
            self._derivative_worker,
        ):
            if worker is not None and worker.isRunning():
                worker.cancel()
                if wait:
                    worker.wait(5000)

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
            self._warn_unavailable(path)
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
            self._warn_unavailable(path)
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

    def _set_status(self, text: str, *, error: bool = False) -> None:
        if self._status_text != text or self._status_is_error != error:
            self._status_text = text
            self._status_is_error = error
            self.statusTextChanged.emit()

    @Slot()
    def clearStatus(self) -> None:
        self._set_status("")

    def _clear_status_for_primary_action(self) -> None:
        if not self._status_text:
            return
        self._set_status("")

    def _expected_data_source(self, path: str) -> str:
        """Return the indexed-folder root that should contain *path*, or "".

        When an indexed file cannot be opened because its original location is
        unavailable, this points the user at the folder they need to (re)attach
        or mount.  The longest matching indexed-folder root wins so nested
        folders are reported precisely.  Returns "" when no managed folder
        covers *path* (so we never guess a path the app does not know).
        """
        if self._folder_repo is None:
            return ""
        try:
            target = os.path.normcase(os.path.normpath(path))
        except (OSError, ValueError):
            return ""
        best_root = ""
        best_len = -1
        for folder in self._folder_repo.get_all():
            root_raw = os.path.normpath(folder.path)
            root = os.path.normcase(root_raw)
            try:
                common = os.path.commonpath([root, target])
            except ValueError:
                # Different drives / unrelated roots (e.g. C: vs D: on Windows).
                continue
            if common == root and len(root) > best_len:
                best_root = root_raw
                best_len = len(root)
        return best_root

    def _warn_unavailable(self, path: str) -> None:
        """Show a red status-bar warning for an unavailable indexed file.

        If the file belongs to a known indexed folder, hint which data source
        to attach; otherwise fall back to a plain file-not-found message.
        """
        source = self._expected_data_source(path)
        if source:
            self._set_status(
                _(
                    "Original data source not attached: {source} — "
                    "attach or mount this folder to open files."
                ).format(source=source),
                error=True,
            )
        else:
            self._set_status(
                _("File not found: {}").format(Path(path).name),
                error=True,
            )

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
        self._embedded_tags = ()
        self._excluded_embedded_tags = ()
        self._exclude_all_embedded_tags = False
        self._embedded_tags_model.set_rows([])
        self._derivative_tags_model.set_rows([])
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
                self._embedded_tags = extract_embedded_keyword_labels(parsed)
                self._refresh_embedded_tag_rows()
                self._derivative_tags_model.set_rows(self._embedded_tags)
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
        self._embedded_tags = ()
        self._excluded_embedded_tags = ()
        self._exclude_all_embedded_tags = False
        self._embedded_tags_model.set_rows([])
        self._derivative_tags_model.set_rows([])
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
            scheme = "raw" if (self._use_raw_preview and os.path.exists(path)) else "preview"
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
            self._maint_worker,
            self._tgm_update_worker,
            self._tgm_vector_worker,
            self._proposal_worker,
            self._bulk_tag_worker,
            self._derivative_worker,
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
        self._maint_worker = None
        self._tgm_update_worker = None
        self._tgm_vector_worker = None
        self._proposal_worker = None
        self._bulk_tag_worker = None
        self._copy_tags_worker = None
        self._derivative_worker = None
        self._tagging_service = None
        self._tgm_repository = None

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
