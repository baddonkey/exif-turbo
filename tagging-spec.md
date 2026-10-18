# Custom Tagging Specification

Status: Implemented

This document describes EXIF Turbo's custom-tagging workflow. Tagging is
non-destructive: sidecars hold user-created tags and embedded-keyword exclusion
choices; the original image is never modified by tagging.

## 1. Scope

- Users can add and remove their own text tags on the focused image, and append
  or replace a multiline custom description.
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
  "description": "Family picnic beside the lake.",
  "exclude_embedded_description": false,
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

`description` is an optional string, defaulting to empty for older sidecars.
It is NFC-normalized, trimmed at its boundaries, and uses LF line endings.
Internal newlines and tabs are preserved; other control characters are rejected.
Append adds a new paragraph separated by one blank line and rejects empty input.
Replace substitutes the entire custom description; empty input clears it.
Embedded image descriptions are separate and never modified by these operations.
This additive field does not promote the sidecar schema version.

`exclude_embedded_description` is an optional boolean, defaulting to `false`.
When true, derivative export clears embedded descriptions even if the custom
description is empty. It is independent of custom description editing: source
metadata and its search index remain intact, and original bytes never change.
Tag edits and Copy Tags preserve the target's flag rather than copying it.

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

Custom descriptions are cached in the encrypted database and indexed alongside
custom tags in the existing sidecar FTS text. Scans and Refresh Tags import
external description edits; deleting a sidecar clears its cached description.
Tag edits, Copy Tags, and legacy cleanup preserve descriptions. Copy Tags does
not copy descriptions. Derivative export appends the saved custom description
to the included embedded description, separated by one blank line, and writes
the combined text to XMP-dc Description on the copy only. Existing description
fields are cleared first to avoid stale alternate captions, and readback must
match the combined text before finalizing. Without custom text, existing
description fields are preserved unless explicitly excluded.
The embedded-description exclusion flag is nevertheless applied to exported
copies, with verified removal of XMP Description (including language variants),
IPTC Caption-Abstract, EXIF ImageDescription/UserComment, XMP UserComment,
PNG Description, and QuickTime Description. Failed removal/readback prevents
finalizing the copy.

## Description Editing and MCP

The tagging drawer uses two independently scrollable columns. The left contains
Custom tags, Custom description, Copy Tags, and Copy Description. The right
contains Existing image tags and Existing embedded description, in that order.
Final derivative tags and Final derivative description are side-by-side previews
in a shared, always-visible bottom row outside both scrollable columns.

The tagging drawer shows the saved custom description in one multiline editor.
Save replaces the entire custom description; saving empty text clears it.
Enter saves, while Shift+Enter inserts a newline. There is no focus-loss autosave.
It also displays embedded descriptions separately, including ExifTool's
`IFD0:ImageDescription` family-1 key and XMP language variants, normalizing
CR/CRLF line endings for display. Excluded embedded text remains inspectable
with a strike-through. Embedded and custom empty states are explicitly labeled.
The bottom Final derivative description preview uses the same composition as
export: included embedded text followed by saved custom text. Drafts do not
affect it until saved. The preview is read-only and vertically scrollable.
Drafts are protected against selection changes and concurrent saved-value edits.
Description writes reuse atomic, revision-checked sidecar persistence and report
conflicts and partial cache failures rather than silently overwriting data.

MCP exposes `set_image_description(image_id, path, description, mode)` and
`set_image_descriptions_batch(updates)`. Mode is explicitly `append` or `replace`;
the image ID and path must match an image in the active database. Batches accept
at most 100 updates and report per-image outcomes, including the resulting
description and whether it changed. Description reads are included in selected
image payloads/resources and paginated set-image listings.
`set_image_description_excluded(image_id, path, excluded)` sets the exclusion
flag independently, without requiring replacement text. Read payloads also expose
`exclude_embedded_description`.

## 4. Copy Tags

### MCP embedded-tag exclusions

`set_image_embedded_tag_excluded(image_id, path, tag, excluded)` toggles a
case-insensitive individual keyword exclusion.
`set_image_all_embedded_tags_excluded(image_id, path, excluded)` independently
toggles ignore-all. Set `excluded=False` to restore inclusion. Toggling ignore-all
preserves individual exclusions; restoring an individual keyword does not
override an enabled ignore-all flag.

Both tools validate positive IDs, nonempty paths, boolean flags, and (for
individual exclusions) nonempty normalized tag strings. The ID/path must match
an image indexed in the active, unlocked database with tagging enabled.
Mutations run on the UI-owning thread through the existing dispatcher and
reuse atomic, revision-checked sidecar persistence. Errors are returned to MCP
clients; cache failures are reported as partial failures.
Responses include `excluded_embedded_tags`, `exclude_all_embedded_tags`, and
`changed`, with repeated identical requests returning `changed=False`.
Selected-image reads/resources and paginated set-image listings include both
settings. Custom tags, descriptions, drafts, originals, and source metadata/search
remain unchanged, and the selected image's derivative preview refreshes.

### Copying tags

The focused image is excluded from its own target set. In **Add** mode, custom
tags are merged case-insensitively and embedded exclusions are merged. In
**Replace** mode, target custom tags and exclusion settings are replaced by the
source values. Individual exclusions copy only when the corresponding embedded
keyword exists on the target. The ignore-all setting is copied in either mode.

Copy operations run in a background worker, report per-image progress, and can
be canceled. Already completed sidecar writes remain in place if canceled.

### Copy Description

Copy Description uses the same target scopes, source exclusion, background
progress, cancellation, and per-image result reporting as Copy Tags.
Only the saved custom description is copied; drafts, embedded descriptions,
tags, and exclusion flags are not copied. **Add** appends the source text as a
new paragraph separated by one blank line, and rejects empty source text.
**Replace** replaces each target's custom description and can clear it when the
source is empty. Replacement and clearing require confirmation in the UI.
Each mutation reuses revision-checked sidecar writes and updates the searchable
description cache. Conflicted or malformed sidecars are reported individually
without preventing subsequent targets from being processed.

## 5. Tagged Derivatives

The derivative exporter preserves source formats and relative folder structure,
requires an output directory outside indexed source roots, and never copies
sidecars. It merges custom free tags with embedded keywords that are not
excluded, removes case-insensitive duplicates, then writes and verifies XMP
Subject and IPTC Keywords on a temporary copy before finalizing it.

Images with no custom tags or included embedded keywords are skipped, as are
existing destinations. Failed or canceled writes do not modify the original.
"