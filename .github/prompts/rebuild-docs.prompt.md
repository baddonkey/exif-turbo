---
description: "Rebuild everything: demo DB, index, thumbnails, screenshots, user manual content, and PDF"
name: "Rebuild documentation"
agent: "agent"
---

Fully rebuild the exif-turbo documentation artefacts from scratch.

## Steps

### 1. Update user manual content

Run the `documentation` subagent to review and update [docs/user-manual.md](../docs/user-manual.md) so it accurately reflects the current application behaviour, UI labels, and features. The agent should read the QML sources, view models, and existing manual, then apply any necessary corrections in place.

### 2. Rebuild screenshots and the demo database

Run the screenshot script. It will:
- Delete and re-create the demo SQLite database
- Re-index all sample images from `tests/sample-data/schweiz/`
- Register the folder in the `indexed_folders` table
- Launch the QML application, drive it through all seven UI states, and save PNGs to `docs/screenshots/`

```powershell
.venv\Scripts\python.exe scripts/take_screenshots.py
```

Wait for the script to finish (it takes 1–3 minutes). Confirm that all seven screenshots were saved. Expected size profile:

- Captures showing photo previews or thumbnails (`02_search_all`, `03_search_eagle`, `04_search_milky_way`, `05_browse_tab`, `07_folder_filter`) should be **> 500 KB** — anything under 100 KB indicates a blank/failed capture.
- Captures of mostly-chrome views (`01_lock_screen`, `06_indexed_folders`) are legitimately smaller (typically 30–80 KB) — do not flag these.

### 3. Generate the PDF

```powershell
.venv\Scripts\python.exe scripts/export_manual_pdf.py
```

Confirm that `docs/user-manual.pdf` was created and is larger than 1 MB (a PDF without embedded screenshots will be much smaller).

## Done

Report the final file sizes of each screenshot and the PDF.
