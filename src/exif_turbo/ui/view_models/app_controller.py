from __future__ import annotations

import html as html_lib
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import List, Tuple

import sqlcipher3
from PySide6.QtCore import Property, QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ...data.image_index_repository import ImageIndexRepository
from ...data.indexed_folder_repository import IndexedFolderRepository
from ...i18n import _
from ...indexing.image_utils import RAW_EXTENSIONS
from ...models.search_result import SearchResult
from ..models.exif_list_model import ExifListModel
from ..models.folder_list_model import FolderListModel
from ..models.search_list_model import SearchListModel
from ..models.settings_model import SettingsModel
from ..workers.index_worker import IndexWorker
from ..workers.thumb_worker import ThumbWorker

_PAGE_SIZE = 10
_DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) // 2)
_log = logging.getLogger(__name__)


class AppController(QObject):
    statusTextChanged = Signal()
    isIndexingChanged = Signal()
    isBuildingThumbsChanged = Signal()
    isCancelingChanged = Signal()
    detailsHtmlChanged = Signal()
    findScrollFractionChanged = Signal()
    selectedImageSourceChanged = Signal()
    selectedThumbSourceChanged = Signal()
    totalResultsChanged = Signal()
    loadedResultsChanged = Signal()
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
    indexedFoldersChanged = Signal()
    indexQueuePositionChanged = Signal()
    indexQueueTotalChanged = Signal()

    def __init__(
        self,
        db_path: Path,
        search_model: SearchListModel,
        exif_model: ExifListModel,
        folder_model: FolderListModel,
        settings: SettingsModel | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._settings = settings
        self._cache_dir = cache_dir
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
        self._find_scroll_fraction = 0.0
        self._selected_image_source = ""
        self._selected_thumb_source = ""
        self._current_result_row: int = -1
        self._total_results = 0
        self._loaded_results = 0
        self._loading = False
        self._details_plain_text = ""
        self._query_text = ""
        self._find_text = ""
        self._find_positions: List[Tuple[int, int]] = []
        self._find_index = -1
        self._sort_by = "path_asc"
        self._ext_filter = ""
        self._available_formats: str = "[]"
        self._folder_filter: str = ""
        self._folder_tree: str = "[]"
        self._folder_tree_dirty: bool = False
        self._pending_preview_path: str = ""
        self._index_worker: IndexWorker | None = None
        self._thumb_worker: ThumbWorker | None = None
        self._scanning_folder_id: int | None = None
        self._scan_queue: list[tuple[int, bool]] = []
        self._index_queue_position = 0
        self._index_queue_total = 0
        self._app_closing = False
        self._pending_thumb_restart = False
        # Timer: kick off a batch thumb build every 8 s while indexing runs
        self._thumb_batch_timer = QTimer(self)
        self._thumb_batch_timer.setInterval(8_000)
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

    @Property(bool, notify=isCancelingChanged)
    def isCanceling(self) -> bool:
        return self._is_canceling

    @Property(str, notify=detailsHtmlChanged)
    def detailsHtml(self) -> str:
        return self._details_html

    @Property(float, notify=findScrollFractionChanged)
    def findScrollFraction(self) -> float:
        return self._find_scroll_fraction

    @Property(str, notify=selectedImageSourceChanged)
    def selectedImageSource(self) -> str:
        return self._selected_image_source

    @Property(str, notify=selectedThumbSourceChanged)
    def selectedThumbSource(self) -> str:
        return self._selected_thumb_source

    @Property(int, notify=currentResultRowChanged)
    def currentResultRow(self) -> int:
        return self._current_result_row

    @Property(int, notify=totalResultsChanged)
    def totalResults(self) -> int:
        return self._total_results

    @Property(int, notify=loadedResultsChanged)
    def loadedResults(self) -> int:
        return self._loaded_results

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

    @Property(str, notify=folderTreeChanged)
    def folderTree(self) -> str:
        return self._folder_tree

    @Property(int, notify=indexQueuePositionChanged)
    def indexQueuePosition(self) -> int:
        return self._index_queue_position

    @Property(int, notify=indexQueueTotalChanged)
    def indexQueueTotal(self) -> int:
        return self._index_queue_total

    # ── Slots ─────────────────────────────────────────────────────────────────

    @Slot(str)
    def unlock(self, password: str) -> None:
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
            self._sort_by = "path_asc"
            self._folder_filter = ""
            self._status_text = ""
            self.isLockedChanged.emit()
            self.unlockErrorChanged.emit()
            self.statusTextChanged.emit()
            self._load_formats()
            self._folder_tree_dirty = True  # loaded on demand when Browse tab is opened
            self._load_indexed_folders()
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
            self._unlock_error = "Wrong password — please try again."
            self.unlockErrorChanged.emit()
            if repo is not None:
                repo.close()
            if folder_repo is not None:
                folder_repo.close()
            # Ensure self refs never point to closed connections
            self._repo = None
            self._folder_repo = None
            self._is_locked = True
        except Exception as exc:
            self._unlock_error = f"Failed to open database: {exc}"
            self.unlockErrorChanged.emit()
            if repo is not None:
                repo.close()
            if folder_repo is not None:
                folder_repo.close()
            # Ensure self refs never point to closed connections
            self._repo = None
            self._folder_repo = None
            self._is_locked = True

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
        self._run_search()

    @Slot(str)
    def setFolderFilter(self, path: str) -> None:
        if self._folder_filter == path:
            return
        self._folder_filter = path
        self._current_result_row = 0
        self.folderFilterChanged.emit()
        self._run_search()

    @Slot(str)
    def browseFolder(self, path: str) -> None:
        """Navigate to a folder in the Browse tab.

        Clears any active search query so the full folder contents are shown.
        Clicking the already-selected folder clears the filter.
        """
        if self._folder_filter == path:
            self._folder_filter = ""
        else:
            self._query_text = ""
            self._folder_filter = path
        self.folderFilterChanged.emit()
        self._run_search()

    def _run_search(self) -> None:
        if self._repo is None:
            return
        excluded = (
            self._folder_repo.get_disabled_paths() if self._folder_repo else None
        )
        rows = self._repo.search_images(
            self._query_text, _PAGE_SIZE, 0,
            sort_by=self._sort_by, ext_filter=self._ext_filter,
            path_filter=self._folder_filter,
            excluded_paths=excluded or None,
        )
        results = [
            SearchResult(path=r[1], filename=r[2], metadata_json=r[3], size=r[4], mtime=r[5])
            for r in rows
        ]
        self._search_model.set_rows(results)
        total = self._repo.count_images(
            self._query_text, ext_filter=self._ext_filter,
            path_filter=self._folder_filter,
            excluded_paths=excluded or None,
        )
        self._total_results = total
        self._loaded_results = len(results)
        self._loading = False
        self.totalResultsChanged.emit()
        self.loadedResultsChanged.emit()
        self._load_formats(
            query=self._query_text,
            path_filter=self._folder_filter,
            excluded_paths=excluded or None,
        )
        if results:
            row = self._current_result_row if 0 <= self._current_result_row < len(results) else 0
            self.selectResult(row)
        else:
            self._clear_details()

    def _load_formats(
        self,
        query: str = "",
        path_filter: str = "",
        excluded_paths: list[str] | None = None,
    ) -> None:
        if self._repo is None:
            return
        import json as _json
        counts = self._repo.get_format_counts(
            query=query,
            path_filter=path_filter,
            excluded_paths=excluded_paths,
        )
        self._available_formats = _json.dumps(
            [{"ext": ext, "count": cnt} for ext, cnt in counts]
        )
        self.availableFormatsChanged.emit()

    def _invalidate_folder_tree(self) -> None:
        """Mark the folder tree as stale; it will be rebuilt on next Browse tab visit."""
        self._folder_tree_dirty = True

    @Slot()
    def loadFolderTree(self) -> None:
        """Load (or reload) the folder tree — called by QML when Browse tab is activated."""
        if self._repo is None or not self._folder_tree_dirty:
            return
        nodes = self._repo.get_folder_tree()
        self._folder_tree = json.dumps(nodes)
        self._folder_tree_dirty = False
        self.folderTreeChanged.emit()

    def _load_folder_tree(self) -> None:
        if self._repo is None:
            return
        nodes = self._repo.get_folder_tree()
        self._folder_tree = json.dumps(nodes)
        self.folderTreeChanged.emit()

    @Slot()
    def loadMore(self) -> None:
        if self._repo is None or self._loading or self._loaded_results >= self._total_results:
            return
        self._loading = True
        excluded = (
            self._folder_repo.get_disabled_paths() if self._folder_repo else None
        )
        rows = self._repo.search_images(
            self._query_text, _PAGE_SIZE, self._loaded_results,
            sort_by=self._sort_by, ext_filter=self._ext_filter,
            path_filter=self._folder_filter,
            excluded_paths=excluded or None,
        )
        results = [
            SearchResult(path=r[1], filename=r[2], metadata_json=r[3], size=r[4], mtime=r[5])
            for r in rows
        ]
        self._search_model.append_rows(results)
        self._loaded_results += len(results)
        self.loadedResultsChanged.emit()
        self._loading = False

    @Slot(int)
    def selectResult(self, row: int) -> None:
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
        self._update_find_scroll()
        self._update_details_html()

    @Slot(str)
    def findPrev(self, find_text: str) -> None:
        if find_text != self._find_text:
            self._find_text = find_text
            self._find_positions = self._find_all(self._details_plain_text, find_text)
            self._find_index = len(self._find_positions)
        if not self._find_positions:
            return
        self._find_index = (self._find_index - 1) % len(self._find_positions)
        self._update_find_scroll()
        self._update_details_html()

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
        self._folder_repo.remove(folder_id)
        self._folder_model.remove_folder(folder_id)
        self._repo.delete_by_path_prefix(folder.path)
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
        self.indexedFoldersChanged.emit()

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
        # Cancel any thumb worker that is still running (e.g. the one started at
        # unlock time).  A definitive build will be triggered after indexing
        # finishes, so there is no value in letting the two workers race.
        if self._thumb_worker and self._thumb_worker.isRunning():
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
            clear_cache_dir=self._search_model.cache_dir if force else None,
            blacklist=self._settings.blacklist_patterns if self._settings else [],
        )
        self._index_worker.finished.connect(self._on_managed_folder_index_done)
        self._index_worker.failed.connect(self._on_managed_folder_index_failed)
        self._index_worker.progress.connect(self._on_index_progress)
        self._index_worker.canceled.connect(self._on_managed_folder_index_canceled)
        # Run below normal priority so the GUI and preview thread get preference.
        self._index_worker.start(QThread.Priority.LowPriority)
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
        self._scan_queue.clear()

    @Slot()
    def cancelThumbnails(self) -> None:
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.cancel()

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
    def openImage(self, path: str) -> None:
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def openFolder(self, path: str) -> None:
        if not path:
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ── Private helpers ───────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        if self._status_text != text:
            self._status_text = text
            self.statusTextChanged.emit()

    def _clear_details(self) -> None:
        self._preview_delay_timer.stop()
        self._pending_preview_path = ""
        self._details_plain_text = ""
        self._details_html = ""
        self.detailsHtmlChanged.emit()
        self._exif_model.set_rows([])
        self._selected_image_source = ""
        self._selected_thumb_source = ""
        self._current_result_row = -1
        self.selectedImageSourceChanged.emit()
        self.selectedThumbSourceChanged.emit()
        self.currentResultRowChanged.emit()

    def _update_exif_table(self, meta_json: str) -> None:
        try:
            parsed = json.loads(meta_json)
            if isinstance(parsed, dict):
                rows = sorted(
                    [(str(k), str(v)) for k, v in parsed.items()],
                    key=lambda r: r[0].lower(),
                )
                self._exif_model.set_rows(rows)
                return
        except Exception:
            pass
        self._exif_model.set_rows([])

    def _update_details_html(self) -> None:
        text = self._details_plain_text
        ranges: List[Tuple[int, int, str]] = []
        if self._query_text:
            for s, e in self._find_all(text, self._query_text):
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
        # Throttle UI updates to at most ~10 Hz — prevents flooding the event loop
        # on large folders with thousands of files.
        now = time.monotonic()
        if now - self._last_progress_update < 0.1 and current != total:
            return
        self._last_progress_update = now
        self._index_current = current
        self._index_total = total
        self._index_current_file = Path(path).name if path else ""
        self.indexCurrentChanged.emit()
        self.indexTotalChanged.emit()
        self.indexCurrentFileChanged.emit()
        self._set_status(_("Indexing\u2026 {} / {}").format(current, total))

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
            self._search_model.max_thumb_bytes,
            workers=self._settings.workerCount if self._settings else _DEFAULT_WORKERS,
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
            encoded = urllib.parse.quote(path, safe="")
            self._selected_image_source = f"image://preview/{encoded}"
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

    def _on_thumb_refresh_tick(self) -> None:
        """Periodic mid-batch refresh so thumbnails appear as they are written."""
        if self._is_building_thumbs:
            self._search_model.refresh_thumbnails()

    def _on_thumb_done(self, cached: int, total: int) -> None:
        self._thumb_refresh_timer.stop()
        self._is_building_thumbs = False
        self.isBuildingThumbsChanged.emit()
        self._search_model.refresh_thumbnails()
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

    def close(self) -> None:
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
            parts.append(f'<span style="background-color:{color}">')
            parts.append(html_lib.escape(text[start:end]))
            parts.append("</span>")
            last = end
        parts.append(html_lib.escape(text[last:]))
        parts.append("</pre>")
        return "".join(parts)
