# exif-turbo

Fast image EXIF metadata search and indexing tool with a PySide6 QML desktop UI.
Fully generated using VS Code Copilot.

## Features

- Full-text search over all EXIF metadata using SQLite FTS5
- PySide6 QML UI with Material Design (light/dark follows system theme)
- Search and Browse tabs with 50/50 split-pane thumbnail preview
- RAW format support: CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF, RWL, SRW
- EXIF orientation correction for thumbnails (all formats including RAW)
- CLI indexer (`exif-turbo-index`) for scripted/headless use
- Encrypted database at rest (SQLCipher); password unlocked via the UI

## Recent changes

### UI & view-model improvements

- **Thumbnail rendering** — thumbnail URIs are pre-computed once when search
  results load, not recalculated on every repaint. This eliminates the
  per-frame `os.stat` call that caused visible jank on large result sets.
- **Thumbnail cache path** — the cache directory is now derived from the
  active database path (`~/.exif-turbo/data/<db-stem>/thumbs/`) so multiple
  databases keep independent caches.
- **`AppController.unlock()`** — SQLCipher authentication errors (wrong
  password) are now reported separately from other failures and the
  connection is always closed on any error path.
- **Worker count** — parallel worker count is capped at `min(cpu_count, 12)`
  in all code paths (UI and CLI) via a shared `_DEFAULT_WORKERS` constant.
- **`SearchResult`** — carries `mtime` so the UI can generate stable
  thumbnail cache keys without hitting the filesystem.

### Indexing & repository improvements

- **Atomic upserts** — the two-table write in `upsert_image` (`images` +
  `images_fts`) is now wrapped in a single transaction.
- **Efficient `delete_missing`** — replaced an O(N) per-row DELETE loop with
  a single set-difference query via a temporary table.
- **`RAW_EXTENSIONS`** — exported from `image_utils` as a named constant;
  `IMAGE_EXTENSIONS` is defined as `{..., *RAW_EXTENSIONS}`. No more
  duplicated extension lists across modules.
- **Logged failures** — `ExifMetadataExtractor` now logs a `WARNING` instead
  of silently swallowing extraction errors.

### Test suite

40 automated tests across four layers:

| Suite | Count | What it covers |
|-------|-------|----------------|
| `tests/data/` | 10 | Repository: upsert, FTS5 search, delete_missing, mtime column |
| `tests/indexing/` | 15 | Image utils, metadata text, IndexerService e2e (real JPEG/PNG files) |
| `tests/ui/` | 5 | Live QML window driven via pytest-qt — unlock, search, filter, clear |

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
