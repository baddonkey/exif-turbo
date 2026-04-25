---
description: "Update the exif-turbo user manual — refresh screenshots, rewrite affected sections, regenerate the PDF"
name: "Update User Manual"
argument-hint: "What changed? (e.g. 'added dark-mode toggle', 'renamed Browse tab')"
agent: "documentation"
tools: [read_file, grep_search, semantic_search, run_in_terminal, replace_string_in_file, create_file]
---

Update the exif-turbo user manual to reflect: **$ARGUMENTS**

## Steps

1. **Understand the change**
   - Read the relevant QML (`src/exif_turbo/ui/qml/`) and Python source
     (`src/exif_turbo/ui/view_models/`) to confirm what actually changed.
   - Do not guess at UI behaviour — verify from source.

2. **Refresh screenshots** (only if the UI changed visually)
   ```
   python scripts/take_screenshots.py
   ```
   The script waits until thumbnails and previews are fully loaded before
   capturing each shot.

3. **Update [docs/user-manual.md](../docs/user-manual.md)**
   - Edit only the sections affected by the change.
   - Follow the existing structure: Installation → First Launch → Indexing →
     Searching → Browsing → Keyboard Shortcuts → CLI → FAQ.
   - Use numbered steps for procedures, bullet lists for features.
   - Reference screenshots as `![caption](screenshots/filename.png)`.

4. **Regenerate the PDF**
   ```
   python scripts/export_manual_pdf.py
   ```
   The PDF is committed to the repo — always regenerate it after editing the
   Markdown source.

5. **Confirm**
   - Open `docs/user-manual.pdf` and verify the changed sections look correct.
   - Report which sections were updated and why.
