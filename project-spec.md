# exif-turbo — Project Specification

## 1. Overview

**exif-turbo** is a cross-platform desktop application and CLI tool for indexing, searching, and non-destructively tagging image metadata. It scans one or more folders, extracts metadata from every image using ExifTool, stores searchable derived state in an encrypted SQLite database, and exposes the corpus through SQLite FTS5 and optional CLIP retrieval. A bundled CC0 Wikidata snapshot provides an offline, curated 8,313-concept visual vocabulary with mandatory `en/de/fr/it` terms. The 8,200-concept base is extended with qualified Wikidata concepts linked to the Library of Congress TGM. Accepted QIDs use schema-v2 adjacent plain-JSON sidecars; legacy `loc-tgm` sidecars remain compatible. A PySide6 QML UI provides real-time search, thumbnail preview, browsing, a focused-image tagging drawer, and a separate marked-image tool for bulk workflows.

---

## 2. Goals

| Goal | Description |
|------|-------------|
| **Speed** | Index large photo libraries (10k+ images) with parallel extraction; search results are instant via FTS5 |
| **Completeness** | All EXIF/IPTC/XMP metadata captured; keys stored as `Group:Key` (ExifTool `-g1` format) |
| **Offline / private** | No cloud; database is encrypted at rest (SQLCipher) and stays on the user's machine |
| **Cross-platform** | Windows and macOS first-class; Linux supported from source |
| **Portable distribution** | Single-file MSI installer (Windows) and DMG (macOS) with no Python dependency |
| **Hybrid retrieval** | Classical EXIF FTS5 search plus CLIP-based semantic retrieval with per-folder AI indexing |
| **Portable tagging** | Store accepted Wikidata QIDs and custom free tags in adjacent JSON sidecars and index multilingual labels in FTS5 without changing originals |
| **Safe derivatives** | Copy marked, tagged images to a separate tree and write XMP/IPTC keywords only to verified copies |

---

## 3. Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| UI framework | PySide6 6.5+ — QML / Qt Quick / Material Design |
| Database | SQLCipher 3 (`sqlcipher3` 0.5+) — encrypted SQLite with WAL mode |
| Full-text search | SQLite FTS5 virtual table |
| AI semantic search | Multilingual OpenCLIP `xlm-roberta-base-ViT-B-32` / `laion5b_s13b_b90k` ([LAION checkpoint](https://huggingface.co/laion/CLIP-ViT-B-32-xlm-roberta-base-laion5B-s13B-b90k)) + FAISS (`faiss-cpu`) with cosine similarity (IndexFlatIP on L2-normalized vectors) |
| Controlled vocabulary | Bundled curated 8,200-concept Wikidata CC0 visual vocabulary; intrinsic `en/de/fr/it`; offline runtime |
| Tag persistence | Adjacent schema-v2 UTF-8 JSON sidecars plus normalized SQLCipher cache; schema-v1 TGM reader compatibility |
| EXIF extraction | ExifTool (external process, `-g1 -j` JSON output) |
| Thumbnails | Pillow ≥10.0 + `ImageOps.exif_transpose` (JPEG/PNG/TIFF) |
| RAW thumbnails | rawpy 0.18+ → libraw (CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF, RWL, SRW) |
| Video thumbnails / previews | PyAV 12+ → FFmpeg (MP4, MOV, AVI, MKV, WMV, M4V, MTS, M2TS, 3GP, WebM, FLV); embedded thumbnail when present, otherwise a frame at 1/3 of the duration; rotation from `rotate` tag or QuickTime `tkhd` display matrix |
| Large image rendering | pyvips 2.x / libvips (`pyvips` + `pyvips-binary`) — images > 100 MP decoded via libvips streaming I/O to avoid loading the full decoded raster into RAM; initialised lazily; bundled in Windows MSI, Linux DEB, and Linux RPM |
| Type checking | mypy strict |
| Testing | pytest |
| Packaging | PyInstaller (onedir) + WiX v6 (Windows MSI, bundles ExifTool) + hdiutil (macOS DMG) |

AI availability note: on macOS Intel (x86_64) targets, AI features are intentionally disabled in the Settings UI because PyTorch is not supported there for Python 3.13+.

---

## 4. Architecture

Ports & adapters (hexagonal) structure. Domain logic has no dependency on PySide6.

```
┌─────────────────────────────────────────────────────────┐
│  UI Layer (PySide6 / QML)                               │
│  AppController · search/tag list models · QML drawer   │
│  PreviewImageProvider · RawImageProvider                │
│  index, TGM, proposal, bulk-tag, derivative workers     │
└───────────────────┬─────────────────────────────────────┘
                    │ Slots / Signals
┌───────────────────▼─────────────────────────────────────┐
│  Domain / Application Layer                             │
│  IndexerService · TaggingService · SidecarSynchronizer  │
│  TGM import/update/vector/proposal services             │
│  DerivativeExportService · ExifMetadataWriter           │
└───────────────────┬─────────────────────────────────────┘
                    │ Repository interface
┌───────────────────▼─────────────────────────────────────┐
│  Data Layer                                             │
│  ImageIndexRepository (SQLCipher + FTS5 tag cache)      │
│  FilesystemSidecarRepository · TgmSnapshotRepository    │
│  separate image-vector and TGM-term FAISS repositories  │
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
| `config.py` | `AppConfig` dataclass and per-database paths for DB/cache, image FAISS artifacts, normalized TGM snapshot/work directory, and separate TGM term index/concept map/fingerprint metadata |
| `db.py` | Low-level DB helpers |
| `indexer.py` | Convenience re-exports for the indexing sub-package |

### 5.2 `data/`

| Module | Purpose |
|--------|---------|
| `image_index_repository.py` | `ImageIndexRepository` — all SQLCipher access for images, marks, sidecar synchronization state, normalized controlled/custom tags, reusable custom-tag catalog, rejected proposal decisions, and FTS5. Tag mutations refresh only `tags_text`; image reindexing preserves it. Accepted labels, IDs, categories, vocabulary identity, current aliases, and custom labels are searchable; proposals are excluded. Foreign-key cascades remove derived rows when an image row is removed but never delete a filesystem sidecar. |
| `indexed_folder_repository.py` | `IndexedFolderRepository` — manages the set of user-added folders: add, remove, enable/disable, status updates. `clear_all()` deletes all folder records. |
| `ai_vector_repository.py` | `AiVectorRepository` — schema v2 persists normalized semantic rows keyed by `(path, view_id)` in `ai_index.faiss` plus `ai_id_map.json` and checksummed `ai_index_meta.json`. Each image has a full view and four corner crops; old, corrupt, or mismatched indexes require AI Full Rescan. Search max-pools view scores by path. |
| `tgm_vector_repository.py` | `TgmVectorRepository` — schema v3 is an independent FAISS `IndexFlatIP` keyed by `(QID, locale)` for normalized English, German, French, and Italian prompt rows. Search max-pools locale scores by QID before applying `top_k`; term rows are never inserted into the image vector index. |
| `sidecar_sync_state.py` | Typed cached sidecar path/stamp/checksum/schema/status used to skip unchanged parses and report malformed sidecars. |

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
USING fts5(path, filename, metadata_text, tags_text);

CREATE TABLE image_sidecar_state (
  image_id       INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
  sidecar_path   TEXT NOT NULL,
  mtime_ns       INTEGER NOT NULL,
  size           INTEGER NOT NULL,
  checksum       TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  sync_status    TEXT NOT NULL,
  error          TEXT
);

CREATE TABLE accepted_image_tags (
  image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  concept_id TEXT NOT NULL,
  canonical_label TEXT NOT NULL,
  vocabulary TEXT NOT NULL,
  category TEXT NOT NULL,
  provenance_method TEXT NOT NULL,
  accepted_at TEXT NOT NULL,
  confidence REAL,
  model TEXT,
  vocabulary_checksum TEXT NOT NULL,
  PRIMARY KEY (image_id, concept_id)
);

CREATE TABLE accepted_image_tag_aliases (
  image_id INTEGER NOT NULL,
  concept_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  PRIMARY KEY (image_id, concept_id, alias),
  FOREIGN KEY (image_id, concept_id)
    REFERENCES accepted_image_tags(image_id, concept_id) ON DELETE CASCADE
);

CREATE TABLE image_tag_proposals (
  image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  concept_id TEXT NOT NULL,
  provider_fingerprint TEXT NOT NULL,
  canonical_label TEXT NOT NULL,
  category TEXT NOT NULL,
  score REAL NOT NULL,
  rank INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending', 'rejected')),
  provider_model TEXT NOT NULL DEFAULT 'clip',
  PRIMARY KEY (image_id, concept_id, provider_fingerprint)
);
```

The full implementation also preserves unknown sidecar/tag/provenance fields in
JSON columns. Existing databases migrate `images_fts` transactionally to add
`tags_text` while retaining image metadata and marks.

### 5.3 `indexing/`

| Module | Purpose |
|--------|---------|
| `cli.py` | `argparse` CLI adapter; entry point for `exif-turbo-index` |
| `image_finder.py` | `ImageFinder` — walks folders using `os.walk()`, yielding `(path, None, None)` tuples (mtime and size are always `None`; the indexer fetches them via `path.stat()` for new or changed files only). A 1 ms cooperative `time.sleep()` between directories prevents the scanner thread from starving other threads on very deep trees. Blacklisted directories are pruned in-place via `dirs[:]` so `os.walk` skips their subtrees entirely. Honours `AppConfig.skip_dotfiles` and a per-instance blacklist. |
| `exif_metadata_extractor.py` | `ExifMetadataExtractor` — runs `exiftool -g1 -j`; parses JSON output. `is_exiftool_available() -> bool` and `get_exiftool_version() -> str` probe for a working ExifTool via `_find_exiftool()`, which checks: (1) augmented `PATH` (adds macOS/Windows well-known install locations); (2) on Windows frozen bundles only, the bundled copy at `Path(sys.executable).parent / "exiftool" / "exiftool.exe"`; returning `False` / `""` if not found or if the process exits non-zero. |
| `metadata_extractor.py` | `MetadataExtractor` protocol (port) |
| `indexer_service.py` | `IndexerService` — orchestrates scan → extract → upsert, then synchronizes adjacent sidecars for every discovered image, including images whose own mtime/size is unchanged. Created, changed, deleted, malformed, and unsupported sidecars update/report cache state without writing originals. Supports parallel workers, force-rebuild, progress, and cancel. Capture-time resolution retains the documented EXIF/XMP/IPTC/QuickTime/filesystem fallback chain. |
| `ai_indexer_service.py` | `AiIndexerService` — lazy-loads OpenCLIP ViT-B/32, downloads tokenizer vocab if missing, encodes image previews into 512-d normalized vectors for FAISS, and encodes text queries for semantic search. |
| `image_utils.py` | Image file type helpers. Defines `RAW_EXTENSIONS`, `VIDEO_EXTENSIONS`, `IMAGE_EXTENSIONS` (union of stills + RAW + video), `is_image_file()`, `is_video_file()`. RAW orientation helper `orient_raw_thumb()` maps `rawpy.RawPy.sizes.flip` → Pillow transpose ops. |

**Incremental indexing:** On each run, `IndexerService` compares `(mtime, size)` against DB-stored stamps. Only new or modified files are re-extracted. `force=True` clears all and rebuilds. After scanning, `delete_missing(existing_paths, folder_roots=[...])` removes stale records scoped to the rescanned folder roots — records from other folders are not affected.

### 5.4 `models/`

| Model | Fields |
|-------|--------|
| `IndexedImage` | `path`, `filename`, `mtime`, `size`, `metadata: dict[str, str]`, `captured_at: float \| None` |
| `SearchResult` | `path`, `filename`, `metadata_json`, `size`, `mtime` |
| `IndexedFolder` | `id`, `path`, `display_name`, `status`, `image_count`, `error_message`, `enabled` |
| `ImageSidecar` / `ImageTag` / `TagProvenance` | Schema-v1 authoritative accepted-tag and derivative-exclusion document, original identity snapshot, canonical `loc-tgm:tgmNNNNNN` tags, normalized custom free tags and `excluded_embedded_tags`, `exclude_all_embedded_tags`, manual/CLIP provenance, and forward-compatible unknown fields |
| `TgmConcept` / `TgmSnapshot` | Canonical descriptors, aliases, subject and genre/form categories, relationships/notes, diagnostics, source URL/date/checksum, and normalized snapshot version |
| `TgmConceptLocalization` / `TgmLocalizationPack` | Optional localized preferred labels and aliases keyed by canonical TGM ID, with locale, source/license provenance, translation method, review status, and pack version |
| `TagProposal` | Ranked ephemeral/rejected canonical concept with score, category, provider model, and fingerprint |

`SearchResult.mtime` is populated from the DB-stored stamp so the UI can
derive stable thumbnail cache names without a live `os.stat` call.

#### 5.4.1 `tagging/`

| Module | Purpose |
|--------|---------|
| `sidecar_repository.py` | Maps an image to adjacent `<complete-filename>.sidecar.json`; validates schema v1, reads stable SHA-256/stamp revisions, writes deterministic UTF-8 JSON through fsynced sibling temporaries, and refuses external-edit races. Originals are never write targets. |
| `sidecar_synchronizer.py` | Reconciles sidecar create/change/delete/error state into normalized SQLite accepted tags and FTS cache without modifying the image or malformed sidecar. |
| `tagging_service.py` | Single mutation boundary for controlled/custom tag changes, embedded-tag exclusions, proposal decisions, and bulk operations. Copy Tags applies target-aware Add/Replace semantics to tags and ignore settings. Writes the sidecar first, updates derived cache transactionally, preserves valid sidecars after cache failures, and returns partial/conflict status. |
| `tgm_xml_parser.py`, `tgm_text_parser.py`, `tgm_importer.py` | Parse official TGM v1 XML and tagged text. Merged `TNR` values become `loc-tgm:<TNR>` IDs; `UF` and non-descriptor `USE` terms become canonical aliases; only postable MARC 150/650 subjects and 155/655 genre/form concepts are selectable. Optional unresolved relations become diagnostics. |
| `tgm_update_service.py`, `tgm_snapshot_repository.py` | Download LOC-hosted HTTPS XML first with tagged-text fallback, enforce size/sanity checks, retain source format/date/checksum, and atomically activate a gzip JSON snapshot. A failed candidate leaves the previous snapshot active. Checksums prove provenance/change, not publisher authenticity. |
| `tgm_localization_repository.py`, `tgm_localization_service.py` | Validate and atomically activate optional user-supplied provenance-bearing translation packs, resolve localized display/search labels by canonical ID, and preserve canonical fallback. Localized terms remain an overlay and never rewrite schema-v1 sidecars. |
| `tgm_prompt_builder.py`, `tgm_vector_index_service.py`, `tgm_clip_proposal_provider.py`, `tgm_proposal_service.py` | Build versioned canonical/alias/localized text prompts, maintain a fingerprinted TGM term index separate from image vectors, rank proposals, exclude accepted/rejected concepts for the current fingerprint, and require an existing image AI vector. The fingerprint includes localization checksum, locales, and prompt strategy. |
| `derivative_export_service.py`, `exif_metadata_writer.py` | Validate an output root outside indexed sources, preserve formats/relative trees, skip images without accepted additions and existing destinations, filter live embedded keywords through per-original exclusions or ignore-all, merge included keywords with canonical, interface-language, or selected-language controlled labels, replace XMP Subject and IPTC Keywords on temporary copies only, verify exact deduplicated readback, and atomically publish or clean up. |

### 5.5 `ui/`

| Module | Purpose |
|--------|---------|
| `app_main.py` | `main()` — bootstraps `QGuiApplication`, sets Material style, registers `PreviewImageProvider` (`image://preview/`) and `RawImageProvider` (`image://raw/`), loads `Main.qml`. Sets `PIL.Image.MAX_IMAGE_PIXELS = 894_784_850` (10× Pillow default) at startup so large panoramas and high-resolution TIFFs load without a `DecompressionBombWarning`. |
| `view_models/app_controller.py` | `AppController(QObject)` — all business logic exposed to QML via `Q_PROPERTY`, `Signal`, `Slot`. Accepts `cache_dir: Path | None` for thumbnail cache management. **Clipboard copy**: `copyPreviewToClipboard()` slot renders the current preview via `render_preview()`, converts it to RGBA `QImage`, and sets it on `QGuiApplication.clipboard()`; emits `clipboardCopyDone(message)` on success or falls back to copying the file path as text. **Save actions**: `pendingPreviewPath` property (`str`) exposes `_pending_preview_path` (currently selected image path) to QML; `doSavePreview(file_url)` renders the preview via `_load_preview_for_clipboard()` and writes JPEG or PNG to the path decoded from the QML `FileDialog` URL; `doSaveOriginal(file_url)` copies the source file byte-for-byte via `shutil.copy2`; both emit `clipboardCopyDone(message)` on success. `resetDatabase()` slot calls `clear_all()` on both repositories, removes the thumbnail cache directory, and resets all UI models. Multi-folder filter: `searchFolderListJson` property (JSON list of `{path, name}`), `toggleSearchFolderFilter(path)` / `clearSearchFolderFilters()` slots, `searchFolderFilters` property (JSON array of selected paths). The filter is applied to `search_images`, `count_images`, and `get_format_counts` via `path_filter` parameter. **ExifTool availability**: `exiftoolMissing` bool property + `exiftoolVersion` string property (both exposed to QML); populated via `get_exiftool_version()` at unlock time. `checkExiftool()` slot re-probes on demand and emits `exiftoolMissingChanged` / `exiftoolVersionChanged` as needed. **Date filter**: `dateFrom` / `dateTo` int properties (UTC epoch seconds, 0 = unset); `yearCounts` string property (JSON array `[{year, count}]` for the histogram); `setDateFilter(date_from, date_to)` and `clearDateFilter()` slots trigger a new search and reload the histogram; `_load_year_counts()` calls `repo.get_year_counts()` and emits `yearCountsChanged`; date params are propagated to `SearchWorker`, `BulkOpWorker`, `loadMore`, and `count_images`. **`isSearching`** bool property + `isSearchingChanged` signal — set to `true` when `SearchWorker` starts and `false` when it finishes; drives the QML search overlay `Rectangle` and `QGuiApplication.setOverrideCursor` / `restoreOverrideCursor` for the busy cursor. |
| `models/search_list_model.py` | `QAbstractListModel` — search result rows; roles: `path`, `filename`, `metadataJson`, `thumbnailSource`, `fileSize`. Thumbnail URIs are pre-computed at `set_rows` / `append_rows` time using DB-stored `mtime`/`size` stamps — no `os.stat` per repaint. **All thumbnails are served via `image://thumb/<sha1>` (never `file://`)**; an optional `?t=N` per-path bust counter is appended after a `bust_thumbnail(row)` call so QML’s pixmap cache refetches the rebuilt PNG. |
| `models/exif_list_model.py` | `QAbstractListModel` — EXIF key/value pairs for the detail panel |
| `models/folder_list_model.py` | `QAbstractListModel` — rows for the Folders management panel; roles: `folderId`, `path`, `displayName`, `status`, `imageCount`, `errorMessage`, `enabled` |
| `models/settings_model.py` | `SettingsModel(QObject)` — existing UI/index settings plus an independent per-database metadata language, tagging thresholds, and derivative TGM-label export mode (`canonical`, metadata language, or selected languages). Thresholds are clamped and auto-accept remains at least 0.01 stricter. AI availability excludes macOS Intel. |
| `models/accepted_tag_list_model.py`, `free_tag_list_model.py`, `marked_tag_list_model.py`, `pending_proposal_list_model.py`, `tgm_search_list_model.py` | Models for accepted controlled tags, current/remembered custom tags, ranked proposals, and canonical/alias TGM type-ahead results. `MarkedTagListModel` supports the internal bulk-tagging service but has no version 1 QML surface. |
| `workers/index_worker.py` | `QThread` — runs `IndexerService.build_index` off the GUI thread; emits progress signals; supports `pause()`/`resume()` via `threading.Event` to yield I/O bandwidth during preview loads. After a successful (non-canceled) run, performs a **cache garbage-collection pass**: hashes every DB stamp into the expected SHA-1 set, scans `<cache_dir>` and `<cache_dir>/previews/`, and unlinks every file whose 40-character prefix is not expected. Emits a `(-1, -1, "")` sentinel `progress` signal so the controller can show a translated *“Cleaning up cache…”* status. |
| `workers/ai_scan_worker.py` | `QThread` — folder-scoped CLIP embedding build for AI search. `aiScanFolder` indexes only missing vectors; `aiFullRescanFolder` removes vectors under that folder and rebuilds from scratch. Emits progress/canceled/failed signals mirrored in the Indexed Folders UI. |
| `workers/ai_search_worker.py` | `QThread` — semantic query worker used by Search-tab AI mode. Encodes query text with CLIP, searches FAISS with precision thresholds (**fine 0.22**, **normal 0.20**, **broad 0.18**), then hydrates ranked paths back to DB rows for display. |
| `workers/tgm_vector_build_worker.py` | Encodes canonical postable TGM concepts and aliases with the configured CLIP model into the separate term index; cancellation keeps the prior complete index active. |
| `workers/tgm_proposal_worker.py` | Searches existing image vectors against current TGM term vectors, applies proposal/optional auto-accept thresholds, returns ephemeral suggestions, persists rejection decisions, and reports missing image vectors as AI-scan-required without decoding originals. |
| `workers/bulk_tag_worker.py` | Internal worker for applying/removing one canonical concept across enabled-folder marks with per-image progress and partial-result summaries; retained for a future bulk-tagging UI and not invoked by version 1 QML. |
| `workers/derivative_export_worker.py` | Plans and exports marked tagged copies outside indexed roots, preserving relative trees/formats and delegating XMP/IPTC writes to the verified ExifTool adapter. |
| `workers/thumb_worker.py` | `QThread` — generates thumbnail cache off the GUI thread; supports `pause()`/`resume()` via `threading.Event`. `build_thumb()` wraps `_open_image()` with `_call_with_timeout()` (`_DECODE_TIMEOUT_S = 300.0 s`); a `TimeoutError` calls `_mark_skip()` so the file is excluded from future runs. |
| `workers/bulk_op_worker.py` | `QThread` — executes the bulk operations off the GUI thread: `select_all`, `deselect_all`, `invert`, `select_missing_thumbs` (marks every matching image whose expected `thumb_cache_path()` has no `.png`/`.enc` on disk; `.skip` sentinels are treated as missing too so failed-thumbnail images surface), `export_json`, and `delete_marked` (removes marked images from disk and from the index, plus the matching cached thumbnail `.png`/`.enc`, `.skip` sentinel and rendered preview `.jpg`/`.jpg.enc`; persists partial progress on cancel so DB and disk stay in sync). Accepts full filter state (query, ext_filter, path_filter, restrict_to_enabled_folders, marked_only), a `sort_by` key for export ordering, and a `cache_dir` for thumb/preview lookup. Mark operations run in batches of 500 rows each emitting a progress tick; export writes one JSON record at a time; delete reports `result_deleted_count`, `result_missing_count`, `result_failed_count`. Signals: `progress(done, total)`, `finished`, `failed(message)`, `canceled`. |
| `workers/password_change_worker.py` | `PasswordChangeWorker(QThread)` — re-encrypts the SQLCipher database off the GUI thread using `PRAGMA rekey`; on success re-wraps the `ThumbCrypto` master key so existing thumbnails remain decryptable without rebuild. Signals: `finished`, `failed(message)`. |
| `workers/preview_build_worker.py` | `PreviewBuildWorker(QThread)` — renders preview JPEGs for one indexed folder off the GUI thread; scans the cache dir once, renders only missing previews with `render_preview()`, writes them as JPEG (encrypted via `ThumbCrypto` when DB key is set). `build_one()` catches `TimeoutError` from `render_preview()` and writes a `.skip` sentinel (`<name>.jpg.skip` / `.jpg.enc.skip`) so the file is never retried. `_scan_existing()` recognises `.skip` files and maps them to the corresponding expected cache name so they are excluded on startup. Signals: `finished(built, total)`, `progress(done, total_missing, path)`, `canceled(built, total)`, `failed(message)`. |
| `providers/preview_image_provider.py` | `PreviewImageProvider(QQuickImageProvider)` — serves full-resolution previews for all formats (JPEG/PNG/TIFF/RAW) as `image://preview/<encoded-path>`; `ForceAsynchronousImageLoading`, `HighPriority` thread; reads raw bytes via `open().read()` to release the GIL during network I/O, then decodes in-memory with Pillow `draft()` for fast JPEG subsampling |
| `providers/raw_image_provider.py` | `RawImageProvider(QQuickImageProvider)` — legacy RAW-only provider (`image://raw/`); kept for backward compatibility |
| `providers/thumb_image_provider.py` | `ThumbnailImageProvider(QQuickImageProvider)` — serves `image://thumb/<sha1_hex>` URIs; reads `.enc` files (encrypted mode) or `.png` files (plain mode) from the cache dir, decrypts via `ThumbCrypto` (AES-256-GCM) when needed, decodes PNG bytes to `QImage`; thread-safe (key set once on unlock). Strips an optional `?t=N` cache-bust query string from the request id so the same SHA-1 can be re-served after a thumbnail rebuild. |
| `qml/Main.qml` | Main application window: tab bar (Search, Browse), split-pane layout, EXIF detail panel, Settings sheet, lock screen; **preview toolbar** — identical overlay on **both the Search-tab and Browse-tab** preview panes: **Copy** pill calls `controller.copyPreviewToClipboard()`; **Save Preview As** (white ⤓) and **Save Original As** (orange ⤓) pills open `savePreviewDialog` / `saveOriginalDialog` (`FileDialog`, `SaveFile` mode) with suggested filenames from `_suggestedPreviewUrl()` / `_suggestedOriginalUrl()` JS helpers; **Show Original / Show Preview** toggle pill calls `controller.setUseRawPreview()` and reflects the current mode with a colour-coded dot (green = preview, orange = original); a **loading overlay** (`BusyIndicator` + "Loading original…" label, rounded semi-transparent pill) fades in while the full-resolution image is decoding (only when `controller.useRawPreview` is `true`); matching *Save Preview As…* / *Save Original As…* items in the shared `previewContextMenu`; a pill-shaped toast `Rectangle` (`id: clipboardToast`) fades in/out (z:9999) and auto-hides after 2 s via `Timer`, driven by `onClipboardCopyDone`; **GPS location bar** in the Metadata panel (visible when the selected image has GPS coordinates — shows links to OpenStreetMap, Google Maps, and GeoHack); **search-syntax tooltip** — a `?` icon button (`searchHelpButton`) at the right edge of the search field, with a custom `ToolTip` `contentItem` (ColumnLayout with accent-coloured section headers, a two-column `GridLayout` of examples, and a tips bullet list); translated via `qsTr()`; **ExifTool section in Settings** — **Check** button calls `controller.checkExiftool()`; colour-coded status badge (green dot + version string / red dot + "Not found") bound to `controller.exiftoolVersion` and `controller.exiftoolMissing`; download link styled with `Material.accent` for dark-mode readability; all bindings guarded against `null` controller; **ExifTool missing dialog** — modal dialog triggered by `onExiftoolMissingChanged` when ExifTool is absent at unlock time, with a clickable `exiftool.org` link; **Browse-tab METADATA and EXIF TAGS panels** — the Browse tab has the same split-view METADATA panel (with inline Ctrl+F find bar and GPS location bar) and EXIF TAGS table as the Search tab; **search overlay** — when `controller.isSearching` is `true`, a semi-transparent grey `Rectangle` covers the entire window and `QGuiApplication.setOverrideCursor(Qt.BusyCursor)` blocks all input; both clear automatically when the search worker finishes |
| `qml/FoldersPanel.qml` | Folder management panel — add/remove/enable folders, shows per-folder indexing status |
| `qml/TaggingDrawer.qml` | Non-modal current-image drawer, available from Search/Browse via tag button or `Ctrl+T`: displays keywords embedded in the original without modifying it and allows per-keyword exclusion or ignore-all for derivatives; custom-tag creation/reuse/removal; canonical/alias TGM type-ahead; focused controlled-tag removal; proposal generation; scored accept/reject; progress and cancellation; fixed read-only footer previewing the final merged derivative keywords. |
| `qml/TaggingSettings.qml` | Per-database enable switch; canonical TGM and optional translation-pack installation; TGM vector build/rebuild; proposal thresholds; and derivative label-language controls. |
| `scroll_fix.py` | `ListScrollFix(QObject)` — window-level event filter that normalises mouse-wheel scrolling on QML `ListView`s to one row per 120-unit notch (`ROW_HEIGHT = 210 px`, accumulator for sub-notch input devices, pixelDelta fallback for trackpads/Wayland). Installed per ListView object name (`resultsList`, `browseImageList`, `foldersList`). The filter short-circuits when the target `ListView` is not actually visible (`QQuickItem.isVisible()` returns false when any ancestor is hidden), so the Search-tab `resultsList` does not silently consume wheel events while the user is on the Browse tab. |
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
- **Search/Browse tab-state isolation** — `enterBrowseTab(query_text)` and
  `leaveBrowseTab() -> str` slots snapshot the Search-tab filter state
  (query, format chip, date range, sort order, ext filter, folder filters)
  on entering the Browse tab and restore it on returning, so Browse-tab
  navigation never mutates the user's active Search filters.
- **"Browse →" card button** — each search result card in the Search tab has a
  pill-shaped `Browse →` button (bottom-right, left of the checkbox, `z:2`).
  Clicking it calls `controller.selectResult(index)` to capture the current
  row, then sets `root._pendingBrowseTarget`, switches to
  `mainTabBar.currentIndex = 1`, and calls `controller.browseFolder(folder)`
  to load the image's parent folder in Browse mode. Once Browse results load,
  `controller.selectResultByPath(target)` scrolls to and selects the image via
  a double `Qt.callLater` / `positionViewAtIndex` sequence.
- **"← Search" back button** — a `← Search` pill in the Browse-tab image list
  header (right of the `IMAGES` badge). Clicking it switches back to
  `mainTabBar.currentIndex = 0`, which triggers `leaveBrowseTab()` to restore
  the Search-tab filter snapshot and re-populate the search field; the scroll
  position is restored to exactly where the user was before the Browse jump.
- **Browse-tab keyboard navigation** — `Up` / `Down` / `PageUp` / `PageDown`
  shortcuts in `Main.qml` are gated on `mainTabBar.currentIndex === 1` and
  drive `browseImageList.currentIndex` through `controller.selectResult()`,
  mirroring the Search-tab navigation. `browseImageList` takes keyboard
  focus when it becomes visible and shows an always-on vertical scrollbar.
- `resetDatabase()` — drops and recreates `images_fts` FTS5 table (purging all
  shadow tables), runs `VACUUM` + `PRAGMA wal_checkpoint(TRUNCATE)` to shrink
  the database file immediately, removes thumbnail/preview caches and the
  per-database TGM snapshot/term-vector directory, then reinitializes tagging
  services and clears QML models. Adjacent source sidecars are not traversed or
  deleted; a later scan can synchronize them again. The separate image AI
  index/map files are not explicitly removed; AI Full Rescan is the clean
  rebuild path. Disabled while indexing is in progress and cancels tagging
  workers before maintenance starts.

**AppController signals (selection):**

| Signal | Purpose |
|--------|---------|
| `statusTextChanged` | Status bar message |
| `isIndexingChanged` | Whether index build is in progress |
| `isBuildingThumbsChanged` | Whether thumb generation is in progress |
| `isLockedChanged` | Whether the DB lock screen is shown |
| `isNewDatabaseChanged` | Whether the DB does not yet exist (passphrase-creation mode) |
| `isUnlockingChanged` | Whether the DB is currently being opened (unlock spinner) |
| `isSearchingChanged` | Whether a search is currently running (drives UI overlay and busy cursor) |
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
| `folder_labels.py` | `friendly_folder_label(path)` — returns a human-readable label for an indexed folder, used when the stored `display_name` is empty (e.g. drive roots, where `Path("C:\\").name == ""`). Windows drive roots resolve to `"<VolumeLabel> (C:)"` via `GetVolumeInformationW` (ctypes); falls back to `"C:\\"` when no label is readable. POSIX root returns `"/"`. Everything else returns `Path(path).name`. |
| `thumb_crypto.py` | `ThumbCrypto` — AES-256-GCM encrypt/decrypt for thumbnail and preview files. Uses a random per-cache-dir master key stored password-wrapped in `.thumb_key` (v2 layout); v1 legacy caches (`.salt`) are migrated on next unlock. `change_password(old, new)` re-wraps the master key without touching the cached files. Raises `WrongPasswordError` on bad password. |
| `preview_cache.py` | `preview_cache_name_from_stamp()` / `preview_cache_path()` / `preview_dir()` — SHA-1 keyed preview JPEG filenames; helpers to list, count, and clear cached previews for a folder. |
| `preview_render.py` | `render_preview(path, target_long_edge)` — renders a downscaled Pillow `Image` for any supported format (JPEG/PNG/TIFF/RAW via rawpy / video via `extract_video_frame`); used by `PreviewBuildWorker`. Images exceeding `MAX_PREVIEW_SOURCE_PX` (100 MP) or whose dimensions cannot be probed by Pillow are routed through **libvips** via `_load_vips()`. Native decoding requires libvips 8.13+, sets `VIPS_BLOCK_UNTRUSTED=1` before library initialisation, and enforces a configurable extension allowlist (default: JPEG, PNG, TIFF, WebP, GIF). `_ensure_pyvips()` initialises pyvips lazily on first use (thread-safe double-checked lock), adds `sys._MEIPASS` to `os.add_dll_directory` on Windows/PyInstaller so `libvips-42-*.dll` is findable, and caches the directory cookie in `_vips_dll_dir` to prevent GC. RAW and video decode calls are wrapped with `_call_with_timeout()` (daemon-thread runner, `_DECODE_TIMEOUT_S = 300.0 s`) so a corrupt/stuck file is abandoned after 5 minutes rather than hanging forever; `_TRUNCATED_LOCK` serialises the `LOAD_TRUNCATED_IMAGES` set→reset sequence in `_load_standard()` across concurrent worker threads. |
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

### Sidecar tagging and FTS

```
User chooses canonical term (or alias resolving to it)
  → AppController delegates to TaggingService
  → read and revision-check <image>.sidecar.json
  → atomic sibling-temp JSON replacement; original image untouched
  → replace normalized accepted tags/aliases + sidecar state in SQLCipher
  → refresh only images_fts.tags_text
  → accepted tag becomes searchable with normal FTS syntax
```

Embedded-keyword exclusions use the same revision-checked sidecar mutation
boundary. They affect derivative output only and never enter FTS or modify the
original image.

Regular and full image scans also run `SidecarSynchronizer` over every found
image, independent of the image mtime/size decision. Undecided proposals remain
in memory only; rejected decisions remain database-only and never enter
`tags_text`.

### Wikidata proposals

```
Explicit TGM install/update → normalized snapshot (XML, text fallback)
Explicit Build/Rebuild Vectors → four locale rows/QID in separate tgm_terms.faiss
AI Full Rescan → five views/image in separate ai_index.faiss
Open tagging drawer, change image, or manually generate
  → all image views search all locale-specific term rows
  → max score over 5 × 4 combinations/QID
  → threshold (default 0.20) → ranked ephemeral proposals
  → manual accept/reject, or confirmed auto-accept (default threshold 0.28)
  → accepted concepts pass through the same sidecar mutation service
```

A TGM checksum, localization-pack checksum/locales, prompt strategy/version, or
CLIP model change makes term vectors stale. Rebuilding TGM vectors does not
rebuild image vectors. Missing image vectors return an AI-scan-required result
rather than reading originals.

Developer diagnostics can bypass the threshold for manual generation and show
the raw top 20 QIDs with decimal cosine similarity and the winning view and
locale. Auto-accept remains thresholded. The offline domain-root curator
targets exactly 8,200 reviewed visual concepts. It applies deterministic
per-domain quotas, preserves valid forced includes, rejects override/quota
conflicts, resolves localized-label collisions by priority, and rebalances
unused domain quota globally. The audit reports every decision plus domain
shortfalls and overflow. The checked-in version 2 snapshot contains all 8,200
selected concepts.

### Tagged derivatives

```
Current matching images (all pages) or marked enabled-folder images + user output root
  → validate output outside indexed roots and plan collision-safe tree
  → skip untagged/existing destinations
  → copy2 source to same-format temporary destination
  → filter live embedded keywords through sidecar exclusions or ignore-all
  → merge included keywords with accepted additions, deduplicate
  → ExifTool replaces XMP-dc:Subject + IPTC:Keywords on temporary copy
  → verify exact labels → os.replace final destination
```

The Action menu asks for the output root. The writer rejects source paths,
cleans incomplete temporaries, does not copy sidecars, and never overwrites an
existing derivative.

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
| Tagging enabled | Settings → Tagging and TGM | `false` per database |
| Proposal threshold | Settings → Tagging and TGM | `0.20` |
| Auto-accept enabled / threshold | Settings → Tagging and TGM | `false` / `0.28` |
| Raw proposal diagnostics | Settings → Tagging and TGM | `false` |
| TGM snapshot and term vectors | Derived from database path | Per-database TGM directory; snapshot plus `tgm_terms.faiss`, concept map, fingerprint metadata |
| Image AI vectors | Derived from database path | Separate `ai_index.faiss` + `ai_id_map.json` + model/checksum `ai_index_meta.json`; built only by AI-Scan / AI Full Rescan |

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

**Windows MSI notes (`installer/exif-turbo.wxs`):**
- `Scope="perMachine"` + `ProgramFiles64Folder` — installs machine-wide under `C:\Program Files\exif-turbo\`.
- `MajorUpgrade Schedule="afterInstallInitialize"` — removes the previous version before copying new files, preventing stale `.pyd`/`.pyz` mismatches.
- The `AppShortcut` component KeyPath uses `HKLM` (not `HKCU`). Per-machine packages must use machine-scope KeyPaths; `HKCU` keys are user-specific, causing Windows Installer error 2755 when a different admin user upgrades the package.

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
