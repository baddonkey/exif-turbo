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
- Launch the QML application, drive it through all six UI states, and save PNGs to `docs/screenshots/`

```powershell
.venv\Scripts\python.exe scripts/take_screenshots.py
```

Wait for the script to finish (it takes 1–3 minutes). Confirm that all six screenshots were saved and that their file sizes are well above 100 KB (blank captures are typically < 50 KB).

### 3. Generate the PDF

```powershell
.venv\Scripts\python.exe scripts/export_manual_pdf.py
```

Confirm that `docs/user-manual.pdf` was created and is larger than 1 MB (a PDF without embedded screenshots will be much smaller).

## Done

Report the final file sizes of each screenshot and the PDF.
