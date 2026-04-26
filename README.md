# exif-turbo

Fast image EXIF metadata search and indexing tool with a PySide6 QML desktop UI.
Fully generated using VS Code Copilot.

## Features

- Full-text search over all EXIF metadata using SQLite FTS5
- PySide6 QML UI with Material Design — light, dark, or system theme
- Multilanguage UI: English, German, French, Italian, Romansh
- Search and Browse tabs with 50/50 split-pane thumbnail preview
- Folder management — add, remove, enable/disable indexed folders with per-folder status
- RAW format support: CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF, RWL, SRW
- EXIF orientation correction for thumbnails (all formats including RAW)
- CLI indexer (`exif-turbo-index`) for scripted/headless use
- Encrypted database at rest (SQLCipher); passphrase set on first launch, unlocked via the UI

## Recent changes

### Multilanguage support

- **i18n infrastructure** — Python `gettext` based translation system. Supported
  languages: German, French, Italian, Romansh. Language is switchable at runtime
  from the Settings sheet without restarting.
- **Translation pipeline** — `scripts/regenerate_translations.py` extracts
  strings from both Python (`_()`) and QML (`qsTr()`), merges them into `.pot`,
  updates `.po` catalogs, and compiles `.mo` binaries.

### Theme support

- **Light / Dark / System theme** — QML `Material.theme` binding driven from
  `settingsModel.theme`. The selection is persisted globally to `settings.json`
  and applied immediately without restart.

### Preview performance on network drives

- **GIL-safe image loading** — `PreviewImageProvider` reads the full image
  file via `open(path, "rb").read()` so CPython releases the GIL during the
  `ReadFile()` syscall. This prevents PIL's C decoder from blocking the Qt
  event loop while fetching from a NAS or slow share.
- **Dedicated high-priority image provider** — `image://preview/` handles all
  formats (JPEG/PNG/TIFF/RAW). The provider thread is boosted to
  `HighPriority` and uses `PIL.Image.draft()` for JPEG subsampled decode (up
  to 8× faster for large camera files).
- **Background worker pause/resume** — clicking a result pauses
  `ThumbWorker` and `IndexWorker` for 2 seconds via `threading.Event` so the
  preview provider gets undivided I/O bandwidth on the network share.
- **Instant thumbnail placeholder** — the cached 144 px thumbnail is shown
  immediately while the full-resolution image loads asynchronously; it fades
  out with a 150 ms transition once the full image is ready.

### Browse tab

- **Browse tab enabled** — the Browse tab is now fully functional. Selecting
  a folder in the tree filters the image list to that folder; clicking an
  image shows the full EXIF detail panel and preview, identical to the Search
  tab.
- **Tab-switch row preservation** — `AppController` tracks `currentResultRow`
  as a `Q_PROPERTY`. Switching away and back to the Search or Browse tab
  restores the previously selected row instead of resetting to row 0.

### New-database passphrase UX

- **Passphrase creation screen** — when a database does not yet exist,
  `AppController.isNewDatabase` is `True` and the lock screen switches to a
  dedicated creation mode: passphrase + confirm fields, mismatch validation,
  a prominent security hint (recommends ≥12 chars, warns no recovery), and a
  "Create Database" button. After first unlock the screen reverts to the normal
  unlock form.

### Folder management

- **Indexed folder tracking** — folders are stored in a dedicated
  `indexed_folders` table. The Folders panel lets users add/remove folders and
  toggle them on/off; disabled folders are excluded from search results without
  losing their index data.
- **Per-folder status** — each folder tracks its last indexing status
  (`new`, `indexed`, `error`) and image count.

### UI & view-model improvements

- **Thumbnail rendering** — thumbnail URIs are pre-computed once when search
  results load, not recalculated on every repaint.
- **Thumbnail cache path** — derived from the active database path
  (`~/.exif-turbo/data/<db-stem>/thumbs/`) so multiple databases keep
  independent caches.
- **`AppController.unlock()`** — SQLCipher authentication errors are reported
  separately from other failures; the connection is always closed on any error.
- **Worker count** — capped at `min(cpu_count, 12)` via a shared constant.
- **`SearchResult`** — carries `mtime` for stable thumbnail cache keys.

### Indexing & repository improvements

- **Atomic upserts** — `upsert_image` wraps both `images` + `images_fts` writes
  in a single transaction.
- **Efficient `delete_missing`** — set-difference query via a temporary table
  replaces an O(N) per-row DELETE loop.
- **`RAW_EXTENSIONS`** — exported constant; `IMAGE_EXTENSIONS` is defined as
  `{..., *RAW_EXTENSIONS}`. No duplicated extension lists.
- **Logged failures** — `ExifMetadataExtractor` logs a `WARNING` instead of
  swallowing extraction errors.

### Test suite

81 automated tests across four layers:

| Suite | Count | What it covers |
|-------|-------|----------------|
| `tests/data/` | 38 | Repository: upsert, FTS5 search, delete_missing, excluded paths, folder management |
| `tests/indexing/` | 25 | Image utils, metadata text, IndexerService e2e (real JPEG/PNG files) |
| `tests/ui/` | 18 | Live QML window driven via pytest-qt — unlock, search, filter, folder add/remove/enable, controller state |

## Requirements

### ExifTool

This application requires **ExifTool** to be installed and on `PATH`.
ExifTool reads EXIF, IPTC, XMP, and other metadata from image files.

Download: https://exiftool.org/

**Windows:** download the standalone `.exe`, rename to `exiftool.exe`, place on `PATH`.

**macOS:**
```bash
brew install exiftool
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt install exiftool
```

## Installation

### Windows / macOS installer (recommended)

Download the latest installer from the [Releases page](https://github.com/baddonkey/exif-turbo/releases):

- **Windows**: `exif-turbo-<version>-windows.msi` — installs to `%ProgramFiles%\exif-turbo\`, adds Start Menu shortcut

### From source

```bash
pip install -e .
```

## Usage

### Launch the GUI

```bash
exif-turbo
```

### Build / update the index (CLI)

```bash
exif-turbo-index --folders "C:\Photos" --db data\index.db
```

### Python module invocation

```bash
python -m exif_turbo.app
python -m exif_turbo.index --folders "C:\Photos" --db data\index.db
```

## Configuration

Control whether dotfiles (filenames starting with `.`) are indexed:

| Method | Value |
|--------|-------|
| Environment variable | `EXIF_TURBO_SKIP_DOTFILES=true\|false` (default: `true`) |
| CLI flag | `--include-dotfiles` |

## FTS5 Query Syntax

```
term                    # single keyword
"exact phrase"          # phrase search
term1 AND term2
term1 OR term2
term1 NOT term2
col:term                # search within a specific EXIF field
prefix*                 # prefix wildcard
```

Examples:

```
camera:Canon lens:50mm
"red car" AND mexico
path:*.jpg
```

## License

MIT — see [LICENSE](LICENSE).

Third-party software credits: [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).

## Building from source

### Windows MSI

Requirements: `pip install pyinstaller`, [WiX Toolset v4](https://wixtoolset.org/)

```powershell
pwsh scripts\build_windows.ps1
# Produces: dist\exif-turbo\  and  dist\exif-turbo-<version>-windows.msi
```

### macOS DMG

Requirements: `pip install pyinstaller`, Xcode Command Line Tools

```bash
bash scripts/build_macos.sh
# Produces: dist/exif-turbo.app  and  dist/exif-turbo-<version>-macos.dmg
```

### Tagging a release

```powershell
pwsh scripts\tag_release.ps1
```

Or use the `/release` prompt in VS Code Copilot Chat.
