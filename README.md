# exif-turbo

Fast image EXIF metadata search and indexing tool with a PySide6 QML desktop UI.
Fully generated using VS Code Copilot.

![exif-turbo search tab](docs/screenshots/03_search_eagle.png)

*Photo: © [Giles Laurent](https://gileslaurent.com), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)*

📖 **[User Manual](docs/user-manual.md)** ([PDF](docs/user-manual.pdf)) — full feature reference, keyboard shortcuts, and screenshots.

## Features

- **Encrypted thumbnail and preview cache** — thumbnails and rendered previews are stored AES-256-GCM encrypted on disk; the encryption key is derived from the user’s password using a wrapped-key model so changing the password does not require rebuilding the cache
- **Change Password** — re-encrypts the SQLCipher database under a new passphrase without rebuilding thumbnails; existing encrypted thumbnails remain valid
- **Build Previews** — per-folder action builds a cache of downscaled preview JPEGs for instant display; configurable long-edge resolution in Settings
- **`×` clear button** — when the search field contains text a `×` button clears it immediately (equivalent to pressing **Enter** with an empty bar)
- **ExifTool not-found dialog** — if ExifTool is absent at unlock time a modal dialog explains that indexing is disabled and links to exiftool.org; search and browse of existing data continue normally
- Full-text search over all EXIF metadata using SQLite FTS5
- **Search-syntax tooltip** — a `?` button next to the search field shows an inline cheat-sheet (single token, phrases, AND/OR/NOT, prefix wildcard) translated into all supported languages
- **GPS location bar** — when the selected image has GPS coordinates, a bar in the Metadata panel shows one-click links to OpenStreetMap, Google Maps, and GeoHack (Wikimedia coordinate hub)
- PySide6 QML UI with Material Design — light, dark, or system theme
- Multilanguage UI: English, German, French, Italian, Romansh
- Search and Browse tabs with 50/50 split-pane thumbnail preview
- Folder management — add, remove, enable/disable indexed folders with per-folder status
- Multi-folder filter — when multiple folders are indexed, a **Folder(s)** dropdown in the search RESULTS header filters results to one or more selected folders simultaneously
- Scoped rescan — rescanning a single folder only updates that folder's records; other indexed folders are never touched
- Reset Database — wipes all indexed images, folder records, and thumbnail cache in one step; database file shrinks immediately
- RAW format support: CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF, RWL, SRW
- EXIF orientation correction for thumbnails (all formats including RAW)
- Encrypted database at rest (SQLCipher); passphrase set on first launch, unlocked via the UI
- **Mark / select images** — select all results (or deselect all) with a single menu action; individual checkbox per result row
- **Select images without thumbnail** — `Select → Select Images Without Thumbnail` marks every result whose thumbnail is not yet cached on disk (including images the thumbnailer permanently gave up on), so they can be exported, deleted or rescanned in bulk
- **Export marked images as JSON** — exports EXIF metadata for all marked images to a JSON file, respecting the current UI sort order
- **Delete marked images** — `Action → Delete Marked Images…` permanently removes every marked image from disk *and* from the index, including any cached thumbnail and rendered preview; a confirmation dialog requires you to type the exact count to proceed
- **Bulk-op progress overlay** — modal overlay with a progress bar and live `X / Y` count during select-all, deselect-all, and export operations; cancelable at any time
- **Unlock spinner** — animated indicator shown on the lock screen while the encrypted database is being opened
- **Fast NAS scanning** — on macOS/Linux, `ImageFinder` spawns up to 8 parallel `find` subprocesses (one per top-level subdirectory) so all `getdents()`/`lstat()` calls happen inside a C binary outside the Python GIL; a live "N files found…" counter updates the progress panel while discovery is still running

## Recent changes

### Encrypted thumbnail and preview cache

Thumbnails and rendered preview JPEGs are now stored AES-256-GCM encrypted
on disk. The encryption uses a random per-cache master key that is itself
stored password-wrapped in a `.thumb_key` file (v2 layout). Changing the
database password re-wraps only the master key — no thumbnails or previews
need to be rebuilt.

`ThumbnailImageProvider` serves `image://thumb/<sha1_hex>` URIs, decrypting
on demand in Qt’s async image-provider pool.

### Change Password

A **Change Password…** button in the Settings tab re-encrypts the SQLCipher
database off the GUI thread (`PasswordChangeWorker`). The dialog requires the
current password plus a new passphrase + confirmation. On success the
`ThumbCrypto` master key is re-wrapped under the new password so all cached
thumbnails remain valid immediately.

### Preview cache builder

A **Build Previews** action on each folder row in the Indexed Folders tab
launches `PreviewBuildWorker`, which renders downscaled JPEG previews for all
images in that folder and stores them in the preview cache (encrypted when a
database key is set). The preview long-edge resolution is configurable in
Settings (**Preview Cache Size**). The Search tab shows a **Show Preview /
Show Original** toggle to switch between the cached preview and the full
resolution source. While a full-resolution original loads, a
**"Loading original…"** overlay with a spinner appears over the preview area.

### ExifTool not-found dialog and settings badge

If ExifTool is absent when the database is unlocked, a modal dialog pops up
automatically explaining that indexing is disabled and providing a link to
exiftool.org. The Settings tab **ExifTool** section shows a colour-coded
badge (green = found with version, red = not found); a **Check** button
re-probes on demand.

### `×` clear button in search field

When the search field contains text a `×` button appears to its left.
Clicking it clears the field and immediately shows all images.

### macOS worker-count lock

On macOS the indexing worker count is automatically locked to **1** to prevent
Python GIL starvation that can occur with network-share folders. The spinner in
Settings is disabled in this configuration.

### Fast NAS scanning (macOS/Linux)

On macOS and Linux, `ImageFinder` spawns up to 8 parallel `find` subprocesses
— one per top-level subdirectory — via a `ThreadPoolExecutor` backed by a
shared `queue.Queue`. All `getdents()`/`lstat()` calls happen inside a C binary,
completely outside the Python GIL. This prevents the event-loop freezes
previously caused by macOS SMB mounts (where every `scandir()` entry has
`DT_UNKNOWN`, forcing a per-file `lstat()` through the GIL). Results stream
back live, so the **"N files found…"** count label updates while discovery is
still running.

On Windows, `os.walk()` is used instead — SMB returns file attributes inline so
no extra `stat()` calls are needed.

## Test suite

160 automated tests across four layers:

| Suite | Count | What it covers |
|-------|-------|----------------|
| `tests/data/` | 55 | Repository: upsert, FTS5 search, delete_missing (scoped), clear_all, excluded paths, folder management, rekey |
| `tests/indexing/` | 26 | Image utils, metadata text, IndexerService e2e (real JPEG/PNG files), scoped rescan |
| `tests/ui/` | 60 | Live QML window driven via pytest-qt — unlock, search, filter, folder add/remove/enable, controller state, ext filter, zoom, thumbnail loading, preview build worker, raw preview toggle, metadata panel scroll, sort combo |
| `tests/utils/` | 19 | Preview cache naming/clearing, thumb crypto (encrypt/decrypt, password change, legacy migration) |

**Total: 160**

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

If Homebrew is not installed yet:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
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

Use `--db <name>` to open a named database (stored under
`~/.exif-turbo/data/<name>.db`):

```bash
exif-turbo --db holidays
```

Print the installed version and exit:

```bash
exif-turbo --version
```

Folders to index are managed inside the GUI on the **Indexed Folders** tab.

### Python module invocation

```bash
python -m exif_turbo.app
python -m exif_turbo.app --db holidays
```

## Configuration

Control whether dotfiles (filenames starting with `.`) are indexed:

| Method | Value |
|--------|-------|
| Environment variable | `EXIF_TURBO_SKIP_DOTFILES=true\|false` (default: `true`) |

## FTS5 Query Syntax

```
term                    # single keyword
"exact phrase"          # phrase search
term1 AND term2
term1 OR term2
term1 NOT term2
prefix*                 # prefix wildcard
```

ExifTool group-prefixed keys (e.g. `GPS:GPSLatitude`, `ExifIFD:FocalLength`)
can be typed verbatim — the colon is treated as a word separator.

Examples:

```
Canon 50mm
"red car" AND mexico
GPS:GPSLatitude
ExifIFD:FocalLength
```

## License

MIT — see [LICENSE](LICENSE).

Third-party software credits: [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).

## Building from source

### Windows MSI

Requirements: `pip install pyinstaller babel pillow`, [WiX Toolset v4](https://wixtoolset.org/)

```powershell
python scripts\build_windows.py
# Produces: dist\exif-turbo\  and  dist\exif-turbo-<version>-windows.msi
```

### macOS DMG

Requirements: `pip install pyinstaller babel pillow`, Xcode Command Line Tools

```bash
python scripts/build_macos.py
# Produces: dist/exif-turbo.app  and  dist/exif-turbo-<version>-macos.dmg
```

### Tagging a release

Use the `/release` prompt in VS Code Copilot Chat.

## Sample Image Credits

The sample images used in tests and screenshots are photographs by
**[Giles Laurent](https://commons.wikimedia.org/wiki/User:Giles_Laurent)**,
published on Wikimedia Commons under the
[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/) license.

Mandatory attribution: © Giles Laurent, gileslaurent.com, License CC BY-SA

See [tests/sample-data/ATTRIBUTION.md](tests/sample-data/ATTRIBUTION.md) for the full list of images and their Wikimedia Commons links.
