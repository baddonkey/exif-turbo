# EXIF Turbo Project Specification

## 1. Overview

EXIF Turbo is a cross-platform desktop application and CLI for indexing,
searching, browsing, and non-destructively tagging image libraries. It extracts
metadata with ExifTool, stores the searchable index in SQLCipher, and exposes
full-text search through SQLite FTS5. Optional CLIP image vectors support
semantic image search and AI-Scan.

Tagging is custom-only. Users create their own text labels, reuse remembered
labels, exclude embedded keywords from derivatives, and copy tag settings
between images. There is no controlled-vocabulary lookup, AI tag suggestion, or
proposal-review workflow. AI image search and AI-Scan are unaffected.

## 2. Product Goals

- Index large image and video libraries with parallel metadata extraction.
- Search EXIF, IPTC, XMP, custom tags, filenames, paths, and capture dates.
- Keep original media files unchanged during indexing, tagging, and derivatives.
- Store custom tags and embedded-keyword exclusions in adjacent sidecars.
- Generate tagged derivative copies outside indexed source folders.
- Keep the application and its search index local to the user's machine.

## 3. Technology

| Area | Technology |
|---|---|
| Language | Python 3.11+ |
| UI | PySide6, QML / Qt Quick |
| Database | SQLCipher with SQLite FTS5 |
| Metadata | ExifTool (`-g1 -j`) |
| Image AI | OpenCLIP and FAISS for optional semantic image search |
| Tests | pytest, pytest-qt, pytest-timeout |
| Packaging | PyInstaller, WiX, platform-native macOS/Linux build scripts |

## 4. Architecture

The source uses a `src/` package layout with domain and persistence code kept
separate from the Qt/QML adapter.

```text
src/exif_turbo/
  data/                 SQLCipher repositories and connection helpers
  indexing/             filesystem scan, metadata extraction, image AI indexing
  models/               image, folder, search, and sidecar data types
  tagging/              sidecar I/O, synchronization, custom tags, derivatives
  ui/
    models/             Qt list models
    qml/                Search, Browse, settings, and custom-tag drawer
    view_models/        AppController and settings adapter
    workers/            indexing, search, maintenance, and export workers
  utils/                AI device, cache, rendering, and path helpers
```

`ImageIndexRepository` owns SQLCipher access. `FilesystemSidecarRepository`
provides optimistic revision checks and atomic replacement. `TaggingService`
coordinates custom-tag sidecar writes with derived cache updates. The
`SidecarSynchronizer` reconciles sidecars found during indexing or an explicit
folder refresh. `DerivativeExportService` writes metadata only to temporary
copies and verifies the result before publication.

## 5. Data and Search

The primary `images` table stores file identity, EXIF JSON, timestamps, and
mark state. `images_fts` indexes paths, filenames, metadata text, and custom tag
text. Custom tagging adds:

- `image_free_tags`: normalized labels assigned to each indexed image.
- `free_tag_catalog`: remembered labels and their preferred spelling.
- `image_sidecar_state`: sidecar path, revision, schema version, and sync status.
- `completed_migrations`: one-time application data migrations.

New databases do not create controlled-tag, alias, vocabulary-search, or AI
proposal tables. Legacy databases drop those tables during the custom-only
migration while preserving image records, custom tags, and search metadata.

## 6. Sidecar and Tagging Contract

For `photo.jpg`, the adjacent authoritative sidecar is
`photo.jpg.sidecar.json`. It contains `source`, `updated_at`, `tags`,
`free_tags`, `excluded_embedded_tags`, and `exclude_all_embedded_tags`. The
`tags` array remains readable only so older sidecars can be safely migrated;
new writes leave it empty. Both currently supported sidecar schema versions are
readable, and unknown fields are preserved.

Custom free tags are trimmed, NFC-normalized, non-empty, and unique ignoring
case. They are indexed in FTS5 and the remembered-tag catalog. Embedded-keyword
exclusions are persisted per image and affect derivative output, not the
original metadata or existing EXIF search.

The first unlock after upgrade runs a one-time cleanup. It rewrites legacy
tagged sidecars using revision-checked atomic writes, preserving custom tags,
exclusions, schema version, and unknown fields. It purges legacy controlled-tag
caches and rebuilds tag FTS from custom labels. If a sidecar cannot be safely
rewritten, it is left intact and cleanup retries on a later unlock. Original
image files are never modified.

Sidecars are plain JSON and are not encrypted by SQLCipher. Their protection
and backup policy follows the containing source folder.

## 7. Custom Tag Workflows

The Search/Browse tagging drawer supports:

- Add/remove custom labels and reuse remembered labels.
- Exclude individual embedded keywords or ignore all embedded keywords for
  derivative output.
- Copy tags and exclusions to marked images, all current search results, or
  the current Browse folder. Add merges; Replace substitutes. The source image
  is excluded, and per-keyword exclusions transfer only when present on the
  target.
- Preview the final deduplicated custom and embedded keyword set for a
  derivative.

Tagged derivatives preserve source formats and relative folder structure.
The output folder must be outside indexed roots. Existing destinations and
images with no included keywords are skipped. ExifTool writes XMP Subject and
IPTC Keywords to the copy only; originals and sidecars are never copied or
modified.

## 8. AI Image Search

CLIP and FAISS remain dedicated to image embeddings and semantic image search.
AI-Scan and AI Full Scan build or refresh image vectors per indexed folder.
Vector indexes are stored separately from the metadata database and remain
image-only. No vocabulary term vectors or tag-suggestion inference are built.

AI features are disabled on macOS Intel when the supported PyTorch runtime is
unavailable.

## 9. Build and Test

Install the package in the project environment with `pip install -e .`. Run
focused tests with pytest; run the full Qt suite using the repository's
process-isolated test runner on Windows when native Qt teardown requires it.

Build and release scripts package the application, ExifTool, and required
runtime licenses. No Wikidata/TGM vocabulary datasets, curation scripts, or
proposal/vector assets are part of the application payload.
