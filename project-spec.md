# exif-turbo — Project Specification

## 1. Overview

**exif-turbo** is a cross-platform desktop application and CLI tool for indexing and searching image EXIF metadata. It scans one or more folders, extracts metadata from every image using ExifTool, stores it in an encrypted SQLite database, and exposes the full corpus via SQLite FTS5 full-text search. A PySide6 QML UI provides real-time search, thumbnail preview, and browsing.

---

## 2. Goals

| Goal | Description |
|------|-------------|
| **Speed** | Index large photo libraries (10k+ images) with parallel extraction; search results are instant via FTS5 |
| **Completeness** | All EXIF/IPTC/XMP metadata captured; keys stored as `Group:Key` (ExifTool `-g1` format) |
| **Offline / private** | No cloud; database is encrypted at rest (SQLCipher) and stays on the user's machine |
| **Cross-platform** | Windows and macOS first-class; Linux supported from source |
| **Portable distribution** | Single-file MSI installer (Windows) and DMG (macOS) with no Python dependency |

---

## 3. Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| UI framework | PySide6 6.5+ — QML / Qt Quick / Material Design |
| Database | SQLCipher 3 (`sqlcipher3` 0.5+) — encrypted SQLite with WAL mode |
| Full-text search | SQLite FTS5 virtual table |
| EXIF extraction | ExifTool (external process, `-g1 -j` JSON output) |
| Thumbnails | Pillow ≥10.0 + `ImageOps.exif_transpose` (JPEG/PNG/TIFF) |
| RAW thumbnails | rawpy 0.18+ → libraw (CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF, RWL, SRW) |
| Video thumbnails / previews | PyAV 12+ → FFmpeg (MP4, MOV, AVI, MKV, WMV, M4V, MTS, M2TS, 3GP, WebM, FLV); embedded thumbnail when present, otherwise a frame at 1/3 of the duration; rotation from `rotate` tag or QuickTime `tkhd` display matrix |
| Type checking | mypy strict |
| Testing | pytest |
| Packaging | PyInstaller (onedir) + WiX v6 (Windows MSI, bundles ExifTool) + hdiutil (macOS DMG) |

---

## 4. Architecture

Ports & adapters (hexagonal) structure. Domain logic has no dependency on PySide6.

```
┌─────────────────────────────────────────────────────────┐
│  UI Layer (PySide6 / QML)                               │
│  AppController · SearchListModel · ExifListModel        │
│  PreviewImageProvider · RawImageProvider                │
│  IndexWorker · ThumbWorker                              │
└───────────────────┬─────────────────────────────────────┘
                    │ Slots / Signals
┌───────────────────▼─────────────────────────────────────┐
│  Domain / Application Layer                             │
│  IndexerService · ImageFinder · ExifMetadataExtractor   │
│  MetadataExtractor (protocol)                           │
└───────────────────┬─────────────────────────────────────┘
                    │ Repository interface
┌───────────────────▼─────────────────────────────────────┐
│  Data Layer                                             │
│  ImageIndexRepository (SQLCipher)                       │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Module Reference

### 5.1 `src/exif_turbo/`

| Module | Purpose |
|--------|---------|
| `__init__.py` | Package init; single source of truth for `__version__` |
| `app.py` | GUI entry point — imports and re-exports `ui.app_main.main` |
| `index.py` | CLI entry point — imports `indexing.cli.main` |
| `config.py` | `AppConfig` dataclass; reads env vars; `default_db_path()`, `thumb_cache_dir()` |
| `db.py` | Low-level DB helpers |
| `indexer.py` | Convenience re-exports for the indexing sub-package |

### 5.2 `data/`

| Module | Purpose |
|--------|---------|
| `image_index_repository.py` | `ImageIndexRepository` — all DB access. Schema: `images` table (with `marked` and `captured_at` columns) + `images_fts` FTS5 virtual table. Encrypted via SQLCipher. Key methods: `upsert_image`, `search_fts`, `delete_missing(existing_paths, folder_roots=None)` (scoped delete), `clear_all()` (drops + recreates FTS5 table, VACUUM, WAL checkpoint), `get_matching_paths(query, ...)` (returns paths matching current filter for bulk mark ops), `get_marked_paths()` (returns paths of all marked images), `get_marked_metadata(sort_by="captured_desc")` (returns export records for all marked images ordered by `sort_by`), `mark_images(paths, value)`, `clear_all_marks()`, `get_year_counts(query, ext_filter, path_filter, restrict_to_enabled_folders)` (returns `[(year, count)]` for the histogram). `search_images`, `count_images`, and `get_matching_paths` all accept `date_from: int | None` and `date_to: int | None` (UTC epoch seconds); when set, only images with a non-NULL `captured_at` in range are returned. |
| `indexed_folder_repository.py` | `IndexedFolderRepository` — manages the set of user-added folders: add, remove, enable/disable, status updates. `clear_all()` deletes all folder records. |

**Schema:**

```sql
CREATE TABLE images (
    id            INTEGER PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,
    filename      TEXT NOT NULL,
    mtime         REAL NOT NULL,
    size          INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    marked        INTEGER NOT NULL DEFAULT 0,
    captured_at   INTEGER           -- UTC epoch seconds; NULL when unknown
);

CREATE INDEX idx_images_captured_at ON images (captured_at);

CREATE VIRTUAL TABLE images_fts
USING fts5(path, filename, metadata_text);
```

### 5.3 `indexing/`

| Module | Purpose |
|--------|---------|
| `cli.py` | `argparse` CLI adapter; entry point for `exif-turbo-index` |
| `image_finder.py` | `ImageFinder` — walks folders, yields `(path, mtime, size)` tuples. On POSIX (macOS/Linux) spawns up to 8 parallel `find` subprocesses (one per top-level subdirectory) via a `ThreadPoolExecutor` + shared `queue.Queue`, streaming results live as discovery runs — avoids Python GIL starvation caused by per-entry `lstat()` on macOS SMB mounts. On Windows uses `os.walk()` (SMB returns file attributes inline). Honours `AppConfig.skip_dotfiles` and a per-instance blacklist. |
| `exif_metadata_extractor.py` | `ExifMetadataExtractor` — runs `exiftool -g1 -j`; parses JSON output. `is_exiftool_available() -> bool` and `get_exiftool_version() -> str` probe for a working ExifTool via `_find_exiftool()`, which checks: (1) augmented `PATH` (adds macOS/Windows well-known install locations); (2) on Windows frozen bundles only, the bundled copy at `Path(sys.executable).parent / "exiftool" / "exiftool.exe"`; returning `False` / `""` if not found or if the process exits non-zero. |
| `metadata_extractor.py` | `MetadataExtractor` protocol (port) |
| `indexer_service.py` | `IndexerService` — orchestrates scan → extract → upsert; supports parallel workers, incremental updates (mtime/size stamps), force-rebuild, progress callback, cancel. Module-level `_resolve_captured_at(metadata, path, mtime)` resolves the capture timestamp: tries EXIF keys `ExifIFD:DateTimeOriginal`, `ExifIFD:CreateDate`, `IFD0:DateTimeOriginal`, `IFD0:CreateDate`, `Composite:SubSecDateTimeOriginal` in order (sub-second suffix stripped); falls back to `st_birthtime` (macOS), `st_ctime` on Windows, or `mtime` on Linux. |
| `image_utils.py` | Image file type helpers. Defines `RAW_EXTENSIONS`, `VIDEO_EXTENSIONS`, `IMAGE_EXTENSIONS` (union of stills + RAW + video), `is_image_file()`, `is_video_file()`. RAW orientation helper `orient_raw_thumb()` maps `rawpy.RawPy.sizes.flip` → Pillow transpose ops. |

**Incremental indexing:** On each run, `IndexerService` compares `(mtime, size)` against DB-stored stamps. Only new or modified files are re-extracted. `force=True` clears all and rebuilds. After scanning, `delete_missing(existing_paths, folder_roots=[...])` removes stale records scoped to the rescanned folder roots — records from other folders are not affected.

### 5.4 `models/`

| Model | Fields |
|-------|--------|
| `IndexedImage` | `path`, `filename`, `mtime`, `size`, `metadata: dict[str, str]`, `captured_at: float \| None` |
| `SearchResult` | `path`, `filename`, `metadata_json`, `size`, `mtime` |
| `IndexedFolder` | `id`, `path`, `display_name`, `status`, `image_count`, `error_message`, `enabled` |

`SearchResult.mtime` is populated from the DB-stored stamp so the UI can
derive stable thumbnail cache names without a live `os.stat` call.

### 5.5 `ui/`

| Module | Purpose |
|--------|---------|
| `app_main.py` | `main()` — bootstraps `QGuiApplication`, sets Material style, registers `PreviewImageProvider` (`image://preview/`) and `RawImageProvider` (`image://raw/`), loads `Main.qml`. Sets `PIL.Image.MAX_IMAGE_PIXELS = 894_784_850` (10× Pillow default) at startup so large panoramas and high-resolution TIFFs load without a `DecompressionBombWarning`. |
| `view_models/app_controller.py` | `AppController(QObject)` — all business logic exposed to QML via `Q_PROPERTY`, `Signal`, `Slot`. Accepts `cache_dir: Path | None` for thumbnail cache management. **Clipboard copy**: `copyPreviewToClipboard()` slot renders the current preview via `render_preview()`, converts it to RGBA `QImage`, and sets it on `QGuiApplication.clipboard()`; emits `clipboardCopyDone(message)` on success or falls back to copying the file path as text. `resetDatabase()` slot calls `clear_all()` on both repositories, removes the thumbnail cache directory, and resets all UI models. Multi-folder filter: `searchFolderListJson` property (JSON list of `{path, name}`), `toggleSearchFolderFilter(path)` / `clearSearchFolderFilters()` slots, `searchFolderFilters` property (JSON array of selected paths). The filter is applied to `search_images`, `count_images`, and `get_format_counts` via `path_filter` parameter. **ExifTool availability**: `exiftoolMissing` bool property + `exiftoolVersion` string property (both exposed to QML); populated via `get_exiftool_version()` at unlock time. `checkExiftool()` slot re-probes on demand and emits `exiftoolMissingChanged` / `exiftoolVersionChanged` as needed. **Date filter**: `dateFrom` / `dateTo` int properties (UTC epoch seconds, 0 = unset); `yearCounts` string property (JSON array `[{year, count}]` for the histogram); `setDateFilter(date_from, date_to)` and `clearDateFilter()` slots trigger a new search and reload the histogram; `_load_year_counts()` calls `repo.get_year_counts()` and emits `yearCountsChanged`; date params are propagated to `SearchWorker`, `BulkOpWorker`, `loadMore`, and `count_images`. |
| `models/search_list_model.py` | `QAbstractListModel` — search result rows; roles: `path`, `filename`, `metadataJson`, `thumbnailSource`, `fileSize`. Thumbnail URIs are pre-computed at `set_rows` / `append_rows` time using DB-stored `mtime`/`size` stamps — no `os.stat` per repaint. **All thumbnails are served via `image://thumb/<sha1>` (never `file://`)**; an optional `?t=N` per-path bust counter is appended after a `bust_thumbnail(row)` call so QML’s pixmap cache refetches the rebuilt PNG. |
| `models/exif_list_model.py` | `QAbstractListModel` — EXIF key/value pairs for the detail panel |
| `models/folder_list_model.py` | `QAbstractListModel` — rows for the Folders management panel; roles: `folderId`, `path`, `displayName`, `status`, `imageCount`, `errorMessage`, `enabled` |
| `models/settings_model.py` | `SettingsModel(QObject)` — exposes `workerCount`, `blacklist`, `sortBy`, `language`, and `theme` to QML; per-DB settings (`workerCount`, `blacklist`, `previewMaxSize`, `sortBy`) persisted as JSON; language and theme stored globally via `i18n` module |
| `workers/index_worker.py` | `QThread` — runs `IndexerService.build_index` off the GUI thread; emits progress signals; supports `pause()`/`resume()` via `threading.Event` to yield I/O bandwidth during preview loads. After a successful (non-canceled) run, performs a **cache garbage-collection pass**: hashes every DB stamp into the expected SHA-1 set, scans `<cache_dir>` and `<cache_dir>/previews/`, and unlinks every file whose 40-character prefix is not expected. Emits a `(-1, -1, "")` sentinel `progress` signal so the controller can show a translated *“Cleaning up cache…”* status. |
| `workers/thumb_worker.py` | `QThread` — generates thumbnail cache off the GUI thread; supports `pause()`/`resume()` via `threading.Event` |
| `workers/bulk_op_worker.py` | `QThread` — executes the bulk operations off the GUI thread: `select_all`, `deselect_all`, `invert`, `select_missing_thumbs` (marks every matching image whose expected `thumb_cache_path()` has no `.png`/`.enc` on disk; `.skip` sentinels are treated as missing too so failed-thumbnail images surface), `export_json`, and `delete_marked` (removes marked images from disk and from the index, plus the matching cached thumbnail `.png`/`.enc`, `.skip` sentinel and rendered preview `.jpg`/`.jpg.enc`; persists partial progress on cancel so DB and disk stay in sync). Accepts full filter state (query, ext_filter, path_filter, restrict_to_enabled_folders, marked_only), a `sort_by` key for export ordering, and a `cache_dir` for thumb/preview lookup. Mark operations run in batches of 500 rows each emitting a progress tick; export writes one JSON record at a time; delete reports `result_deleted_count`, `result_missing_count`, `result_failed_count`. Signals: `progress(done, total)`, `finished`, `failed(message)`, `canceled`. |
| `workers/password_change_worker.py` | `PasswordChangeWorker(QThread)` — re-encrypts the SQLCipher database off the GUI thread using `PRAGMA rekey`; on success re-wraps the `ThumbCrypto` master key so existing thumbnails remain decryptable without rebuild. Signals: `finished`, `failed(message)`. |
| `workers/preview_build_worker.py` | `PreviewBuildWorker(QThread)` — renders preview JPEGs for one indexed folder off the GUI thread; scans the cache dir once, renders only missing previews with `render_preview()`, writes them as JPEG (encrypted via `ThumbCrypto` when DB key is set). Signals: `finished(built, total)`, `progress(done, total_missing, path)`, `canceled(built, total)`, `failed(message)`. |
| `providers/preview_image_provider.py` | `PreviewImageProvider(QQuickImageProvider)` — serves full-resolution previews for all formats (JPEG/PNG/TIFF/RAW) as `image://preview/<encoded-path>`; `ForceAsynchronousImageLoading`, `HighPriority` thread; reads raw bytes via `open().read()` to release the GIL during network I/O, then decodes in-memory with Pillow `draft()` for fast JPEG subsampling |
| `providers/raw_image_provider.py` | `RawImageProvider(QQuickImageProvider)` — legacy RAW-only provider (`image://raw/`); kept for backward compatibility |
| `providers/thumb_image_provider.py` | `ThumbnailImageProvider(QQuickImageProvider)` — serves `image://thumb/<sha1_hex>` URIs; reads `.enc` files (encrypted mode) or `.png` files (plain mode) from the cache dir, decrypts via `ThumbCrypto` (AES-256-GCM) when needed, decodes PNG bytes to `QImage`; thread-safe (key set once on unlock). Strips an optional `?t=N` cache-bust query string from the request id so the same SHA-1 can be re-served after a thumbnail rebuild. |
| `qml/Main.qml` | Main application window: tab bar (Search, Browse), split-pane layout, EXIF detail panel, Settings sheet, lock screen; **clipboard copy** — a **Copy** pill button in the preview header of both Search and Browse tabs calls `controller.copyPreviewToClipboard()`; a shared `Menu { id: previewContextMenu }` with a *Copy Image to Clipboard* item is triggered by a `TapHandler { acceptedButtons: Qt.RightButton }` in each preview pane; a pill-shaped toast `Rectangle` (`id: clipboardToast`) fades in/out (z:9999) and auto-hides after 2 s via `Timer`, driven by `onClipboardCopyDone`; **GPS location bar** in the Metadata panel (visible when the selected image has GPS coordinates — shows links to OpenStreetMap, Google Maps, and GeoHack); **search-syntax tooltip** — a `?` icon button (`searchHelpButton`) at the right edge of the search field, with a custom `ToolTip` `contentItem` (ColumnLayout with accent-coloured section headers, a two-column `GridLayout` of examples, and a tips bullet list); translated via `qsTr()`; **ExifTool section in Settings** — **Check** button calls `controller.checkExiftool()`; colour-coded status badge (green dot + version string / red dot + "Not found") bound to `controller.exiftoolVersion` and `controller.exiftoolMissing`; download link styled with `Material.accent` for dark-mode readability; all bindings guarded against `null` controller; **ExifTool missing dialog** — modal dialog triggered by `onExiftoolMissingChanged` when ExifTool is absent at unlock time, with a clickable `exiftool.org` link |
| `qml/FoldersPanel.qml` | Folder management panel — add/remove/enable folders, shows per-folder indexing status |
| `qml/FloatingBadge.qml` | Reusable badge overlay component |

**AppController design notes:**

- `unlock()` catches `sqlcipher3.DatabaseError` (wrong password) separately
  from generic `Exception` (I/O, corrupt file). The repository is always
  closed on any error path.
- `_DEFAULT_WORKERS = min(os.cpu_count() or 1, 12)` caps parallel workers;
  used in both `startIndexing` and `buildThumbnails`.
- `_run_search()` guards with `if self._repo is None: return` (safe under
  `-O` optimised bytecode in the frozen bundle).
- `isNewDatabase` — bool property, `True` when `db_path` does not exist at
  construction time. The QML lock screen switches to a passphrase-creation
  mode (confirm field + security hint). Cleared to `False` after a
  successful `unlock()` call.
- `isUnlocking` — bool property set to `True` the moment `unlock()` is
  called; cleared once the DB opens (or fails).
- **GPS location bar** — `_update_exif_table()` calls the static helper
  `_extract_geo_urls(parsed)` which reads `GPS:GPSLatitude`,
  `GPS:GPSLongitude`, `GPS:GPSLatitudeRef`, and `GPS:GPSLongitudeRef` from
  the metadata JSON and returns a triple `(osm_url, gmaps_url, geohack_url)`.
  Three `Q_PROPERTY` strings (`geoLocationUrl`, `geoGoogleMapsUrl`,
  `geoWikipediaUrl`) are emitted to QML; the Metadata panel renders a thin
  bar with links to OpenStreetMap
  (`https://www.openstreetmap.org/?mlat=…&mlon=…&zoom=14`), Google Maps
  (`https://www.google.com/maps?q=…`), and GeoHack
  (`https://geohack.toolforge.org/geohack.php?params=…`). The bar is hidden
  when no GPS data is present. `_clear_details()` resets all three URLs to
  `""`. A `QTimer.singleShot(50ms)`
  defers the blocking `open()` call so the QML repaint (spinner) executes
  before the main thread stalls. The QML lock screen shows a `BusyIndicator`
  + "Unlocking…" label and disables the Unlock button while `True`.
- **Bulk operations** — `selectAll()`, `deselectAll()`, `invertSelection()`,
  `selectMissingThumbnails()`, `exportMarkedMetadataJson()`, and
  `deleteMarkedImages()` slots each launch a `BulkOpWorker` on a background
  thread. While the worker runs, `isBusy` is `True` and a modal overlay with
  a `ProgressBar` and `"X / Y"` count label blocks the UI.
  `cancelBulkOp()` signals the worker to stop cleanly. Export respects the
  current UI sort order (`_sort_by` passed as `sort_by` to the worker and
  forwarded to `get_marked_metadata(sort_by=...)` → `ORDER BY`).
  `deleteMarkedImages()` requires QML to confirm via the typed-count
  dialog (the user must type the exact number of marked images) before the
  slot is invoked; on completion the search list, format facets, folder
  tree, and indexed-folder counts are refreshed, and the status bar
  reports `Deleted N image(s).` with optional `N were already missing.` /
  `N could not be deleted.` clauses.
- **Menu auto-sizing** — the Select and Action menus measure their widest
  item via `TextMetrics` and bind `implicitWidth` accordingly, so long
  dynamic labels (e.g. *"Delete Marked Images… (1234 selected)"* or
  *"Select Images Without Thumbnail"*) are never truncated.
- `currentResultRow` — `int` property tracking the currently selected result
  row. `_run_search()` restores it after a re-run (tab switch, filter change)
  so the selection survives navigation. Resets to `0` only when the query or
  filter actually changes. Drives QML `resultsList.currentIndex` and
  `browseImageList.currentIndex` via a declarative binding.
- **Pause/resume on selection** — `selectResult()` calls `pause()` on both
  `ThumbWorker` and `IndexWorker`, then schedules a 2-second `QTimer` to
  `resume()` them. This yields I/O bandwidth to `PreviewImageProvider` on
  slow network drives.
- `resetDatabase()` — drops and recreates `images_fts` FTS5 table (purging all
  shadow tables), runs `VACUUM` + `PRAGMA wal_checkpoint(TRUNCATE)` to shrink
  the database file immediately, removes the thumbnail cache directory, and
  emits signals to clear all QML models. Disabled while indexing is in progress.

**AppController signals (selection):**

| Signal | Purpose |
|--------|---------|
| `statusTextChanged` | Status bar message |
| `isIndexingChanged` | Whether index build is in progress |
| `isBuildingThumbsChanged` | Whether thumb generation is in progress |
| `isLockedChanged` | Whether the DB lock screen is shown |
| `isNewDatabaseChanged` | Whether the DB does not yet exist (passphrase-creation mode) |
| `isUnlockingChanged` | Whether the DB is currently being opened (unlock spinner) |
| `isBusyChanged` | Whether a bulk operation (select-all / export) is running |
| `busyLabelChanged` | Label text for the bulk-op modal overlay |
| `bulkProgressChanged` | Emits both `bulkProgress` (done) and `bulkProgressTotal` (total) |
| `selectedImageSourceChanged` | QML `Image.source` for the preview pane || `selectedThumbSourceChanged` | QML `Image.source` for the low-res placeholder shown while full preview loads |
| `clipboardCopyDone(message)` | Emitted after a clipboard copy attempt; `message` is a translated confirmation or error string |
| `currentResultRowChanged` | Currently selected result row index || `detailsHtmlChanged` | HTML for the EXIF detail panel |
| `indexCurrentChanged / indexTotalChanged` | Indexing progress |
| `thumbCurrentChanged / thumbTotalChanged` | Thumbnail progress |
| `indexedFoldersChanged` | Folder list changed (add/remove/enable/disable) |

### 5.6 `i18n/`

| Module | Purpose |
|--------|---------|
| `__init__.py` | Public API: `_()`, `set_language()`, `current_language()`, `available_languages()`, `current_theme()`, `set_theme()` |
| `translator.py` | `Translator` singleton — loads `.mo` binary catalogs at runtime via Python `gettext`; persists language and theme to a global `settings.json` |
| `locales/<lang>/LC_MESSAGES/exif_turbo.mo` | Compiled translation catalogs (de, fr, it, rm) |

Translation domain: `exif_turbo`. Supported languages: German (`de`), French (`fr`), Italian (`it`), Romansh (`rm`). Strings extracted from Python (`_()`) and QML (`qsTr()`) sources. Pipeline: `scripts/regenerate_translations.py`.

### 5.7 `utils/`

| Module | Purpose |
|--------|---------|
| `thumb_cache.py` | `thumb_cache_path()` / `thumb_cache_name_from_stamp()` — SHA-1 keyed by `path\|mtime\|size` → `.png` filename |
| `thumb_crypto.py` | `ThumbCrypto` — AES-256-GCM encrypt/decrypt for thumbnail and preview files. Uses a random per-cache-dir master key stored password-wrapped in `.thumb_key` (v2 layout); v1 legacy caches (`.salt`) are migrated on next unlock. `change_password(old, new)` re-wraps the master key without touching the cached files. Raises `WrongPasswordError` on bad password. |
| `preview_cache.py` | `preview_cache_name_from_stamp()` / `preview_cache_path()` / `preview_dir()` — SHA-1 keyed preview JPEG filenames; helpers to list, count, and clear cached previews for a folder. |
| `preview_render.py` | `render_preview(path, target_long_edge)` — renders a downscaled Pillow `Image` for any supported format (JPEG/PNG/TIFF/RAW via rawpy / video via `extract_video_frame`); used by `PreviewBuildWorker`. |
| `video_frame.py` | `extract_video_frame(path)` — PyAV-based frame extractor used by `render_preview()`, `ThumbWorker`, and `RawImageProvider` for video files. Tries the embedded thumbnail/cover stream first; on failure seeks to the keyframe nearest 1/3 of the duration. Rotation: reads the `rotate` metadata tag, falls back to parsing the QuickTime `tkhd` atom display matrix directly when PyAV does not expose `stream.side_data` (covers iOS MOV files where audio-only `trak` atoms have an identity matrix that must not short-circuit the loop). |

---

## 6. Data Flow

### Indexing

```
User selects folders in UI (or CLI --folders)
  → ImageFinder.iter_images() yields image paths
  → IndexerService compares mtime/size against DB stamps (skip unchanged)
  → ExifMetadataExtractor: exiftool -g1 -j → dict[str, str]
  → metadata_to_text(): flattens keys + values + raw JSON → FTS document
  → ImageIndexRepository.upsert_image() → images + images_fts updated
```

### Search

```
User types in search box
  → AppController.search(query) Slot
  → ImageIndexRepository.search_fts(query, page, page_size)
  → SELECT … FROM images JOIN images_fts … WHERE images_fts MATCH ?
  → SearchListModel populated → QML ListView updates
```

### Thumbnail generation

```
ThumbWorker iterates search results
  → thumb_cache_name_from_stamp(path, mtime, size) → cache PNG name
  → If missing: Pillow open → ImageOps.exif_transpose → resize → save PNG
  → For RAW: rawpy.imread → extract_thumb (JPEG) or postprocess → Pillow
  → SearchListModel.thumbnailSource updated → QML Image refreshes
```

Thumbnail URIs are pre-computed at `set_rows` time using DB-stored
`(mtime, size)` stamps — no live `os.stat` call per repaint. The cache
directory is derived from the active database path so multiple databases
maintain independent caches.

### Image preview

```
User selects image in UI
  → AppController.selectResult(row)
      • sets selectedThumbSource = cached 144px thumbnail (shown instantly)
      • sets selectedImageSource = "image://preview/<encoded path>"
      • pauses ThumbWorker + IndexWorker (yields I/O bandwidth)
      • schedules 2s timer to resume workers
  → Qt calls PreviewImageProvider.requestImage on HighPriority background thread
      • reads full file bytes via open().read()  ← GIL released during ReadFile()
      • decodes from BytesIO (in-memory, fast)
      • for JPEG: PIL.Image.draft() for subsampled decode (up to 8× faster)
      • for RAW: rawpy → Pillow
      • QImage returned to QML; placeholder fades out as full preview fades in
```

---

## 7. Configuration

| Setting | Source | Default |
|---------|--------|---------|
| Database path | `--db` CLI arg or env | `~/.exif-turbo/data/index.db` |
| Thumbnail cache | Derived from db path | `~/.exif-turbo/data/<db-stem>/thumbs/` |
| Skip dotfiles | `EXIF_TURBO_SKIP_DOTFILES` env | `true` |
| Database encryption key | UI lock screen | — (required; prompted on first launch) |
| UI language | Settings sheet → Language | System locale, fallback `en` |
| UI theme | Settings sheet → Theme | `system` (follows OS dark/light mode) |
| Sort order | Sort combo in Search tab | `captured_desc` (Date taken ↓) |

Language and theme are persisted globally to `settings.json`:

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\exif-turbo\settings.json` |
| macOS | `~/Library/Application Support/exif-turbo/settings.json` |
| Linux | `$XDG_CONFIG_HOME/exif-turbo/settings.json` (fallback `~/.config/`) |

---

## 8. Supported Image Formats

| Category | Extensions |
|----------|-----------|
| JPEG | `.jpg`, `.jpeg` |
| PNG | `.png` |
| TIFF | `.tif`, `.tiff` |
| RAW (Canon) | `.cr2`, `.cr3` |
| RAW (Nikon) | `.nef`, `.nrw` |
| RAW (Sony) | `.arw`, `.srf`, `.sr2` |
| RAW (Adobe) | `.dng` |
| RAW (Olympus) | `.orf` |
| RAW (Panasonic) | `.rw2` |
| RAW (Pentax) | `.pef` |
| RAW (Fuji) | `.raf` |
| RAW (Leica) | `.rwl` |
| RAW (Samsung) | `.srw` |
| Video | `.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.m4v`, `.mts`, `.m2ts`, `.3gp`, `.webm`, `.flv` |

---

## 9. CLI Reference

### `exif-turbo-index`

```
exif-turbo-index --folders <dir> [<dir> ...] --db <path.db> [options]

Options:
  --folders          One or more root folders to scan
  --db               Path to the SQLite database file
  --include-dotfiles Include files/folders starting with "."
  --force            Clear and rebuild the entire index
  --workers N        Parallel extraction workers (default: 1)
```

### `exif-turbo`

```
exif-turbo [--db NAME] [--version]
```

| Option | Description |
|--------|-------------|
| `--db NAME` | Open (or create) a named database stored at `~/.exif-turbo/data/<NAME>/<NAME>.db`. Default: `index`. |
| `--version` | Print the installed exif-turbo version and exit. |

---

## 10. FTS5 Query Syntax

```
term                  keyword anywhere in metadata
"exact phrase"        phrase search
term1 AND term2
term1 OR term2
term1 NOT term2
prefix*               prefix wildcard
```

The colon (`:`) is treated as a word separator, not an FTS5 column-filter
operator. This allows ExifTool group-prefixed keys such as `GPS:GPSLatitude`
or `ExifIFD:FocalLength` to be typed verbatim without quoting.

---

## 11. Release & Distribution

### Versioning

Single source of truth: `src/exif_turbo/__init__.py` → `__version__ = "X.Y.Z"`.
`pyproject.toml` `version` must be kept in sync.

### Build artefacts

| Platform | Script | Output |
|----------|--------|--------|
| Windows | `scripts/build_windows.py` | `dist\exif-turbo\` (onedir) + `dist\exif-turbo-<ver>-windows.msi` |
| macOS | `scripts/build_macos.py` | `dist/exif-turbo.app` + `dist/exif-turbo-<ver>-macos.dmg` |
| Linux | `scripts/build_linux.py` | `dist/exif-turbo/` (onedir) + `dist/exif-turbo_<ver>_amd64.deb` + `dist/exif-turbo-<ver>-1.x86_64.rpm` (via PyInstaller + fpm) |

### Release workflow

Write release notes.

1. Update `__version__` in `__init__.py` and `version` in `pyproject.toml`
2. Commit and push
3. Run `python scripts\build_windows.py` (Windows) / `python scripts/build_macos.py` (macOS)
4. Tag: `git tag -a v<ver> -m "Release v<ver>"` + `git push origin v<ver>`
5. Publish: `gh release create v<ver> --title "exif-turbo v<ver>" --notes "Release v<ver>" dist\exif-turbo-<ver>-windows.msi`

Or use the `/release` Copilot prompt in VS Code.

---

## 12. Project Structure

```
exif-turbo/
├── src/exif_turbo/
│   ├── __init__.py              # __version__
│   ├── app.py                   # GUI entry point
│   ├── index.py                 # CLI entry point
│   ├── config.py                # AppConfig, env vars, paths
│   ├── data/
│   │   ├── image_index_repository.py
│   │   └── indexed_folder_repository.py
│   ├── i18n/
│   │   ├── __init__.py          # public API: _(), set_language(), current_theme(), …
│   │   ├── translator.py        # Translator singleton; settings.json persistence
│   │   └── locales/             # de, fr, it, rm — .po + .mo catalogs
│   ├── indexing/
│   │   ├── cli.py
│   │   ├── exif_metadata_extractor.py
│   │   ├── image_finder.py
│   │   ├── image_utils.py
│   │   ├── indexer_service.py
│   │   └── metadata_extractor.py
│   ├── models/
│   │   ├── indexed_folder.py
│   │   ├── indexed_image.py
│   │   └── search_result.py
│   ├── ui/
│   │   ├── app_main.py
│   │   ├── models/
│   │   │   ├── exif_list_model.py
│   │   │   ├── folder_list_model.py
│   │   │   ├── search_list_model.py
│   │   │   └── settings_model.py
│   │   ├── providers/
│   │   │   ├── preview_image_provider.py
│   │   │   ├── raw_image_provider.py
│   │   │   └── thumb_image_provider.py
│   │   ├── qml/
│   │   │   ├── Main.qml
│   │   │   ├── FoldersPanel.qml
│   │   │   └── FloatingBadge.qml
│   │   ├── view_models/
│   │   │   └── app_controller.py
│   │   └── workers/
│   │       ├── bulk_op_worker.py
│   │       ├── index_worker.py
│   │       ├── password_change_worker.py
│   │       ├── preview_build_worker.py
│   │       └── thumb_worker.py
│   ├── utils/
│   │   ├── preview_cache.py
│   │   ├── preview_render.py
│   │   ├── thumb_cache.py
│   │   └── thumb_crypto.py
│   └── assets/
│       ├── app_icon.svg
│       └── lense.svg
├── tests/
│   ├── conftest.py              # shared fixtures (repo, make_jpeg, make_png)
│   ├── data/
│   │   ├── test_excluded_paths.py
│   │   ├── test_image_index_repository.py
│   │   ├── test_image_index_repository_rekey.py
│   │   └── test_indexed_folder_repository.py
│   ├── indexing/
│   │   ├── test_image_utils.py
│   │   ├── test_indexer_service.py  # e2e — real images, real DB
│   │   └── test_metadata_to_text.py
│   ├── ui/
│   │   ├── conftest.py              # Material style session fixture
│   │   ├── test_app_controller.py
│   │   ├── test_ext_filter.py
│   │   ├── test_ext_filter_with_folder.py
│   │   ├── test_folder_management.py
│   │   ├── test_metadata_panel_scroll_reset.py
│   │   ├── test_preview_build_worker.py
│   │   ├── test_preview_provider_missing_source.py
│   │   ├── test_raw_preview_toggle.py
│   │   ├── test_sort_combo_width.py
│   │   ├── test_thumbnail_loading.py
│   │   └── test_zoom_anchor.py
│   └── utils/
│       ├── test_preview_cache.py
│       └── test_thumb_crypto.py
├── installer/
│   └── exif-turbo.wxs           # WiX v4 MSI descriptor
├── scripts/
│   ├── build_windows.py
│   ├── build_macos.py
│   └── regenerate_translations.py
├── exif-turbo.spec              # PyInstaller — Windows
├── exif-turbo-macos.spec        # PyInstaller — macOS
├── pyproject.toml
└── README.md
```

---

## 13. External Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| PySide6 | ≥6.5 | Qt bindings — QML, widgets, image providers |
| Pillow | ≥10.0 | Thumbnail generation; EXIF orientation correction |
| rawpy | ≥0.18 | libraw wrapper for RAW format decoding |
| sqlcipher3 | ≥0.5 | Encrypted SQLite |
| cryptography | any | AES-256-GCM thumbnail/preview encryption (`ThumbCrypto`) |
| Babel | any | `.po`/`.mo` catalog management (dev-time only) |
| ExifTool | any (system) | EXIF extraction (external process) |

Build-time only:

| Dependency | Purpose |
|------------|---------|
| PyInstaller | Standalone binary packaging |
| WiX Toolset v4 | Windows MSI generation |
| hdiutil | macOS DMG creation (built in to macOS) |
| gh (GitHub CLI) | Publishing GitHub Releases |
