# EXIF Turbo Tagging Specification

Status: Implemented (version 1; release validation and LOC redistribution review remain open)

This document is the product and technical contract for non-destructive image
tagging in EXIF Turbo. Sections 1-16 describe the implemented version 1
contract; sections 17-18 record remaining release questions and decisions.

### Implementation status (2026-08-09)

The end-to-end feature is implemented:

- Adjacent schema-v1 `<complete-image-filename>.sidecar.json` files are plain
  UTF-8 JSON and authoritative for accepted tags. Atomic revision-checked
  writes preserve unknown fields and never write the original image.
- Official TGM v1 XML is downloaded first, with official tagged text as
  fallback. Canonical merged `TNR` values become `loc-tgm:tgmNNNNNN`; `UF` and
  non-descriptor `USE` terms resolve as aliases; postable subject and
  genre/form categories are selectable.
- SQLCipher caches accepted tags, aliases, sidecar synchronization state, and
  pending/rejected proposals. `images_fts.tags_text` contains accepted labels,
  IDs, categories, vocabulary identity, and active aliases.
- The Search/Browse tag button and `Ctrl+T` open the non-modal QML drawer. It
  provides canonical/alias search, selected-image add/remove, marked-image
  aggregation and bulk add/remove, proposal generation and review, confirmed
  optional auto-accept, derivative output selection, progress, cancellation,
  and summaries. Existing persistent marks and the `Space` toggle are reused.
- Proposal generation requires AI enabled, an explicit image AI scan, and an
  independently built TGM term-vector index. Defaults are 0.24 for proposals
  and 0.32 for auto-accept; auto-accept is disabled by default and its threshold
  is kept at least 0.01 above the proposal threshold.
- Derivatives preserve source format and relative trees, require an output root
  outside indexed sources, skip untagged/existing destinations, write and
  verify XMP Subject plus IPTC Keywords on temporary copies, and never copy
  sidecars or overwrite originals.

Known version 1 limitations include no sidecar encryption/relocation/cloud
sync, no generic or additional vocabulary import, no hierarchical tag browser,
no OCR provider, no derivative format conversion/custom mapping/overwrite,
and no automatic image-vector creation during proposal generation. Bulk
add/remove currently executes directly after the drawer action; only bulk
auto-accept and derivative generation have confirmation dialogs.

## 1. Summary

EXIF Turbo will let users assign controlled terms to indexed images without
modifying the original files. Accepted tags are stored in adjacent JSON
sidecars. A normalized copy in the encrypted SQLite database makes those tags
available to the existing full-text search.

The first supported controlled vocabulary is the Library of Congress
Thesaurus for Graphic Materials (TGM). Existing CLIP image vectors are compared
with a separate index of TGM term vectors to propose tags. Users may review
proposals or explicitly enable automatic acceptance above a configured
threshold.

Marked images form the working set for bulk tagging and derivative generation.
Derivative generation copies each original into an output tree and writes the
accepted canonical TGM labels to the copy's XMP and IPTC metadata. Original
images are never metadata-write targets.

## 2. Goals

- Keep original image and media files byte-for-byte unchanged during tagging.
- Store accepted tags in portable sidecars beside their source images.
- Make accepted sidecar tags available to the existing SQLite FTS5 search.
- Support fast keyboard-oriented tagging of one image or a marked set.
- Propose canonical TGM terms using existing CLIP image vectors.
- Support review-first proposals and optional threshold-based auto-acceptance.
- Generate tagged derivatives without modifying originals.
- Leave clear extension points for later thesauri and OCR proposal providers.

## 3. Non-goals for Version 1

- Modifying metadata in an original image.
- Generic CSV, JSON, SKOS, RDF, or user-defined thesaurus import.
- Configuring more than one controlled vocabulary.
- OCR extraction or OCR-based proposals.
- Sidecar encryption or cloud synchronization.
- Automatic sidecar relocation after an external image rename or move.
- Hierarchical tag browsing or tag facets in the main search UI.
- Custom metadata mappings or JPEG conversion during derivative export.
- Automatically overwriting an existing derivative.
- Automatically accepting CLIP proposals unless the user enables that mode.

## 4. Terminology

**Original**
: The indexed image or media file. Tagging must not write to this file.

**Sidecar**
: The JSON file adjacent to an original that is the authoritative store for its
accepted tags.

**Accepted tag**
: A canonical postable TGM concept deliberately accepted by the user or by an
explicitly enabled auto-accept rule.

**Proposal**
: A ranked TGM concept suggested by CLIP or, later, another provider. A pending
or rejected proposal is not an accepted tag.

**Mark**
: EXIF Turbo's existing database-backed checkbox state. Marks define the
working set for bulk operations; they are not tags.

**Derivative**
: A copy of an original created under a user-selected output root. EXIF Turbo
may write accepted tags into the derivative's metadata.

## 5. Invariants

1. Tagging, proposal generation, sidecar synchronization, and search indexing
   never write an original image.
2. A sidecar is the source of truth for accepted tags. SQLite and FAISS data
   are rebuildable indexes and caches.
3. Only accepted tags are included in full-text search and derivative metadata.
4. A pending or rejected proposal never changes a sidecar.
5. TGM aliases always resolve to one canonical postable concept before a tag is
   stored.
6. ExifTool receives only derivative paths for metadata-write operations.
7. A failed sidecar write leaves the last valid sidecar intact.
8. A failed TGM update leaves the last valid normalized TGM snapshot active.

## 6. Sidecar Contract

### 6.1 Location and name

For an original named `photo.jpg`, the sidecar is:

```text
photo.jpg.sidecar.json
```

The complete original filename, including its extension, is retained. This
avoids collisions between files such as `photo.jpg` and `photo.tif`.

The sidecar lives in the same directory as the original. If that directory is
read-only, EXIF Turbo reports the image as non-writable for tagging and does not
fall back to hidden or central storage.

### 6.2 Version 1 schema

```json
{
  "schema_version": 1,
  "source": {
    "filename": "photo.jpg",
    "size": 2841032,
    "mtime_ns": 1786200000000000000
  },
  "updated_at": "2026-08-09T12:30:00Z",
  "tags": [
    {
      "concept_id": "loc-tgm:tgm000001",
      "label": "Example canonical TGM term",
      "vocabulary": "loc-tgm",
      "category": "subject",
      "provenance": {
        "method": "manual",
        "accepted_at": "2026-08-09T12:30:00Z",
        "confidence": null,
        "model": null,
        "vocabulary_checksum": "sha256:example"
      }
    }
  ]
}
```

The example identifier and label illustrate structure only and are not a real
TGM record pair.

### 6.3 Field rules

| Field | Rule |
|---|---|
| `schema_version` | Required integer. Version 1 readers reject newer unsupported versions without rewriting them. |
| `source.filename` | Required original filename snapshot for diagnostics. It is not used to locate another file. |
| `source.size` | Optional non-negative byte-size snapshot. |
| `source.mtime_ns` | Optional non-negative modification-time snapshot. |
| `updated_at` | Required UTC RFC 3339 timestamp written after a successful mutation. |
| `tags` | Required array, unique by `concept_id`. Order is deterministic by canonical label and then ID. |
| `concept_id` | Required qualified TGM identifier `loc-tgm:tgmNNNNNN`. |
| `label` | Required canonical-label snapshot from the active TGM version when accepted. |
| `vocabulary` | Required value `loc-tgm` in version 1. |
| `category` | Required `subject` or `genre_format`. |
| `provenance.method` | Required `manual` or `clip`. `ocr` is reserved for a later version. |
| `provenance.accepted_at` | Required UTC RFC 3339 timestamp. |
| `provenance.confidence` | Required number from 0 through 1 for CLIP auto-acceptance; otherwise nullable. |
| `provenance.model` | Required CLIP model fingerprint for CLIP auto-acceptance; otherwise nullable. |
| `provenance.vocabulary_checksum` | Required checksum of the normalized TGM snapshot used to accept the term. |

In version 1, "manual" means that a user selected or accepted a TGM concept.
Free-text tags are not supported.

Readers preserve unknown object fields at the top level and within tag records
when rewriting a supported schema version. Unknown fields do not become FTS
content automatically.

### 6.4 Atomic writes and conflicts

The filesystem sidecar repository must:

1. Read and validate the current sidecar.
2. Compare its revision fingerprint with the revision last presented to the
   mutation command.
3. Refuse the write if an external process changed the file.
4. Serialize deterministic UTF-8 JSON with a final newline.
5. Write and flush a uniquely named temporary sibling file.
6. Replace the destination with `os.replace` only after validation succeeds.
7. Remove a remaining temporary file after failure where possible.

The revision fingerprint is the sidecar's SHA-256 checksum plus file stamp. A
conflict is shown to the user and requires reload before retry. EXIF Turbo never
silently merges or overwrites an external edit in version 1.

### 6.5 Rename, deletion, and malformed files

- EXIF Turbo does not infer external image renames. Users or external tools
  must move the adjacent sidecar with the image.
- Removing an image from the index removes only database cache rows. It does
  not delete the sidecar.
- Deleting a sidecar causes accepted tags to disappear from the database cache
  and FTS after synchronization.
- A malformed or unsupported sidecar remains untouched. The last cached tags
  may be displayed as stale but must not be silently treated as current.

## 7. TGM Contract

### 7.1 Authoritative source

Version 1 uses the official Library of Congress TGM distribution:

- Preferred: the quarterly XML distribution.
- Fallback: the quarterly tagged ASCII distribution.
- Information page: <https://guides.loc.gov/tgm-i/download-tgm>
- Field definitions: <https://www.loc.gov/pictures/collection/tgm/fields.html>
- Application guidance: <https://guides.loc.gov/tgm-i>

The application records the source URL, source format, LOC distribution date
when available, import time, byte size, and SHA-256 checksum. A normalized
snapshot is stored in per-database application data. The downloaded source is
never modified.

The 2026-07-29 distribution contains 13,341 term records and 13,337 `TNR`
values. Its XML root is `THESAURUS` with repeated `CONCEPT` elements, and its
creation comment is `Created: 7/29/2026 11:55:28 AM`. The tagged-text fallback
starts with the same timestamp and uses blank-delimited records: an unindented
term followed by indented `TAG:` fields. Indented continuation lines append to
the preceding field.

TGM content must not be bundled with EXIF Turbo until its redistribution and
attribution terms have been reviewed for the chosen release channel. An
on-demand download is the default implementation assumption until that review
is complete.

### 7.2 Identity and normalization

The merged TGM control number (`TNR`, such as `tgm000001`) is the stable concept
identifier. EXIF Turbo qualifies it as `loc-tgm:<TNR>`.

The importer preserves these fields when present:

- Canonical term and postable/nonpostable state.
- `USE` and `UF` equivalence relationships.
- `BT`, `NT`, and `RT` semantic relationships.
- Scope, facet, cataloger, history, and former-usage notes.
- Former `lctgm` and `gmgpc` control numbers.
- `TTCSubj`, `TTCForm`, `TTCRef`, and `TTCSubd` term categories.

Only postable `TTCSubj` and `TTCForm` concepts are selectable tags and CLIP
candidates. `TTCSubj` maps to `subject`; `TTCForm` maps to `genre_format`.
Reference and subdivision records remain available to normalization but are not
accepted as standalone image tags in version 1.

Nonpostable terms and `UF` terms are aliases. Type-ahead and FTS may match an
alias, but acceptance stores the target canonical concept ID and label.

The official 2026-07-29 source has four records without `TNR`: descriptors
`Antennas`, `Giants`, and `Strip tease`, plus non-descriptor `Sun rays` which
uses `Sunlight`. These records are skipped with diagnostics; an equivalent
alias may still be supplied by a canonical record's `UF` field.

The source also assigns `tgm013479` to descriptor `Chair caning` and to
non-descriptor `Crevasses`, which uses `Fissures`. A canonical descriptor wins
a TNR collision with a non-descriptor; the colliding non-descriptor is skipped
with a diagnostic. More generally, two different canonical descriptors sharing
a TNR invalidate the candidate snapshot.

Unresolved `USE` labels and unresolved optional `BT`, `NT`, or `RT` labels are
preserved as diagnostics and do not reject an otherwise valid snapshot. This
accommodates source encoding and data anomalies without inventing relationships.
Malformed required structure, conflicting canonical TNRs, or a candidate with
no selectable canonical concept remains invalid. Managed official updates also
require a configurable selectable-concept sanity minimum, defaulting to 7,000,
to prevent activation of a truncated distribution.

### 7.3 Managed installation and updates

Settings exposes:

- Installed/not-installed state.
- Distribution/source date and checksum.
- Counts of canonical subject and genre/format concepts.
- Install/update, build/rebuild vectors, per-database enable/disable, and
  diagnostics.

An update is an explicit user action. EXIF Turbo downloads into a temporary
location, verifies transport success, parses and validates the complete file,
writes a normalized candidate snapshot, and atomically activates it. Any error
leaves the previous snapshot and term-vector index active.

No arbitrary thesaurus file picker is exposed in version 1.

## 8. Database and Full-Text Search

### 8.1 Storage model

The encrypted SQLite database stores normalized, rebuildable state:

- Accepted tags linked to `images.id` with cascade deletion.
- Sidecar path, stamp, checksum, schema version, and synchronization status.
- Pending and rejected proposal state.
- Normalized TGM concepts, aliases, relationships, and installation metadata.

Exact table names and columns are implementation details, but foreign keys and
uniqueness constraints must enforce one accepted concept per image.

### 8.2 FTS migration

`images_fts` changes from:

```sql
fts5(path, filename, metadata_text)
```

to:

```sql
fts5(path, filename, metadata_text, tags_text)
```

The migration rebuilds FTS transactionally for existing images. FTS-row update
logic is centralized so:

- Reindexing image metadata preserves `tags_text`.
- Updating tags preserves `metadata_text`.
- Removing a sidecar clears only its tag-derived search content.

`tags_text` contains accepted canonical labels, qualified IDs, TGM identity,
category, and known aliases from the active normalized TGM snapshot. Pending and
rejected proposals are excluded.

Existing FTS syntax remains unchanged. A user can search by a canonical label,
an alternate term, or a qualified TGM ID.

### 8.3 Synchronization

Regular and full scans include a sidecar synchronization pass. Sidecar stamps
must be checked even when image size and mtime are unchanged. The pass handles
created, changed, deleted, malformed, and unsupported sidecars without writing
the original image.

If a sidecar write succeeds but the SQLite update fails, the sidecar remains
authoritative. The image is marked cache-stale and resynchronized from that
sidecar. Valid user sidecar data is never deleted to roll back a cache failure.

## 9. CLIP Proposal System

### 9.1 Separate vector indexes

The existing image FAISS index remains image-only. A new TGM term index stores
one normalized 512-dimensional vector for each canonical postable subject or
genre/format concept.

The TGM index is keyed by:

- TGM source checksum.
- Normalization version.
- Prompt version.
- CLIP model and pretrained-weight fingerprint.

Changing TGM rebuilds only the term index. Existing image vectors do not need
to be recomputed.

### 9.2 Term encoding

Each term vector is generated from a controlled, versioned prompt containing
the canonical term and useful alternate terms. Cataloger and history notes are
not sent into the model. The prompt format is fixed for an index version so
proposal scores remain reproducible.

### 9.3 Proposal lifecycle

For each selected image, the proposal service:

1. Retrieves its existing CLIP vector.
2. Searches the TGM term index.
3. Applies the configured proposal threshold.
4. Resolves aliases and deduplicates by canonical concept ID.
5. Excludes concepts already accepted or explicitly rejected for the current
   TGM/model fingerprint.
6. Persists ranked pending proposals in SQLite.

Missing image vectors produce an actionable "AI scan required" state. Proposal
generation does not implicitly load originals or build image vectors.

Review-first is the default. Optional auto-acceptance requires a separate,
explicit setting and threshold. Every auto-accepted tag records its score, CLIP
fingerprint, TGM checksum, and acceptance time in the sidecar.

Rejected proposals are operational state and remain in SQLite. They are
invalidated or reevaluated when the TGM, prompt, or CLIP fingerprint changes.

### 9.4 Future providers

A `TagProposalProvider` boundary returns canonical proposal IDs, labels,
categories, scores, and provenance. CLIP/TGM is the first provider. A later OCR
provider must use the same acceptance service and cannot write sidecars
directly.

## 10. Tagging User Experience

### 10.1 Workbench

A docked tagging workbench is available from Search and Browse through a tag
icon and keyboard shortcut. For the focused image it shows:

- Accepted canonical TGM tags.
- TGM type-ahead over canonical and alternate terms.
- Ranked proposals with confidence and provider.
- Subject or genre/format category.
- Accept, reject, and remove actions.
- Sidecar synchronization or write errors.

The workbench is an operational tool, not a separate landing page.

### 10.2 Bulk tagging

The existing marked-image state is reused as the bulk working set. The
workbench shows the marked count and aggregate tag state:

- `all`: every marked image has the concept.
- `some`: only part of the marked set has the concept.
- `none`: no marked image has the concept.

Users can add or remove a concept across marks, apply a type-ahead result to all
marks, or generate proposals for marks. Bulk auto-acceptance requires
confirmation; bulk add/remove currently starts directly from its drawer
button. Operations run in cancellable QThreads with per-image progress and a
final summary of succeeded, skipped, conflicted, and failed items.

Space remains the mark toggle. `Ctrl+T` opens/closes the drawer; opening focuses
TGM search. `Enter` applies the highlighted type-ahead result to the focused
image and `Down` navigates type-ahead results. Proposal accept/reject and apply
to marked are currently explicit drawer buttons.

### 10.3 Mutation boundary

All manual, proposal, and bulk mutations use one application service. For each
image it checks the sidecar revision, performs the atomic sidecar write, updates
normalized SQLite rows and FTS, and emits model/controller updates. Neither QML
nor a proposal provider writes a sidecar directly.

## 11. Derivative Generation

### 11.1 Input and layout

Derivative generation operates on marked images. The user chooses an output
root that must not be inside an indexed source root. Paths are reproduced
relative to each indexed root. Multiple roots receive deterministic,
collision-safe root labels.

Version 1 preserves the source format and uses `shutil.copy2` before metadata
writing. Existing output files are skipped and reported; they are never
silently overwritten.

Images without accepted tags are also skipped and reported as untagged. No
untagged derivative or output directory is created for those items.

### 11.2 Metadata mapping

Accepted canonical TGM labels replace these keyword fields on the derivative:

- `XMP-dc:Subject`
- `IPTC:Keywords`

Other copied metadata is preserved. A narrow ExifTool writer adapter invokes
ExifTool with no-backup/overwrite-original behavior against the derivative.
The adapter must reject a target that resolves to an original source path.

If metadata writing or verification fails, EXIF Turbo removes the incomplete
derivative where possible and reports the failure. The source hash and mtime
must remain unchanged.

Sidecars are not copied into the derivative tree in version 1 because their
accepted tag content is embedded in the derivative.

## 12. Security and Privacy

- Sidecars are plain JSON and inherit source-directory permissions. SQLCipher
  database encryption does not protect them.
- TGM downloads use HTTPS and are validated before activation.
- Source checksums provide provenance and change detection, not publisher
  authenticity. Signature verification is unavailable unless LOC supplies a
  verifiable signature mechanism.
- CLIP processing remains local except for existing model/tokenizer downloads.
- Paths and private image metadata are not included in TGM term prompts.
- Derivative output-root validation prevents accidental writes into indexed
  source trees.

## 13. Migration and Rollout

Existing databases migrate automatically. The FTS table is rebuilt while the
database is unlocked. Existing image metadata and marks remain intact.

The first release uses a per-database tagging feature setting. Disabling the UI
does not delete sidecars, cached accepted tags, proposals, or TGM data. Already
synchronized accepted tags remain searchable.

No sidecar is created until the first accepted tag mutation for an image.

Resetting a database clears image/tag/proposal rows, marks, indexed folders,
thumbnail/preview caches, the normalized TGM snapshot, and TGM term-vector
artifacts. It does not traverse source directories or delete adjacent sidecars.
The separate image AI index/map files are not explicitly deleted; AI Full
Rescan is the clean rebuild path after images are indexed again. Re-adding and
scanning folders synchronizes sidecars; TGM must then be reinstalled before
tags can be edited or proposals rebuilt.

## 14. Verification Strategy

### 14.1 Sidecars

- Version 1 round trips, Unicode labels, deterministic output, and final newline.
- Unknown-field preservation and unsupported-version refusal.
- Invalid JSON, duplicate concepts, invalid timestamps, and invalid provenance.
- Atomic replacement, read-only folders, cleanup, and external-edit conflicts.
- Creation, change, and deletion while the image stamp remains unchanged.

### 14.2 TGM

- Representative official XML and tagged-text fixtures.
- Postable/nonpostable records and stable `loc-tgm:<TNR>` identities.
- `USE`/`UF` canonicalization and `BT`/`NT`/`RT` relationships.
- Subject and genre/format category mapping.
- Duplicate IDs, unresolved targets, malformed fields, and update rollback.
- Source provenance, checksums, and term counts.

### 14.3 Search and database

- Legacy database migration and transactional FTS rebuild.
- EXIF terms survive tag updates; tag terms survive image reindexing.
- Canonical labels and aliases are searchable after synchronization.
- Removed tags and deleted sidecars disappear from search.
- Removing an image row never removes a sidecar.

### 14.4 AI proposals

- AI tests always mock CLIP and never download a model.
- Image and TGM indexes remain separate.
- Ranking, thresholding, alias deduplication, rejection, and auto-acceptance.
- TGM, prompt, normalization, and CLIP fingerprint invalidation.
- Missing image vectors produce an actionable state.

### 14.5 Bulk operations and derivatives

- Mixed aggregate tag states, partial completion, cancellation, and conflicts.
- Preserved folder trees, multiple source roots, and destination collisions.
- Exact ExifTool target and XMP/IPTC arguments through a fake process boundary.
- Cleanup after metadata failure and byte-for-byte unchanged originals.
- Optional ExifTool integration test reads keywords back from a derivative.

Focused tests run after each implementation slice. The full suite uses the
repository's file-redirected, unbuffered pytest invocation with timeout
protection. AI tests must never trigger a real CLIP download.

## 15. Implementation Phases

1. Sidecar domain models, filesystem repository, validation, and tests.
2. SQLite tag cache, FTS migration, synchronization, and tests.
3. TGM importer, normalized repository, managed update flow, and tests.
4. TGM term vectors, image-vector lookup, proposal worker, and tests.
5. Single-image and bulk tagging workbench.
6. Derivative export service, ExifTool writer, dialog, and tests.
7. Documentation, translations, manual UX verification, and rollout.

## 16. Acceptance Criteria

Version 1 is complete when:

1. A user can select a canonical TGM tag and EXIF Turbo creates or updates the
   adjacent sidecar without changing the original image.
2. An accepted canonical or alternate TGM term finds the image through existing
   full-text search.
3. TGM can be installed and updated from the official quarterly distribution
   without losing the previous valid version after a failed update.
4. CLIP can propose ranked canonical TGM tags from existing image vectors.
5. Review-first and explicitly enabled threshold auto-acceptance both retain
   complete provenance.
6. A user can apply and remove tags across marked images with progress,
   cancellation, and conflict reporting.
7. A user can generate derivatives that contain canonical TGM labels in XMP
   Subject and IPTC Keywords while original hashes and mtimes remain unchanged.
8. Existing databases migrate without losing images, metadata, marks, or search
   behavior.
9. Focused automated coverage passes without downloading CLIP; release
  validation must separately record any full-suite result.

## 17. Open Decisions

- Confirm LOC redistribution and attribution requirements before deciding
  whether a TGM snapshot may be bundled rather than downloaded on demand.
- Decide how an accepted concept removed or made nonpostable by a later TGM
  release is displayed. The sidecar entry must not be silently deleted.
- Evaluate the implemented 0.24 proposal and 0.32 auto-accept defaults on a
  representative image set before treating scores as production-calibrated.

## 18. Decision Log

| Date | Decision |
|---|---|
| 2026-08-08 | Store tags in adjacent `<complete-image-filename>.sidecar.json` files. |
| 2026-08-08 | Reuse existing marks as the bulk working set. |
| 2026-08-08 | Support review-first proposals and optional explicit auto-acceptance. |
| 2026-08-08 | Preserve source formats and folder trees for derivatives. |
| 2026-08-08 | Write derivative tags to XMP Subject and IPTC Keywords. |
| 2026-08-09 | Use LOC TGM as the sole configured version 1 vocabulary. |
| 2026-08-09 | Prefer official quarterly TGM XML and support tagged ASCII as fallback. |
| 2026-08-09 | Use qualified merged TNR control numbers as canonical tag identities. |
| 2026-08-09 | Defer additional thesauri and generic import formats. |
| 2026-08-09 | Import unresolved optional relationships with diagnostics instead of rejecting the snapshot. |
| 2026-08-09 | Skip official missing-TNR records and non-descriptor TNR collisions; reject conflicting canonical descriptors. |
| 2026-08-09 | Ship review-first defaults of 0.24 proposal and 0.32 auto-accept, with auto-accept disabled and a minimum 0.01 threshold gap. |
| 2026-08-09 | Use `Ctrl+T` for the Search/Browse tagging drawer and retain `Space` for marks. |
| 2026-08-09 | Reset per-database TGM term-vector/cache state but preserve adjacent source sidecars and separately managed image AI files. |