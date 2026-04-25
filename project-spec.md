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
| Type checking | mypy strict |
| Testing | pytest |
| Packaging | PyInstaller (onedir) + WiX v4 (Windows MSI) + hdiutil (macOS DMG) |

---

## 4. Architecture

Ports & adapters (hexagonal) structure. Domain logic has no dependency on PySide6.

```
┌─────────────────────────────────────────────────────────┐
│  UI Layer (PySide6 / QML)                               │
│  AppController · SearchListModel · ExifListModel        │
│  RawImageProvider · IndexWorker · ThumbWorker           │
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
| `image_index_repository.py` | `ImageIndexRepository` — all DB access. Schema: `images` table + `images_fts` FTS5 virtual table. Encrypted via SQLCipher. |

**Schema:**

```sql
CREATE TABLE images (
    id            INTEGER PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,
    filename      TEXT NOT NULL,
    mtime         REAL NOT NULL,
    size          INTEGER NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE VIRTUAL TABLE images_fts
USING fts5(path, filename, metadata_text);
```

### 5.3 `indexing/`

| Module | Purpose |
|--------|---------|
| `cli.py` | `argparse` CLI adapter; entry point for `exif-turbo-index` |
| `image_finder.py` | `ImageFinder` — walks folders, yields image paths; honours `AppConfig.skip_dotfiles` |
| `exif_metadata_extractor.py` | `ExifMetadataExtractor` — runs `exiftool -g1 -j`; parses JSON output |
| `metadata_extractor.py` | `MetadataExtractor` protocol (port) |
| `indexer_service.py` | `IndexerService` — orchestrates scan → extract → upsert; supports parallel workers, incremental updates (mtime/size stamps), force-rebuild, progress callback, cancel |
| `image_utils.py` | Image file type helpers |

**Incremental indexing:** On each run, `IndexerService` compares `(mtime, size)` against DB-stored stamps. Only new or modified files are re-extracted. `force=True` clears all and rebuilds.

### 5.4 `models/`

| Model | Fields |
|-------|--------|
| `IndexedImage` | `path`, `filename`, `mtime`, `size`, `metadata: dict[str, str]` |
| `SearchResult` | `path`, `filename`, `metadata_json`, `size` |

### 5.5 `ui/`

| Module | Purpose |
|--------|---------|
| `app_main.py` | `main()` — bootstraps `QGuiApplication`, sets Material style, registers `RawImageProvider`, loads `Main.qml` |
| `view_models/app_controller.py` | `AppController(QObject)` — all business logic exposed to QML via `Q_PROPERTY`, `Signal`, `Slot` |
| `models/search_list_model.py` | `QAbstractListModel` — search result rows; roles: `path`, `filename`, `metadataJson`, `thumbnailSource`, `fileSize` |
| `models/exif_list_model.py` | `QAbstractListModel` — EXIF key/value pairs for the detail panel |
| `workers/index_worker.py` | `QThread` — runs `IndexerService.build_index` off the GUI thread; emits progress signals |
| `workers/thumb_worker.py` | `QThread` — generates thumbnail cache off the GUI thread |
| `providers/raw_image_provider.py` | `RawImageProvider(QQuickImageProvider)` — serves RAW images to QML as `image://raw/<encoded-path>`; uses `ForceAsynchronousImageLoading` |
| `qml/Main.qml` | Main application window: tab bar (Search, Browse), split-pane layout, EXIF detail panel, find-in-page bar |
| `qml/FloatingBadge.qml` | Reusable badge overlay component |

**AppController signals (selection):**

| Signal | Purpose |
|--------|---------|
| `statusTextChanged` | Status bar message |
| `isIndexingChanged` | Whether index build is in progress |
| `isBuildingThumbsChanged` | Whether thumb generation is in progress |
| `selectedImageSourceChanged` | QML `Image.source` for the preview pane |
| `detailsHtmlChanged` | HTML for the EXIF detail panel |
| `indexCurrentChanged / indexTotalChanged` | Indexing progress |
| `thumbCurrentChanged / thumbTotalChanged` | Thumbnail progress |

### 5.6 `utils/`

| Module | Purpose |
|--------|---------|
| `thumb_cache.py` | `thumb_cache_path()` / `thumb_cache_name_from_stamp()` — SHA-1 keyed by `path|mtime|size` → `.png` filename |

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
  → thumb_cache_path(path, mtime, size) → cache PNG path
  → If missing: Pillow open → ImageOps.exif_transpose → resize → save PNG
  → For RAW: rawpy.imread → extract_thumb (JPEG) or postprocess → Pillow
  → SearchListModel.thumbnailSource updated → QML Image refreshes
```

### RAW preview

```
User selects RAW image in UI
  → AppController sets selectedImageSource = "image://raw/<encoded path>"
  → Qt calls RawImageProvider.requestImage on background thread
  → rawpy → Pillow → QImage returned to QML
```

---

## 7. Configuration

| Setting | Source | Default |
|---------|--------|---------|
| Database path | `--db` CLI arg or env | `~/.exif-turbo/data/index.db` |
| Thumbnail cache | Derived from db path | `~/.exif-turbo/data/<db-stem>/thumbs/` |
| Skip dotfiles | `EXIF_TURBO_SKIP_DOTFILES` env | `true` |
| Database encryption key | UI unlock dialog | `""` (no encryption) |

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
exif-turbo [--db <path.db>]
```

---

## 10. FTS5 Query Syntax

```
term                  keyword anywhere in metadata
"exact phrase"        phrase search
term1 AND term2
term1 OR term2
term1 NOT term2
col:term              search within a specific EXIF field (e.g. camera:Canon)
prefix*               prefix wildcard
```

---

## 11. Release & Distribution

### Versioning

Single source of truth: `src/exif_turbo/__init__.py` → `__version__ = "X.Y.Z"`.
`pyproject.toml` `version` must be kept in sync.

### Build artefacts

| Platform | Script | Output |
|----------|--------|--------|
| Windows | `scripts/build_windows.ps1` | `dist\exif-turbo\` (onedir) + `dist\exif-turbo-<ver>-windows.msi` |
| macOS | `scripts/build_macos.sh` | `dist/exif-turbo.app` + `dist/exif-turbo-<ver>-macos.dmg` |

### Release workflow

1. Update `__version__` in `__init__.py` and `version` in `pyproject.toml`
2. Commit and push
3. Run `pwsh scripts\build_windows.ps1` (Windows) / `bash scripts/build_macos.sh` (macOS)
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
│   │   └── image_index_repository.py
│   ├── indexing/
│   │   ├── cli.py
│   │   ├── exif_metadata_extractor.py
│   │   ├── image_finder.py
│   │   ├── image_utils.py
│   │   ├── indexer_service.py
│   │   └── metadata_extractor.py
│   ├── models/
│   │   ├── indexed_image.py
│   │   └── search_result.py
│   ├── ui/
│   │   ├── app_main.py
│   │   ├── models/
│   │   │   ├── exif_list_model.py
│   │   │   └── search_list_model.py
│   │   ├── providers/
│   │   │   └── raw_image_provider.py
│   │   ├── qml/
│   │   │   ├── Main.qml
│   │   │   └── FloatingBadge.qml
│   │   ├── view_models/
│   │   │   └── app_controller.py
│   │   └── workers/
│   │       ├── index_worker.py
│   │       └── thumb_worker.py
│   ├── utils/
│   │   └── thumb_cache.py
│   └── assets/
│       ├── app_icon.svg
│       └── lense.svg
├── tests/
├── installer/
│   └── exif-turbo.wxs           # WiX v4 MSI descriptor
├── scripts/
│   ├── build_windows.ps1
│   ├── build_macos.sh
│   └── tag_release.ps1
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
| ExifTool | any (system) | EXIF extraction (external process) |

Build-time only:

| Dependency | Purpose |
|------------|---------|
| PyInstaller | Standalone binary packaging |
| WiX Toolset v4 | Windows MSI generation |
| hdiutil | macOS DMG creation (built in to macOS) |
| gh (GitHub CLI) | Publishing GitHub Releases |
