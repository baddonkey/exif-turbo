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
9. [Marking Images & Bulk Actions](#9-marking-images--bulk-actions)
10. [Settings](#10-settings)
11. [Keyboard Shortcuts](#11-keyboard-shortcuts)
12. [FAQ](#12-faq)

---

## 1. Requirements

### ExifTool

exif-turbo requires **ExifTool** on your `PATH` to extract metadata from images.

| Platform | Install |
|----------|---------|
| **Windows** | Download the standalone `.exe` from [exiftool.org](https://exiftool.org/), rename to `exiftool.exe`, place in a folder on your `PATH` |
| **macOS** | `brew install exiftool` (if Homebrew is not installed yet: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`) |
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
exif-turbo [--db NAME] [--version]
```

| Option | Description |
|--------|-------------|
| `--db NAME` | Open (or create) a named database instead of the default one. The database is always stored in `~/.exif-turbo/data/<NAME>/<NAME>.db`. Useful for keeping separate libraries — e.g. `exif-turbo --db work` and `exif-turbo --db holidays`. |
| `--version` | Print the installed exif-turbo version and exit. |

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
third-party open-source licence list, and the **About** dialog, which shows the
application version, a brief description of the application, and the licence (MIT).

---

## 4. Indexed Folders — Managing Your Library

Click the **Indexed Folders** tab to manage which directories are scanned.

![Indexed Folders tab](screenshots/06_indexed_folders.png)

### Adding a folder

1. Click **Add Folder** in the **Managed Folders** header bar at the top of the
   tab.
2. Pick the directory in the file browser dialog.
3. The folder is immediately queued for scanning — its status changes to **QUEUED**
   then **SCANNING** once the worker starts.

The header bar also provides **Rescan All** (incrementally re-index all enabled
folders) and **Full Rescan All** (force re-extract EXIF for every file in all
enabled folders).

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

Each folder row shows a coloured status badge, an image-count badge
(e.g. "42 images") once it has been indexed, and — if previews have been
rendered — a preview-cache badge ("✓ 42/42 previews"). The preview badge is
**green** when every image in the folder has a cached preview and **amber**
when only some do; hover it to see the exact ratio.

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
deleting it or its index data. Hovering the switch shows the tooltip *"Folder
is included in search results"* (when on) or *"Folder is excluded from search
results"* (when off).

### Per-folder actions

Each row exposes the following buttons on the right:

| Button | Action |
|--------|--------|
| **Rescan** | Incrementally re-index this folder (only files whose modification time changed). |
| **Full Rescan** | Force re-extract EXIF for every file in this folder. |
| **Build Previews** | Render preview-cache JPEGs for every image in this folder. While the build is running on this folder the same button reads **Cancel Previews**. Disabled while another folder's preview build is in progress. |
| **Clear Previews** | Delete all cached previews for this folder. Hidden (kept invisible for layout alignment) when nothing is cached. A confirmation dialog asks *"Delete N cached preview(s) for \"<folder>\"? Thumbnails are unaffected."* |
| **Remove** | Remove the folder and delete all its indexed images. A **Remove Folder** confirmation dialog asks before deletion. The original files on disk are not touched. |

---

## 5. Indexing Progress

While scanning, a non-blocking progress panel appears in the bottom-right corner
of the **Indexed Folders** tab. The same panel is reused for the two background
phases that may follow indexing — **thumbnail building** and **preview
building** — so it can show three different titles:

- **"Indexing folder N of M"** / **"Indexing"** — file-indexing phase. Shown
  while the indexer is processing folders from the queue.
- **"Building Thumbnails"** — thumbnail-cache phase, started automatically
  after indexing finishes.
- **"Building Previews"** — preview-cache phase, started by the **Build
  Previews** button on a folder row.

The panel always contains:

- **Progress bar** — indeterminate while the total is still being computed,
  then a percentage once it is known.
- **Count label** — **"Scanning for images…"** during indexing discovery,
  **"Preparing…"** for the thumbnail and preview phases before the total is
  known, then `n / total` files (indexing) or `n / total images` (thumbnails
  and previews).
- **Current file** — name of the file being processed.
- **Cancel button** — labelled **Cancel Indexing**, **Cancel Thumbnails**,
  or **Cancel Previews** depending on the phase. While an indexing or thumbnail
  cancel is in flight the label changes to **"Canceling…"** and the button is
  disabled until the worker has stopped.

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

*Photos: © [Giles Laurent](https://gileslaurent.com), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)*

### Running a search

Type any word or phrase into the **Search EXIF metadata…** bar and press
**Enter** (or click **Search**). exif-turbo performs a full-text search across
every metadata field — camera make and model, lens name, date, GPS coordinates,
keywords, copyright, and more.

Press **Enter** with an empty search bar to show all indexed images.

A **`?`** button at the right edge of the search field shows a syntax
cheat-sheet when hovered. It lists six examples (single token, implicit AND,
OR, NOT, exact phrase, prefix wildcard) and a short tips section. You do not
need to click it — the tooltip appears automatically on hover.

### Filtering by format

When results contain more than one file format, a row of format chips appears
below the search bar. Click a chip to show only that format:

```
All   CR2 · 1459   JPG · 563   TIF · 113   PNG · 2
```

Click **All** to return to unfiltered results.

### Filtering by folder

When you have two or more indexed folders enabled, a **Folder(s)** dropdown
appears in the RESULTS header bar, to the left of the **Sort** control. It is
hidden when only one folder is indexed.

The button label reflects the current filter state:

| Label | Meaning |
|-------|---------|
| **All folders** | No folder filter — results span all enabled folders |
| _Folder name_ | Exactly one folder is selected |
| **N folders** | N individual folders are selected |

Click **Folder(s)** to open the selection popup. Tick **All folders** to clear
any active filter; tick one or more folder names to restrict results to those
folders only. Multiple folders can be selected simultaneously. Hovering over a
folder name shows its full path as a tooltip.

![Folder filter popup](screenshots/07_folder_filter.png)

### The selection chip

Whenever at least one image is marked (or the marked-only filter is active), a
**selection chip** appears in the RESULTS header bar next to the **Folder(s)**
dropdown. It shows the current marked count:

| Label | Meaning |
|-------|---------|
| `☑ N` | Every marked image is in the current results |
| `☑ here/total` | Only some marked images match the current filters (e.g. `☑ 12/87`) |

Click the chip to toggle the **marked-only filter** — the tooltip switches
between *"Show only selected images"* and *"Show all results"*. While the
filter is active the chip stays highlighted so you always know which view
you are looking at.

*Photos: © [Giles Laurent](https://gileslaurent.com), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)*

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
| Smallest | File size, smallest first |

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
| `prefix*` | `Fuji*` | Matches any token starting with the prefix |

Multiple terms without an operator (`Canon 50mm`) are treated as an implicit AND.

ExifTool stores metadata with group-prefixed keys such as `GPS:GPSLatitude` or
`ExifIFD:FocalLength`. You can type these directly in the search box — the colon
is treated as a word separator, so `GPS:GPSLatitude` becomes an implicit AND
of `GPS` and `GPSLatitude`.

---

## 7. Browsing by Folder

The **Browse** tab lets you navigate your library by folder hierarchy:

![Browse tab](screenshots/05_browse_tab.png)

*Photos: © [Giles Laurent](https://gileslaurent.com), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)*

The left panel shows all indexed folders as an indented list — sub-folders are
indented under their parent. Each entry shows the folder name and a count of
images inside it. Click any folder to show only its images in the centre panel.
Click the highlighted folder again to deselect it and show all images.

The same thumbnail list and preview pane appear as in Search. **Single-click**
an image to select it and load the preview. The preview supports the same
zoom and pan gestures as in Search (scroll wheel, touchpad scroll, touchpad
pinch-to-zoom, drag-to-pan, double-tap to reset — see
[Zooming and panning](#zooming-and-panning)). **Double-click** an image to open
it in your system's default viewer. (Unlike the Search tab, double-clicking in
Browse always opens the image — there is no folder-open shortcut.) The Metadata
and EXIF Tags panels are not shown in the Browse tab; use the **Search** tab
for the full metadata view of a selected image.

Switching to the **Search** tab clears the folder filter and re-runs the current
search query. Any image previously selected while browsing is not automatically
highlighted in Search.

---

## 8. Viewing Metadata and EXIF Tags

Selecting any image in the result list populates three panels:

![Search results with detail panels](screenshots/04_search_milky_way.png)

*Photo: © [Giles Laurent](https://gileslaurent.com), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)*

### Preview

The right pane shows a full-resolution preview of the selected image scaled to
fit the available space. For RAW files (CR2, CR3, NEF, ARW, DNG, etc.) the
embedded preview JPEG is used. A cached thumbnail is shown immediately as a
low-resolution placeholder while the full image is loading; the full image fades
in once it has been decoded.

#### Show Preview / Show Original

When the selected image has a cached preview JPEG, a small pill toggle appears
at the right edge of the **PREVIEW** header bar. The label tells you what
clicking it will do:

- **Show Original** (with a green dot) — you are currently looking at the
  cached preview; click to load the full-resolution source file.
- **Show Preview** (with an orange dot) — you are currently looking at the
  full-resolution source; click to switch back to the cached preview.

The pill is useful for RAW files: the cached preview decodes instantly and is
sufficient for most viewing, but switching to **Show Original** loads the
full-resolution image when you want to zoom in for detail. The toggle is hidden
when no cached preview is available for the selected image.

#### Zooming and panning

The preview supports cursor-anchored zoom and drag-to-pan:

| Input | Action |
|-------|--------|
| **Ctrl + scroll wheel** (mouse) | Zoom in / out, anchored to the cursor position |
| **Ctrl + two-finger scroll** (touchpad) | Zoom in / out, anchored to the cursor position |
| **Touchpad — pinch** | Zoom in / out, anchored to the pinch centroid |
| **Click and drag** / **two-finger drag** | Pan the zoomed image in any direction |
| **Plain scroll wheel / two-finger scroll** | Pan vertically when zoomed in |
| **Double-click** / **double-tap** | Reset zoom to fit |

Zoom is capped at **8×**. A badge in the bottom-right corner of the preview shows
the current zoom level when it is above 1×. Selecting a new image always resets
the zoom to fit.

### Metadata panel (bottom-left)

Displays the metadata for the selected image as formatted, indented JSON. Click
the **Find** button in the panel header (or press **Ctrl+F**) to open an inline
search bar and find any tag value. Press **F3** (or click the ▼ / ▲ arrows) to
jump through all matches. Search terms from the main search bar are highlighted
automatically.

#### GPS location bar

When the selected image contains GPS coordinates in its EXIF metadata, a thin
bar appears directly below the **Find** bar. It shows a 🗺 icon, a
**"GPS location —"** label, and three links you can click to view the location
on a map:

| Link | Service |
|------|---------|
| **OpenStreetMap** | Opens the coordinates on [OpenStreetMap](https://www.openstreetmap.org) at zoom level 14 |
| **Google Maps** | Opens the coordinates in [Google Maps](https://www.google.com/maps) |
| **GeoHack** | Opens the [Wikimedia GeoHack](https://geohack.toolforge.org) coordinate hub — lists nearby Wikipedia articles and dozens of map services |

The bar is hidden when the selected image has no GPS data, or when nothing is
selected. Hovering over a link shows the full URL in a tooltip.

![GPS location bar](screenshots/08_gps_location_bar.png)

### EXIF Tags panel (bottom-right)

Displays the same metadata as a clean two-column table — **Tag** and **Value**
— sorted alphabetically. Hover over a truncated tag or value to see the full
text in a tooltip.

You can drag the divider between the two bottom panels to adjust the split.
By default they start at **50 % / 50 %**.

---

## 9. Marking Images & Bulk Actions

Every result card has a **checkbox** in its bottom-right corner. Tick it to
*mark* that image — marks persist across searches, tab switches, and app
restarts (the state is stored in the encrypted database). The same checkbox
is present on the cards in the **Browse** tab, so you can mark images while
browsing as well as while searching. Marked images are the input for the
bulk actions in the **Action** menu.

The menu bar exposes two menus dedicated to marking and bulk actions.

### Select menu

| Action | What it does |
|--------|--------------|
| **Select All** | Marks every image matching the current filters (search query, format chip, folder filter, marked-only toggle). Runs on a background thread in batches so the UI stays responsive. |
| **Deselect All** | Unmarks every image matching the current filters. |
| **Invert Selection** | Flips the marked state of every image matching the current filters. |
| **Select Images Without Thumbnail** | Marks every matching image whose thumbnail has not been cached on disk yet. Images the thumbnailer has permanently given up on (oversized files or decoder errors, recorded as a `.skip` sentinel) are also marked, so you can act on them — for example by exporting the metadata or deleting the offending files. Like the other Select actions, it respects the active search query, format chip, folder filter, and marked-only toggle. |

All four actions show the **bulk-op progress overlay** with a live `X / Y`
counter and a **Cancel** button.

### Action menu

The Action menu operates on whatever is currently marked across the entire
database — not just the visible results.

| Action | What it does |
|--------|--------------|
| **Export Metadata as JSON…** | Writes the EXIF metadata of every marked image to a JSON file you choose via a Save dialog. The export honours the current **Sort** order (filename, path, date, or size). When nothing is marked, the menu label changes to *"Export Metadata as JSON… (all results)"* and the action exports every image matching the current filters instead. |
| **Delete Marked Images…** | Permanently deletes every marked image **from disk** and removes its row from the index. Cached thumbnails (`.png` / `.enc`), `.skip` sentinels, and any rendered preview (`.jpg` / `.jpg.enc`) for the deleted images are also cleaned up. Disabled when nothing is marked. The menu label includes the current count, e.g. *"Delete Marked Images… (12 selected)"*. |

Both menu items report the live count in their label and run via the bulk-op
progress overlay; clicking **Cancel** mid-run stops cleanly and any deletions
already made stay on disk and in the index — the database is never out of
sync with the file system.

#### Confirming a delete

Because **Delete Marked Images…** is irreversible, the confirmation dialog
requires an extra step:

1. The dialog states how many files will be deleted (e.g.
   *"Permanently delete 12 marked image file(s) from disk and remove them
   from the index?"*).
2. A text field asks you to **type the exact count** — for example `12` —
   into the box labelled *"To confirm, type the number 12 below"*.
3. The **Yes** button stays disabled until the typed number matches the
   expected count exactly. Pressing **Enter** in the field also confirms
   the action when the count matches.
4. **Cancel** (or closing the dialog) aborts without deleting anything.

After completion the status bar reports the outcome, e.g.
**"Deleted 12 image(s)."** When some files were already gone or could not be
removed (for example because of file-system permissions) extra clauses are
appended: **"3 were already missing."** and/or **"1 could not be deleted."**

> **There is no undo.** Files are removed using the operating system's regular
> delete call — they do *not* go to the Recycle Bin / Trash. Make sure the
> marked set is correct before confirming.

### Tip — auto-sized menus

The Select and Action menu popups are sized to fit their longest item, so
dynamic labels such as *"Delete Marked Images… (1234 selected)"* are always
shown in full and never truncated.

---

## 10. Settings

Click the **Settings** tab to configure application behaviour.

### Worker Threads

Controls the number of parallel threads used for indexing and thumbnail
generation. Higher values speed up processing on multi-core machines but use
more CPU and memory. The default is half the number of detected CPU threads.

### Preview Cache Size

Long-edge resolution used by the preview-cache builder. Larger values give
sharper detail when zooming but take more disk space and longer to render.
Choose a value (in pixels) from the dropdown — the change applies to
subsequently built previews; existing cached previews are unaffected until
you rebuild them via **Build Previews** on a folder row.

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

### ExifTool

Click **Check** to verify that ExifTool is installed and available on your
`PATH`. A colour-coded badge appears next to the button:

- **Green dot + "Found — ExifTool \<version\>"** — ExifTool was found and
  the version is shown.
- **Red dot + "Not found"** — ExifTool is missing. A download link
  ([exiftool.org](https://exiftool.org/)) and a restart hint are shown below
  the badge.

The badge is also populated automatically each time you unlock the database,
so you do not need to click **Check** after every launch.

### Change Password

Click **Change Password…** to re-encrypt the SQLCipher database under a new
password. The dialog asks for:

- **Current password** — must match the password the database is currently
  encrypted with.
- **New password** — your new passphrase. Cannot be empty and must differ
  from the current one.
- **Confirm new password** — must match the new password exactly.

Click **Change Password** to apply. A busy indicator and the message
**“Changing password… This may take a moment.”** are shown while exif-turbo
re-encrypts every page of the database. Existing **thumbnails are preserved**
— exif-turbo uses a wrapped-key model, so only the wrapping key (which
protects the thumbnail key) is re-encrypted under the new password; the
thumbnail cache on disk does not have to be rebuilt.

Once the operation finishes successfully the dialog closes and a confirmation
appears. The new password is required the next time you unlock the database.

If the current password is wrong, an inline red error message
(“Current password is incorrect.”) is shown and the dialog stays open. The
The **Change Password…** button is disabled while indexing is in progress and while
the database is locked. The operation is also rejected if thumbnail building is
running when you submit the dialog.

> **There is no recovery if you forget the new password.** Make sure you
> remember it (or store it in a password manager) before clicking
> **Change Password**.

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

## 11. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Run search |
| `Ctrl+F` | Open / close find-in-metadata bar |
| `Escape` | Close the find-in-metadata bar |
| `F3` | Jump to next match in metadata |
| `Shift+F3` | Jump to previous match in metadata |
| `↓` | Select the next result (Search tab) |
| `↑` | Select the previous result (Search tab) |
| `Page Down` | Jump one page forward in results (Search tab) |
| `Page Up` | Jump one page backward in results (Search tab) |
| `Ctrl+Q` | Exit the application (File → Exit) |

---

## 12. FAQ

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
A: Open the **Settings** tab and click **Change Password…**. Enter your
current password and a new one — exif-turbo will re-encrypt the database in
place. Thumbnails are preserved (no re-indexing required). See
[Change Password](#change-password) for details.

**Q: Thumbnails are not showing / are slow to appear.**  
A: Thumbnails are generated in a background thread after indexing. Depending
on the number of images it may take a few minutes for all thumbnails to be
built and cached. They persist across sessions so subsequent launches are fast.

---

## Image Credits

The screenshots in this manual use sample photographs by
**[Giles Laurent](https://commons.wikimedia.org/wiki/User:Giles_Laurent)**,
published on Wikimedia Commons under the
[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/) license.

Mandatory attribution: © Giles Laurent, gileslaurent.com, License CC BY-SA

The GPS location bar screenshot uses a photograph by
**1904.CC** (Manuel Schmalstieg),
published on [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Xenakis_UPIC_system_computer_unit_2.jpg)
under the [Creative Commons CC0 1.0 Universal Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/).

Attribution (voluntary): 1904.CC (Manuel Schmalstieg), CC0, via Wikimedia Commons
