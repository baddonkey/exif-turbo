# exif-turbo

Find photos by their metadata or by describing what they show. exif-turbo is a
local-first desktop app for searching and browsing large photo and video
collections on Windows, macOS, and Linux.

[Download the latest release](https://github.com/baddonkey/exif-turbo/releases) ·
[Read the User Manual](docs/user-manual.md)

[![Watch the exif-turbo walkthrough: full-screen search, metadata, AI search, and Browse](docs/screenshots/exif-turbo-demo-poster.png)](docs/screenshots/exif-turbo-demo.mp4)

*The demo and poster include photographs by © Giles Laurent, licensed CC BY-SA 4.0; see [screenshot attribution](docs/screenshots/README.md).*

## What it does

- **Search metadata:** Find images and videos by EXIF, IPTC, XMP, and other embedded metadata, with text, date, and folder filters.
- **Search by image meaning:** Use natural-language AI search to find photos by their visual content, not just their filenames or tags. AI search runs locally after its model is available.
- **Browse and inspect:** Browse indexed folders, preview media, and inspect metadata and EXIF tags.
- **Organize without changing originals:** Add searchable custom tags and descriptions in sidecars, and export tagged copies while leaving source files untouched.
- **Keep the index local:** Password-protected databases encrypt the index and supported thumbnail, preview, and AI caches at rest.
- **Handle varied libraries:** Index common photo, RAW, and video formats; the interface is available in five languages.

## Install

Download the installer for your platform from [GitHub Releases](https://github.com/baddonkey/exif-turbo/releases):

- **Windows:** MSI installer; ExifTool is included.
- **macOS:** Apple silicon DMG; install ExifTool separately.
- **Linux:** Debian/Ubuntu DEB or Fedora/openSUSE RPM; install ExifTool separately.

See the [User Manual](docs/user-manual.md#2-installation) for setup and first-run instructions.

## MCP batch selection

The running desktop app's MCP interface lets an assistant choose an image set
before applying custom tags to a batch:

```python
list_image_sets()
get_image_set_images(set_id=1, include_previews=True)
```

The first call lists sets with their IDs, names, and member counts. The second
returns a page of images with existing custom tags, descriptions, metadata, and available JPEG
previews. With previews enabled, the default and maximum page size is 5 images;
without previews, the default is 25 and the maximum is 50. Pass the returned
`next_offset` as `offset` to fetch another page until `next_offset` is `null`.
Use the chosen image IDs and paths with `set_custom_tags_batch` to append or
replace custom tags.

The single-image tools `get_selected_image` and `add_custom_tags` follow the
tagging drawer's selection. In Sets, select a member first; they never fall back
to an unrelated Search selection while a set is active. `add_custom_tags` updates
only that selected image, not the entire set. Check the path returned by
`get_selected_image` before tagging, and use `set_custom_tags_batch` with explicit
image IDs and paths for batch updates.

Successful MCP tag updates write an INFO log entry per image with the tool name,
image ID, target path, append/replace mode, requested tags, and resulting custom
tags. Failed updates are not logged as successes.

### Embedded tag exclusions through MCP

To ignore or restore one embedded keyword on derivative exports:

```python
set_image_embedded_tag_excluded(
    image_id=42, path=r"C:\photos\image.jpg", tag="Family", excluded=True
)
```

To ignore all embedded keywords independently:

```python
set_image_all_embedded_tags_excluded(
    image_id=42, path=r"C:\photos\image.jpg", excluded=True
)
```

Use `excluded=False` to restore inclusion. Individual exclusions are
case-insensitive and remain saved when ignore-all is toggled; restoring one
keyword does not override ignore-all. Both tools require a matching indexed
image ID/path, an unlocked database, and enabled tagging. They return
`excluded_embedded_tags`, `exclude_all_embedded_tags`, and `changed`.
Selected-image reads/resources and set-image listings also expose both settings.
Only sidecars and derived cache state change; originals, source metadata/search,
custom tags, descriptions, and description drafts are preserved.

### Custom descriptions through MCP

Use `set_image_description` to append or replace the custom description for an
explicit indexed image. Obtain its `image_id` and `path` from
`get_selected_image` or `get_image_set_images`; both must match the active
database. The mode is required:

```python
set_image_description(
    image_id=42,
    path=r"C:\Photos\fox.jpg",
    description="Photographed shortly before sunset.",
    mode="append",
)
```

Append adds a new paragraph with one blank line between the existing text and
the new text. Replace substitutes the entire custom description; an empty string
clears it. Empty appends are rejected. Original images and embedded descriptions
are never modified: the custom description lives in the adjacent JSON sidecar
and is searchable in the database.

For batches, call `set_image_descriptions_batch(updates=[...])` with at most 100
objects containing `image_id`, `path`, `description`, and explicit `mode`.
Results are reported per image, including the resulting description and a
`changed` flag. Existing descriptions are included in selected-image metadata
and set-image listings. Description editing in the tagging drawer uses the same
sidecar operations. **Copy Description** can append or replace saved custom
descriptions on the same targets as Copy Tags. Replace requires confirmation
and can clear target descriptions when the source is empty; drafts and embedded
metadata are not copied. Copy Tags remains unchanged. Derivative exports include the
embedded description (unless ignored), then the saved custom description as a
new paragraph in XMP-dc Description. The drawer's **Final derivative description**
preview shows this combined text; unsaved drafts are not included.

To discard embedded descriptions from exported copies without supplying any
replacement text, use
`set_image_description_excluded(image_id=42, path=..., excluded=True)`.
The independent `exclude_embedded_description` sidecar flag is also available as
**Ignore embedded description** in the drawer and is returned by MCP image reads.
Set it to `False` to retain embedded descriptions again. It does not clear custom
description text, remove source metadata from search, or change original files.

## Privacy

Indexing and search run locally. Password protection covers the database and
supported caches, not original media, exports, tagging sidecars, settings,
diagnostic output, or data in application memory. See [What the password
protects](docs/user-manual.md#what-the-password-protects) for the full scope.

## More information

- [User Manual](docs/user-manual.md)
- [AI performance measurements](docs/ai-performance.md)
- [CI quality checks](docs/continuous-integration.md)
- [License](LICENSE) and [third-party software notices](THIRD-PARTY-LICENSES.md)

Sample-photo sources and licenses are listed in the [attribution manifest](tests/sample-data/ATTRIBUTION.md).