# exif-turbo

Find photos by their metadata or by describing what they show. exif-turbo is a
local-first desktop app for searching and browsing large photo and video
collections on Windows, macOS, and Linux.

[Download the latest release](https://github.com/baddonkey/exif-turbo/releases) ·
[Read the User Manual](docs/user-manual.md)

[![Watch the exif-turbo walkthrough: full-screen search, metadata, AI search, and Browse](docs/screenshots/exif-turbo-demo-poster.png)](docs/screenshots/exif-turbo-demo.mp4)

*The demo includes photographs by © Giles Laurent, licensed CC BY-SA 4.0; see [screenshot attribution](docs/screenshots/README.md).*

## What it does

- **Search metadata:** Find images and videos by EXIF, IPTC, XMP, and other embedded metadata, with text, date, and folder filters.
- **Search by image meaning:** Use natural-language AI search to find photos by their visual content, not just their filenames or tags. AI search runs locally after its model is available.
- **Browse and inspect:** Browse indexed folders, preview media, and inspect metadata and EXIF tags.
- **Organize without changing originals:** Add custom tags, search them, and export tagged copies while leaving source files untouched.
- **Keep the index local:** Password-protected databases encrypt the index and supported thumbnail, preview, and AI caches at rest.
- **Handle varied libraries:** Index common photo, RAW, and video formats; the interface is available in five languages.

## Install

Download the installer for your platform from [GitHub Releases](https://github.com/baddonkey/exif-turbo/releases):

- **Windows:** MSI installer; ExifTool is included.
- **macOS:** Apple silicon DMG; install ExifTool separately.
- **Linux:** Debian/Ubuntu DEB or Fedora/openSUSE RPM; install ExifTool separately.

See the [User Manual](docs/user-manual.md#2-installation) for setup and first-run instructions.

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