# exif-turbo

Find photos by their metadata or by describing what they show. exif-turbo is a
local-first desktop app for searching and browsing large photo and video
collections on Windows, macOS, and Linux.

For AI assisted tagging, watch out the companion project [Exif Turbo AI Tagger](https://github.com/baddonkey/tag-exif-turbo).

[Download the latest release](https://github.com/baddonkey/exif-turbo/releases) ·
[Read the User Manual](docs/user-manual.md)

[![Watch the exif-turbo walkthrough: full-screen search, metadata, AI search, and Browse](docs/screenshots/exif-turbo-demo-poster.png)](docs/screenshots/exif-turbo-demo.mp4)

*The demo and poster include photographs by © Giles Laurent, licensed CC BY-SA 4.0; see [screenshot attribution](docs/screenshots/README.md).*

## What it does

- **Search metadata:** Search EXIF, IPTC, XMP, and other embedded metadata with full-text and [structured tag, description, date, format, and folder filters](docs/user-manual.md#6-searching).
- **Search by image meaning:** Find photos by visual content with local AI search after its model is available. See [AI search](docs/user-manual.md#6-searching).
- **Browse and inspect:** Browse [indexed folders](docs/user-manual.md#7-browsing-by-folder), preview media, and inspect [metadata and EXIF tags](docs/user-manual.md#9-viewing-metadata-and-exif-tags).
- **Group with Image Sets:** Collect image references, filter Search by set, and optionally reapply saved filters. See [Image Sets](docs/user-manual.md#8-image-sets).
- **Tag and export derivatives:** Add searchable custom tags and descriptions in sidecars, then create configurable derivative copies with format, resize, metadata, and embedded-tag/description controls. See [Custom Tags and Derivatives](docs/user-manual.md#11-custom-tags-and-derivatives).
- **Keep the index local:** Password-protected databases encrypt the index and supported thumbnail, preview, and AI caches at rest.
- **Handle varied libraries:** Index common photo, RAW, and video formats; the interface is available in five languages.

## Install

Download the installer for your platform from [GitHub Releases](https://github.com/baddonkey/exif-turbo/releases):

- **Windows:** MSI installer; ExifTool is included.
- **macOS:** Apple silicon DMG; install ExifTool separately.
- **Linux:** Debian/Ubuntu DEB or Fedora/openSUSE RPM; install ExifTool separately.

See the [User Manual](docs/user-manual.md#2-installation) for setup and first-run instructions.

## MCP interface

The optional MCP server runs inside the desktop app. The User Manual's
[MCP Interface guide](docs/user-manual.md#mcp-interface) covers setup, selected
images, set pagination, batch tag and description updates, and derivative
exclusions.

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
