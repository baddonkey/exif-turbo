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
