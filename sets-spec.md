# Image Sets Specification

Status: Implemented

## 1. Purpose

Image Sets let users organize indexed images into named, persistent collections.
A set has fixed membership that changes through explicit member actions or when
the user reapplies its optional saved filter. Sets are available in Search,
Browse, and the Sets tab. The opt-in local MCP interface can list sets, read
their images, and apply custom tags to indexed images.

Sets organize references to indexed images. They do not copy, move, edit, or
delete image files, and they do not replace the existing custom-tag workflow.

## 2. Scope

- The desktop application provides a **Sets** tab.
- Users create, rename, and delete sets; view their members and optional saved filter.
- Users add the selected image, marked images, all current search results, or all
  images in the current Browse folder.
- Users remove individual members from a set. The current Sets UI does not expose
  bulk removal scopes.
- Users define an optional structured filter and explicitly reapply it in Add or
  Replace mode.
- Sets and memberships are stored in the currently open image-index database.
- The MCP interface enumerates sets, pages through a set's images and
  previews, and writes custom tags to indexed images.

The MCP interface does not create, edit, or delete sets or change their
membership. Sets do not modify image files, embedded keywords, or tag
suggestions.

## 3. Set Management

- Each set has a stable internal ID, a required name, an optional saved filter,
  and zero or more indexed-image members.
- Set names are unique within one database, ignoring case. Renaming preserves
  the set ID and its members.
- Creating a set creates an empty set. The user can then add images using any
  supported target scope.
- Deleting a set requires confirmation and deletes only the set and its
  membership records. It never deletes images, sidecars, or tags.
- Adding an existing member or removing a non-member is an idempotent no-op.
  Bulk operations report how many images were added, removed, skipped, or no
  longer available.
- Removing an image from the index removes its set memberships. Membership is
  not removed merely because an image is outside current search results.
- Membership remains fixed across searches, restarts, and changes to metadata
  until the user explicitly edits it or reapplies the saved filter.

The Sets tab shows the set list and the selected set's members. Set names and
member filenames must remain inspectable without opening each image. The Add
control can target the current selection, marked images, the complete current
search result set, or the current Browse folder. These bulk operations include
the complete scope, not only currently loaded or visible rows. Each member row
has a **Remove** control for removing that image from the set.

Search also provides a set filter. **All sets** includes every indexed image;
selecting a named set restricts results to its members. Search filters do not
change membership.

The Action menu is available on Sets and targets the selected set, independent
of Search filters. Current-results derivative generation uses all set members;
marked-image commands use only marked members of that set. JSON export uses
marked set members when present, otherwise all set members. Deletion retains
the marked-file confirmation and never affects images outside the selected set.
Without a selected set, these actions are disabled. Returning to Search or Browse
restores their normal action scope without changing the Search set filter.

The shared tagging drawer is available on Sets through the tag button or Ctrl+T.
Selecting a member focuses its tags; double-clicking also opens the drawer.
Tag edits and embedded-keyword exclusions apply to that member without changing
the Search image selection. Copy Tags supports the complete selected set or its
marked members, as well as any other named set. Named-set destinations are
also available from Search and Browse and are independent of current Search
filters. The source image is excluded even when it belongs to the destination.
The existing Add/Replace confirmation, progress, and cancel behavior applies.
Switching sets or removing the focused member clears the tagging
selection so subsequent edits cannot target a stale image.

## 4. Saved Filters

A set may have one optional structured filter. Filters are saved as data with
the set and are not evaluated automatically. Reapplying always searches the
entire currently open indexed database, independent of the current Search page
filters, sort order, selected image, and pagination.

### 4.1 Condition fields

Version 1 filters support:

- Indexed text, using the application's regular text-search semantics.
- One or more indexed folders, using the application's existing folder-filter
  semantics.
- File type/extension.
- Capture date, with inclusive lower and upper bounds; either bound may be
  omitted. Images without a capture date do not match a bounded date condition.
- Marked state: marked or unmarked.
- A named metadata field selected from indexed metadata fields.

Named metadata field conditions support equals, not-equals, contains,
not-contains, exists, missing, and numeric greater-than, greater-than-or-equal,
less-than, and less-than-or-equal comparisons. Numeric comparisons apply only
when the stored value and condition value can both be parsed as numbers. A
missing field does not match equals, not-equals, contains, not-contains, or
numeric comparisons; use exists or missing to test field presence explicitly.

### 4.2 Boolean logic and validation

Conditions can be combined with nested AND and OR groups. Empty groups and
malformed conditions are rejected before saving or applying. The editor shows
which condition is invalid and does not silently ignore it. Applying a valid
filter evaluates all conditions against indexed data; it does not read or
modify source image files.

Saved filters use a versioned JSON object. Groups have an `op` of `and` or
`or` and a non-empty `conditions` array. A condition has a `field`, an
`operator`, and a `value`; metadata conditions additionally have a `key`.
For example:

```json
{
  "op": "and",
  "conditions": [
    {"field": "text", "operator": "matches", "value": "wildlife"},
    {
      "op": "or",
      "conditions": [
        {"field": "file_type", "operator": "equals", "value": "jpg"},
        {
          "field": "metadata",
          "key": "EXIF:Make",
          "operator": "contains",
          "value": "Canon"
        }
      ]
    }
  ]
}
```

The persisted filter version is stored separately from the JSON body. Folder
conditions use `within_any` with a list of indexed folder paths; file type also
supports `one_of`; capture-date bounds are integer timestamps in a `from`/`to`
object, where either bound may be null. Marked conditions use a boolean value.
Metadata comparisons are case-insensitive for text. Numeric comparisons accept
finite numeric values and do not match values that cannot be parsed as numbers.

### 4.3 Reapply behavior

The user explicitly chooses **Add matches** or **Replace members**:

- Add matches unions matching indexed images with current members; existing
  members remain.
- Replace members makes the set membership equal to the matching indexed
  images.
- If Replace members would leave the set empty, the application requires
  confirmation. Canceling leaves membership unchanged.
- A filter matching no images in Add mode has no effect and reports zero added.
- Reapplying a set's filter does not alter the filter or other sets.
- Add and filter reapply operations show progress and can be canceled. Canceling
  stops further work without rolling back changes already applied. During
  Replace, removals already performed also remain in effect. Canceling before
  any changes leaves membership unchanged.

## 5. Persistence and Identity

- Set definitions, saved filters, and memberships are stored in the active
  SQLCipher image-index database and are isolated per database.
- Image membership refers to the indexed image identity, not a copied media
  file. The database enforces cleanup when an image record is deleted.
- Set IDs remain stable across rename and membership changes. MCP requests are
  scoped to the currently open, unlocked database; clients must not assume IDs
  are portable across databases.
- Filter data is versioned so future application versions can validate or
  migrate saved filters. Unsupported or malformed filter versions are reported
  and are not applied.

## 6. MCP Interface

The existing opt-in local MCP server can access sets in the currently open and
unlocked database. MCP availability continues to follow the application's
existing enablement and database-lock behavior.

### 6.1 Listing and reading sets

- A list operation returns each set's ID, name, member count, and whether it
  has a saved filter.
- A read operation accepts a set ID and pagination information and returns one
  page of members. Each member includes its indexed image ID, path, filename,
  current custom tags and description, embedded-tag and description exclusion
  settings, and parsed indexed metadata.
- Pages have a deterministic ordering and return `next_offset` for continuation.
  Without previews, the default page size is 25 and the maximum is 50. With
  inline previews, both the default and maximum are 5 images. A custom-tag batch
  is limited to 100 image updates.
- Image previews are available through image-specific MCP resources. A page
  may also request inline preview data. Missing or unavailable previews are
  reported per image without failing the rest of the page.
- Requests for unknown sets, invalid pagination, or a set from a database that
  is no longer active return an MCP error.

### 6.2 Custom-tag writeback

A batch operation accepts image-specific tag updates. Each update includes the
indexed image ID, its path as returned by the application, a list of tag labels,
and an explicit mode: **append** or **replace**. Append is the default when a
caller omits the mode.

- The application verifies that the ID and path still identify the same image
  in the active database. Stale, mismatched, or unindexed images fail without
  writing tags.
- MCP may target any indexed image in the active database; membership in a
  particular set is not required.
- Append adds labels to existing custom tags, preserving existing labels and
  deduplicating according to the custom-tagging rules.
- Replace makes the supplied labels the complete custom-tag list for that
  image. It does not change embedded keywords or exclusion settings.
- Writes use the existing custom-tagging service and sidecar revision/conflict
  handling. The index and search data are refreshed through the existing
  tagging path. Original image files are never modified.
- Custom-tagging-disabled, locked-database, sidecar-conflict, validation, and
  filesystem errors are returned as failures; the operation must not bypass
  existing availability gates.
- A batch continues after an individual image fails and returns one result per
  requested image, including success or failure and the resulting custom tags
  on success. A batch is not atomic across images.
- Batch-size limits are bounded implementation constants and are reported
  clearly when exceeded.

## 7. Acceptance Criteria

- A user can create, rename, and delete a set without modifying media files.
- Set names are unique ignoring case within one database; the same name may be
  used in another database.
- A user can add the selected image, marked images, all current search results,
  and all images in the current Browse folder.
- A user can remove an individual member without deleting its image.
- Bulk additions include off-screen and not-yet-loaded rows, and repeat
  operations are safe and report their outcomes.
- Membership and saved filters persist across application restarts and remain
  isolated between databases.
- Reapplying a filter searches the entire index and implements the chosen Add
  or Replace semantics. An empty Replace cannot happen without confirmation.
- Image-index deletion cleans up corresponding membership records.
- An MCP client can list sets, read a set in bounded pages, retrieve previews,
  and receive per-image metadata, custom tags, descriptions, and exclusion state.
- MCP tag batches verify image identity, support append and replace, continue
  after per-image failures, and return an outcome for every item.
- MCP mutations use the existing sidecar/tagging behavior and never modify the
  source image or bypass lock/tagging availability.

## 8. Related Specifications

- [Project Specification](project-spec.md) defines the database, indexing, and
  custom-tagging architecture.
- [Custom Tagging Specification](tagging-spec.md) defines tag normalization,
  sidecar persistence, conflict behavior, and bulk-tag conventions.