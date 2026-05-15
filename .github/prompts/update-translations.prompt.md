---
description: "Audit and fill all missing translations for de, fr, it, and rm"
name: "Update translations"
agent: "translator"
---

## Goal

Ensure every UI string in all four locales (de, fr, it, rm) has a translation.
`scripts/populate_translations.py` is the canonical source of truth.

## Steps

1. **Regenerate the translation files** to pick up any new or changed source strings:
   ```
   .venv\Scripts\python.exe scripts\regenerate_translations.py
   ```
   On macOS/Linux use `.venv/bin/python` instead.

2. **Identify untranslated entries** across all locales using `babel`.
   Use `read_po()` — not a regex — to avoid false positives from multiline `msgstr`:
   ```python
   from babel.messages.pofile import read_po
   from pathlib import Path

   LOCALES = Path("src/exif_turbo/i18n/locales")
   for lang in ["de", "fr", "it", "rm"]:
       po_path = LOCALES / lang / "LC_MESSAGES" / "exif_turbo.po"
       with po_path.open("rb") as fh:
           catalog = read_po(fh)
       missing = [m for m in catalog if m.id and not m.string]
       print(f"{lang}: {len(missing)} untranslated")
       for m in missing:
           print(f"  {repr(m.id)}")
   ```

3. **If 0 untranslated across all locales** → report "All translations up to date" and stop.

4. **For each untranslated string**, produce translations for every locale that
   is missing it (de, fr, it, rm). Respect the conventions in the agent:
   - Preserve `%1`/`%2` and `{}` / `{name}` placeholders
   - Keep `&` accelerator markers (relocate to a natural letter in the target language)
   - QML unicode escapes: use `\\u2026` as the dict key, actual `…` in the value
   - Do not translate proper nouns: `ExifTool`, `GeoHack`, `Google Maps`, `OpenStreetMap`

5. **Add all new translations to `scripts/populate_translations.py`**:
   - Find the thematic section that best fits the strings (or create a new
     `# ── <Topic> ──` section).
   - Add the key/value pair to each locale sub-dict that is missing it.
   - Never overwrite an existing non-empty `msgstr`.

6. **Re-run the full pipeline** to apply and compile:
   ```
   .venv\Scripts\python.exe scripts\regenerate_translations.py
   ```

7. **Verify** by re-running the babel check from Step 2. Confirm 0 untranslated
   in all four locales.

8. **Report** a summary:
   - Number of strings translated per locale
   - Any strings that were skipped and why (e.g. proper nouns left as-is)
   - Offer to commit the changes if the user has not already asked to do so
