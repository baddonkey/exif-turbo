# exif-turbo User Manual

**exif-turbo** lets you scan image folders, build a searchable index of all EXIF
metadata, and instantly find any photo by camera model, lens, date, location, or any
other tag — across thousands of images.

---

## Table of Contents

1. [Requirements](#1-requirements)
2. [Installation](#2-installation)
3. [First Launch — Unlocking the Database](#3-first-launch--unlocking-the-database)
4. [Indexed Folders — Managing Your Library](#4-indexed-folders--managing-your-library)
5. [Indexing Progress](#5-indexing-progress)
6. [Searching](#6-searching)
7. [Browsing by Folder](#7-browsing-by-folder)
8. [Viewing Metadata and EXIF Tags](#8-viewing-metadata-and-exif-tags)
9. [Settings](#9-settings)
10. [Keyboard Shortcuts](#10-keyboard-shortcuts)
11. [FAQ](#11-faq)

---

## 1. Requirements

### ExifTool

exif-turbo requires **ExifTool** on your `PATH` to extract metadata from images.

| Platform | Install |
|----------|---------|
| **Windows** | Download the standalone `.exe` from [exiftool.org](https://exiftool.org/), rename to `exiftool.exe`, place in a folder on your `PATH` |
| **macOS** | `brew install exiftool` |
| **Linux** | `sudo apt install libimage-exiftool-perl` |

---

## 2. Installation

### Windows installer (recommended)

Download `exif-turbo-<version>-windows.msi` from the
[Releases page](https://github.com/baddonkey/exif-turbo/releases).
The installer adds an entry to **Start Menu** and puts `exif-turbo` on your `PATH`.

### From source

```bash
pip install -e .
```

### Command-line options

```
exif-turbo [--db NAME]
```

| Option | Description |
|--------|-------------|
| `--db NAME` | Open (or create) a named database instead of the default one. The database is always stored in `~/.exif-turbo/data/<NAME>.db`. Useful for keeping separate libraries — e.g. `exif-turbo --db work` and `exif-turbo --db holidays`. |

If `--db` is omitted, the default database `~/.exif-turbo/data/index/index.db` is used.

---

## 3. First Launch — Unlocking the Database

When you start exif-turbo you are greeted by the **lock screen**:

![Lock screen](screenshots/01_lock_screen.png)

### First-time setup — creating a new database

If this is the first time you have launched exif-turbo (or you are using a new
named database), the lock screen shows a **New passphrase** field, a
**Confirm passphrase** field, and a **Create Database** button. Choose a strong
passphrase of at least 12 characters that mixes letters, numbers, and symbols —
it encrypts your entire image index and **cannot be recovered if lost**.

### Opening an existing database

Enter your password in the **Password** field and click **Unlock** (or press
**Enter**). The same password is required every time you open the app.

Once unlocked, the **Search** tab opens and any previously indexed images are
immediately available.

### Help menu

The **Help** menu in the menu bar provides access to this user manual, the
third-party open-source licence list, and the **About** dialog which shows the
application version.

---

## 4. Indexed Folders — Managing Your Library

Click the **Indexed Folders** tab to manage which directories are scanned.

![Indexed Folders tab](screenshots/06_indexed_folders.png)

### Adding a folder

1. Click **Add Folder** (top-right of the Indexed Folders tab).
2. Pick the directory in the file browser dialog.
3. The folder is immediately queued for scanning — its status changes to **QUEUED**
   then **SCANNING** once the worker starts.

### Starting an index scan

Click **Rescan** next to a folder (or **Rescan All** to queue all enabled folders).
The folder status changes to **SCANNING** and the progress panel appears in the
bottom-right corner of the tab.

Use **Full Rescan** (or **Full Rescan All**) to force every file to be
re-processed even if its modification time has not changed. This is useful after
updating ExifTool or if you suspect the index is out of date.

When rescanning a single folder, only the records belonging to that folder are
updated or removed. Images indexed from other folders are not affected.

### Folder statuses

Each folder row shows a coloured status badge and an image count badge
(e.g. "42 images") once it has been indexed.

| Status | Meaning |
|--------|---------|
| **NEW** | Added but never scanned |
| **QUEUED** | Waiting in the scan queue |
| **SCANNING** | Currently being indexed |
| **INDEXED** | Last scan completed successfully |
| **MISSING** | Folder path no longer exists on disk |
| **ERROR** | Last scan ended with an error |
| **DISABLED** | Excluded from search results |

### Disabling / enabling a folder

Toggle the **Enabled** switch to exclude a folder from search results without
deleting it or its index data.

### Removing a folder

Click **Remove**. A confirmation dialog asks you to confirm before the folder
and all its indexed images are deleted from the database. The original files
on disk are not touched.

---

## 5. Indexing Progress

While scanning, a non-blocking progress panel appears in the bottom-right corner
of the **Indexed Folders** tab:

- **Queue indicator** — shows which folder is currently being scanned. When
  multiple folders are queued it reads **"Indexing folder 2 of 5"**; when only
  one folder is being processed it reads **"Indexing"**.
- **Progress bar** — shows an indeterminate animation while exif-turbo is
  scanning the folder for image files, then switches to a percentage once the
  total file count is known.
- **File counter** — shows **"Scanning for images…"** during the initial
  discovery phase, then `n / total` files once counting is complete.
- **Current file** — name of the file being processed.
- **Cancel Indexing** button — stops indexing immediately. While the worker is
  stopping the label changes to **"Canceling…"** and the button is disabled
  until the worker has stopped. During the thumbnail-build phase the same button
  shows **Cancel Thumbnails**.

The same progress panel is reused after indexing finishes to show **thumbnail
building** progress ("Building Thumbnails"). Thumbnails are generated in a
background pass and cached to disk so subsequent launches are fast.

Across **all tabs** the **status bar** at the very bottom of the window shows a
pulsing blue dot and the text **Indexing…** during the file-indexing phase, so
you always know the indexer is running even when you are working in Search or
Browse. The dot is not shown during the separate thumbnail-building phase. The
status bar also shows brief event messages to its right (such as "Indexed 42
images" after a scan completes).

### Pause and resume

If you close the application while indexing is in progress, the current folder
is saved as **QUEUED**. The next time you open exif-turbo and unlock the
database the scan queue is automatically restored and indexing resumes where
it left off.

---

## 6. Searching

The **Search** tab is the main way to find photos:

![Search — all images](screenshots/02_search_all.png)

### Running a search

Type any word or phrase into the **Search EXIF metadata…** bar and press
**Enter** (or click **Search**). exif-turbo performs a full-text search across
every metadata field — camera make and model, lens name, date, GPS coordinates,
keywords, copyright, and more.

Press **Enter** with an empty search bar to show all indexed images.

### Filtering by format

When results contain more than one file format, a row of format chips appears
below the search bar. Click a chip to show only that format:

```
All   CR2 · 1 459   JPG · 563   TIF · 113   PNG · 2
```

Click **All** to return to unfiltered results.

### Sorting results

Use the **Sort** dropdown at the top-right of the results panel:

| Option | Description |
|--------|-------------|
| Name A→Z | Filename ascending |
| Name Z→A | Filename descending |
| Path A→Z | Full path ascending (default) |
| Path Z→A | Full path descending |
| Newest first | Date taken, most recent first |
| Oldest first | Date taken, oldest first |
| Largest | File size, largest first |

### Loading more results

Results are loaded in batches as you scroll. When you reach the bottom of the
result list the next batch is fetched automatically. The total match count is
shown next to the **RESULTS** badge in the panel header.

### Opening images from results

**Single-click** a result card to select it and load the preview and metadata
panels.

**Double-click** a result card to open the file or folder in your system's
default application:
- Double-clicking the **thumbnail** (left side of the card) opens the image
  in your default image viewer.
- Double-clicking the **info area** (right side of the card) opens the parent
  folder in the system file manager. On Windows, Explorer opens with the file
  highlighted; on macOS and Linux the parent folder is opened.

### Search examples

| Query | What it finds |
|-------|---------------|
| `Canon EOS R5` | All images shot with a Canon EOS R5 |
| `f/1.4` | All images taken at f/1.4 aperture |
| `Switzerland 2024` | Images with Switzerland and 2024 in any metadata field |
| `eagle` | Images whose filename, title, or keywords mention eagle |
| `Nikon Z 9 ISO 6400` | Nikon Z 9 shots at ISO 6400 |

### Advanced query syntax

The search box accepts the full **SQLite FTS5** query language:

| Syntax | Example | What it does |
|--------|---------|--------------|
| `term` | `Canon` | Keyword anywhere in metadata |
| `"exact phrase"` | `"red deer"` | Terms must appear adjacent and in order |
| `term1 AND term2` | `Canon AND 50mm` | Both terms must be present |
| `term1 OR term2` | `Canon OR Nikon` | Either term must be present |
| `term1 NOT term2` | `50mm NOT Nikon` | First term present, second term absent |
| `column:term` | `filename:IMG_1234` | Search within a specific field only |
| `prefix*` | `Fuji*` | Matches any token starting with the prefix |

Available column names for scoped queries: `path`, `filename`, `metadata_text`.

Multiple terms without an operator (`Canon 50mm`) are treated as an implicit AND.

---

## 7. Browsing by Folder

The **Browse** tab lets you navigate your library by folder hierarchy:

![Browse tab](screenshots/05_browse_tab.png)

The left panel shows all indexed folders as an indented list — sub-folders are
indented under their parent. Each entry shows the folder name and a count of
images inside it. Click any folder to show only its images in the centre panel.
Click the highlighted folder again to deselect it and show all images.

The same thumbnail list and preview pane appear as in Search. **Double-click**
an image to open it in your system's default viewer. (Unlike the Search tab,
double-clicking in Browse always opens the image — there is no folder-open
shortcut.) The Metadata and EXIF Tags panels are not shown in the Browse tab;
use the **Search** tab for the full metadata view of a selected image.

Switching to the **Search** tab clears the folder filter and re-runs the current
search query. Any image previously selected while browsing is not automatically
highlighted in Search.

---

## 8. Viewing Metadata and EXIF Tags

Selecting any image in the result list populates three panels:

![Search results with detail panels](screenshots/04_search_milky_way.png)

### Preview

The right pane shows a full-resolution preview of the selected image scaled to
fit the available space. For RAW files (CR2, CR3, NEF, ARW, DNG, etc.) the
embedded preview JPEG is used. A cached thumbnail is shown immediately as a
low-resolution placeholder while the full image is loading; the full image fades
in once it has been decoded.

### Metadata panel (bottom-left)

Displays the metadata for the selected image as formatted, indented JSON. Click
the **Find** button in the panel header (or press **Ctrl+F**) to open an inline
search bar and find any tag value. Press **F3** (or click the ▼ / ▲ arrows) to
jump through all matches. Search terms from the main search bar are highlighted
automatically.

### EXIF Tags panel (bottom-right)

Displays the same metadata as a clean two-column table — **Tag** and **Value**
— sorted alphabetically. Hover over a truncated tag or value to see the full
text in a tooltip.

You can drag the divider between the two bottom panels to adjust the split.
By default they start at **50 % / 50 %**.

---

## 9. Settings

Click the **Settings** tab to configure application behaviour.

### Worker Threads

Controls the number of parallel threads used for indexing and thumbnail
generation. Higher values speed up processing on multi-core machines but use
more CPU and memory. The default is half the number of detected CPU threads.

### Indexing Blacklist

A list of file and folder name patterns to skip during indexing. Supports
wildcards: `*` matches any sequence of characters, `?` matches a single
character. Patterns are matched against individual file or folder names, not
full paths.

Examples: `@eaDir`, `*.tmp`, `Thumbs.db`

Changes to the blacklist take effect on the next rescan.

### Theme

Choose between **system** (follows OS dark/light mode), **light**, or **dark**.
The theme changes immediately.

### Language

Select the display language from the dropdown. A restart is required for the
language change to take full effect.

### Reset Database

At the bottom of the Settings tab, a divider separates the standard settings
from a destructive-action zone.

Click the ⚠️ **Reset Database…** button (red) to open a confirmation dialog.
Click **OK** to confirm. This permanently:

- Deletes all indexed images from the database
- Removes all indexed folder records
- Wipes the thumbnail cache on disk

The database is vacuumed and checkpointed immediately, so the database file
shrinks to near-zero on disk straight away.

> **This action cannot be undone.** After a reset you will need to re-add your
> folders and run a full rescan to rebuild the index.

The **Reset Database…** button is disabled while indexing is in progress.

---

## 10. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Run search |
| `Ctrl+F` | Open / close find-in-metadata bar |
| `Escape` | Close the find-in-metadata bar |
| `F3` | Jump to next match in metadata |
| `Shift+F3` | Jump to previous match in metadata |
| `Ctrl+Q` | Quit |

---

## 11. FAQ

**Q: Why does the status bar say "Indexing…" even after I switch tabs?**  
A: The indexer runs in the background across all tabs. The pulsing blue dot in
the status bar lets you know it is still working. You can continue searching
and browsing while indexing proceeds.

**Q: I closed the app mid-scan. Will I lose my progress?**  
A: No. exif-turbo saves the queue state when it closes. Next time you unlock the
database, any interrupted scans are automatically resumed.

**Q: The search finds nothing even though I can see files in the folder.**  
A: The files must be indexed first. Go to the **Indexed Folders** tab, add the
folder, and click **Rescan**.

**Q: Does exif-turbo modify my image files?**  
A: Never. exif-turbo only *reads* metadata — it never writes to your images.

**Q: What image formats are supported?**  
A: JPEG, PNG, TIFF, HEIC, BMP, GIF, and RAW formats: CR2, CR3, NEF, ARW, DNG,
ORF, RW2, PEF, RAF, RWL, SRW (and any other format that ExifTool can read).

**Q: Where is the database stored?**  
A: By default at `~/.exif-turbo/data/index/index.db` on all platforms.

**Q: How do I change the database password?**  
A: There is no in-app password change yet. Re-create the database by deleting
the `.db` file and re-indexing your folders with a new password.

**Q: Thumbnails are not showing / are slow to appear.**  
A: Thumbnails are generated in a background thread after indexing. Depending
on the number of images it may take a few minutes for all thumbnails to be
built and cached. They persist across sessions so subsequent launches are fast.
