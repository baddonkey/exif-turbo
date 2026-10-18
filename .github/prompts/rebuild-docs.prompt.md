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
- Copy the attributed deer sample to a temporary folder for demo-only tagging
- Seed the demo database with three sets, a saved filter, custom tags, and a description
- Launch the QML application, capture all 15 standard UI states, and save PNGs to `docs/screenshots/`

```powershell
.venv\Scripts\python.exe scripts/take_screenshots.py
```

Wait for the script to finish (it takes 1–3 minutes). Confirm that all 15 standard screenshots were saved, including `06_indexed_folders_basic.png` and `06_indexed_folders_expert.png`. Expected size profile:

- Captures with loaded photo previews or result imagery (`02_search_all`, `03_search_eagle`, `04_search_milky_way`, `05_browse_tab`, `07_folder_filter`, `08_gps_location_bar`, `09_ai_search_mode`) should normally be **> 300 KB**.
- UI-focused captures (`01_lock_screen`, both `06_indexed_folders` images, and `10`–`14`) are smaller because they show mostly controls or overlays. A low file size alone does not mean a capture failed; visually inspect the Sets, filter, tagging, copy-panel, and Action-menu screenshots for the intended state.

### 3. Generate the PDF

```powershell
.venv\Scripts\python.exe scripts/export_manual_pdf.py
```

Confirm that `docs/user-manual.pdf` was created and is larger than 1 MB (a PDF without embedded screenshots will be much smaller).
Confirm that each newly embedded screenshot has a credit immediately below it and is listed in the screenshot licensing and sample-photo attribution records.

## Done

Report the final file sizes of each screenshot and the PDF.
