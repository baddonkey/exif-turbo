# Custom Tagging Specification

Status: Implemented

This document describes EXIF Turbo's custom-tagging workflow. Tagging is
non-destructive: sidecars hold user-created tags and embedded-keyword exclusion
choices; the original image is never modified by tagging.

## 1. Scope

- Users can add and remove their own text tags on the focused image.
- Previously used custom tags are remembered per database and offered as
  suggestions.
- Users can exclude individual keywords embedded in an image, or exclude all
  embedded keywords from derivatives.
- Copy Tags can apply custom tags and exclusion choices to marked images, the
  complete current result set, or the current Browse folder.
- Tagged derivatives are copies. The exporter writes custom tags and included
  embedded keywords to XMP Subject and IPTC Keywords on the copy only.
- There is no controlled vocabulary lookup, AI tag suggestion, proposal review,
  or vocabulary-vector generation. AI image search and AI-Scan remain separate
  image-indexing features.

## 2. Sidecar Contract

For `photo.jpg`, the adjacent sidecar is `photo.jpg.sidecar.json`. It is plain
UTF-8 JSON and is authoritative for custom tags and embedded-keyword
exclusions. Database rows and FTS text are rebuildable caches.

```json
{
  "schema_version": 1,
  "source": {
    "filename": "photo.jpg",
    "size": 2841032,
    "mtime_ns": 1786200000000000000
  },
  "updated_at": "2026-08-09T12:30:00Z",
  "tags": [],
  "free_tags": ["Family", "Summer 2026"],
  "excluded_embedded_tags": ["Private"],
  "exclude_all_embedded_tags": false
}
```

`tags` remains in the serialized shape for compatibility with existing sidecars;
new custom-tag writes leave it empty. Readers accept the existing schema versions
1 and 2 so the migration can safely parse and clear old controlled tags. The
migration does not downgrade an existing schema version.

`free_tags` are NFC-normalized, trimmed, non-empty strings without control
characters and unique ignoring case. `excluded_embedded_tags` follow the same
normalization and uniqueness rules. `exclude_all_embedded_tags` defaults to
`false`. Unknown top-level and source fields are preserved when a sidecar is
rewritten.

Sidecars are not encrypted by SQLCipher. They inherit the permissions and
backup policy of the directory containing the original.

## 3. Persistence and Search

The sidecar repository performs revision-checked writes using a temporary
sibling file and atomic replacement. An external edit that changes the sidecar
revision causes a conflict instead of a silent overwrite. Malformed or
unsupported sidecars are left untouched and reported.

The encrypted database caches per-image free tags, a reusable custom-tag
catalog, and sidecar synchronization state. FTS5 indexes custom labels together
with the existing image metadata. Embedded keywords continue to come from the
image metadata index; exclusions affect derivative output, not the source
metadata or search index.

New databases do not create controlled-tag, alias, or proposal tables. On the
first unlock after upgrading, a one-time migration:

1. Reads each indexed image's sidecar.
2. Clears legacy controlled tags with revision-checked atomic writes while
   preserving custom tags, exclusions, schema version, and unknown fields.
3. Drops legacy controlled-tag and proposal cache tables and rebuilds tag FTS
   text from remaining custom tags.
4. Records completion only when all sidecar rewrites succeeded.

If a sidecar cannot be read or safely rewritten, the original and sidecar are
left intact, cached controlled-tag data is purged, and the migration retries on
a later unlock. Original image files are never opened for writing by this
migration.

Sidecar synchronization also strips any residual controlled tags before
updating the custom-tag cache, so a later folder refresh cannot restore them.

## 4. Copy Tags

The focused image is excluded from its own target set. In **Add** mode, custom
tags are merged case-insensitively and embedded exclusions are merged. In
**Replace** mode, target custom tags and exclusion settings are replaced by the
source values. Individual exclusions copy only when the corresponding embedded
keyword exists on the target. The ignore-all setting is copied in either mode.

Copy operations run in a background worker, report per-image progress, and can
be canceled. Already completed sidecar writes remain in place if canceled.

## 5. Tagged Derivatives

The derivative exporter preserves source formats and relative folder structure,
requires an output directory outside indexed source roots, and never copies
sidecars. It merges custom free tags with embedded keywords that are not
excluded, removes case-insensitive duplicates, then writes and verifies XMP
Subject and IPTC Keywords on a temporary copy before finalizing it.

Images with no custom tags or included embedded keywords are skipped, as are
existing destinations. Failed or canceled writes do not modify the original.
"