# Third-Party Licenses

This file lists all third-party software used in exif-turbo, along with their
licenses and upstream URLs.

Release bundles include the exact license files collected from the active build
environment in the `licenses/` folder, together with the matching CPython and
Qt open-source license texts. The `licenses/libvips/<version>/` directory also
contains the exact libvips LGPL text, the native bundle's third-party notices,
dependency version manifest, build-script license, and corresponding source and
replacement instructions.

---

## Python Runtime Dependencies

These packages are required at runtime by the application.

| Package | Used for | License | URL |
|---------|----------|---------|-----|
| [CPython](https://www.python.org/) | Embedded Python interpreter and standard library used by the standalone application | Python-2.0 | https://docs.python.org/3/license.html |
| [PySide6](https://pypi.org/project/PySide6/) | Qt bindings — QML engine, Qt Quick / Material UI, threading (`QThread`), file dialogs, and the application event loop | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| [Pillow](https://pypi.org/project/Pillow/) | Thumbnail generation — opens JPEG / PNG / TIFF images, applies EXIF orientation correction via `ImageOps.exif_transpose`, resizes to cache-sized PNGs | HPND (Historical Permission Notice and Disclaimer) | https://pillow.readthedocs.io |
| [rawpy](https://pypi.org/project/rawpy/) | RAW image decoding — wraps libraw to extract embedded JPEG previews or full-colour bitmaps from CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF, RWL, SRW files | MIT | https://github.com/letmaik/rawpy |
| [av](https://pypi.org/project/av/) (PyAV) | Video thumbnail and preview extraction — wraps FFmpeg to decode frames from MP4, MOV, AVI, MKV, WMV, M4V, MTS, M2TS, 3GP, WebM, and FLV files; uses the embedded thumbnail when present, otherwise extracts a frame at 1/3 of the duration; applies rotation from the `tkhd` display matrix | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| [sqlcipher3](https://pypi.org/project/sqlcipher3/) | Encrypted SQLite database — stores the image index at rest using AES-256 via SQLCipher; exposes the standard Python `sqlite3` API | MIT | https://github.com/coleifer/sqlcipher3 |
| [cryptography](https://pypi.org/project/cryptography/) | Thumbnail and preview cache encryption — AES-256-GCM symmetric encryption of cached thumbnail PNGs and preview JPEGs on disk; key derivation and wrapped-key model for password changes | Apache-2.0 OR BSD-3-Clause | https://cryptography.io |
| [pyvips](https://pypi.org/project/pyvips/) | Large-image rendering — Python bindings for libvips; used to decode images exceeding 100 MP (panoramas, large TIFFs, medium-format scans) via streaming tile I/O so memory use stays constant; initialised lazily | MIT | https://github.com/libvips/pyvips |
| [pyvips-binary](https://pypi.org/project/pyvips-binary/) | Pre-built libvips shared library — bundled libvips binary wheels that provide the native library for `pyvips` on Windows and Linux without a separate system install | LGPL-3.0-or-later | https://github.com/kleisauke/pyvips-binary |
| [faiss-cpu](https://pypi.org/project/faiss-cpu/) | AI vector search index — stores and queries CLIP embeddings for AI-based image search using an inner-product FAISS index | MIT | https://github.com/facebookresearch/faiss |
| [open-clip-torch](https://pypi.org/project/open-clip-torch/) | AI search and AI indexing — loads the CLIP model/tokenizer used to embed images and text; downloads its runtime cache into the per-database user folder under `~/.exif-turbo/data/<db-stem>/open_clip/` | MIT | https://github.com/mlfoundations/open_clip |

The `pyvips-binary` wheel contains dynamically loaded, separate shared-library
files built by [libvips-packaging](https://github.com/kleisauke/libvips-packaging).
Release recipients can replace those files with interface-compatible modified
builds. Exact versioned source and build links are shipped in
`licenses/libvips/<version>/SOURCE-AND-REPLACEMENT.txt`. On macOS, replacing a
signed `.dylib` invalidates the app signature; the modified app must be signed
again locally, for example with `codesign --force --deep --sign - exif-turbo.app`.

---

## Runtime-Downloaded AI Assets

These assets are **not bundled in the installer**. They are downloaded on first
AI use and cached in the per-database user folder under
`~/.exif-turbo/data/<db-stem>/open_clip/`.

| Asset | Used for | License | URL |
|-------|----------|---------|-----|
| OpenCLIP tokenizer vocabulary (`bpe_simple_vocab_16e6.txt.gz`) | Text tokenization for AI search and AI indexing | MIT (via OpenAI CLIP repository) | https://github.com/openai/CLIP |
| OpenAI ViT-B/32 pretrained weights (`timm/vit_base_patch32_clip_224.openai`) | Pretrained CLIP model weights downloaded by OpenCLIP for AI search and AI indexing | Apache-2.0 | https://huggingface.co/timm/vit_base_patch32_clip_224.openai |

> **OpenAI CLIP attribution:** The OpenCLIP project states that portions of its
> modeling and tokenizer code are adapted from OpenAI's CLIP repository, which
> is licensed under MIT. The runtime tokenizer vocabulary used here follows
> that upstream source.

---

## Runtime-Downloaded Controlled Vocabulary

This data is **not bundled in the installer**. When the user chooses
**Install TGM** or **Update TGM**, exif-turbo downloads one of the official
quarterly distributions and stores a normalized snapshot in the current
database's application-data directory.

| Asset | Used for | Terms / status | URL |
|-------|----------|----------------|-----|
| Library of Congress Thesaurus for Graphic Materials (TGM), XML or tagged-text distribution | Canonical controlled terms, aliases, categories, and the separate TGM proposal-vector index | The Library of Congress download page makes both formats available for importing into other systems but does not state a standalone SPDX license. Use remains subject to the [Library of Congress legal notice](https://www.loc.gov/legal/). | https://guides.loc.gov/tgm-i/download-tgm |

exif-turbo records the source URL, source date, and SHA-256 checksum for the
downloaded snapshot. The checksum records provenance and change; it is not a
publisher signature or a grant of additional rights.

---

## Python GUI / Optional Dependencies

| Package | Used for | License | URL |
|---------|----------|---------|-----|
| [pyobjc-framework-Cocoa](https://pypi.org/project/pyobjc-framework-Cocoa/) *(macOS only)* | macOS Cocoa bridge — used to apply the native appearance and dark-mode integration on macOS | MIT | https://github.com/ronaldoussoren/pyobjc |

---

## Build System

These packages are used to build and package exif-turbo from source.

| Package | Used for | License | URL |
|---------|----------|---------|-----|
| [setuptools](https://pypi.org/project/setuptools/) | Python package build backend — compiles the `exif-turbo` wheel and installs the entry-point scripts | MIT | https://github.com/pypa/setuptools |
| [wheel](https://pypi.org/project/wheel/) | Builds the standard Python wheel distribution from the setuptools backend | MIT | https://github.com/pypa/wheel |
| [PyInstaller](https://pypi.org/project/pyinstaller/) | Freezes the GUI into a self-contained binary (`exif-turbo.app` / `exif-turbo.exe`) that runs without a Python installation | GPL-2.0-or-later with Bootloader Exception | https://pyinstaller.org |
| [WiX Toolset v4](https://www.nuget.org/packages/wix) *(Windows installer)* | Compiles the `exif-turbo.wxs` descriptor into a distributable MSI installer for Windows | Microsoft Reciprocal License (MS-RL) | https://wixtoolset.org |

> **PyInstaller Bootloader Exception:** The PyInstaller bootloader (the stub
> that loads your frozen application) is licensed under the Apache 2.0 License.
> Only the build tool itself is GPL-2.0-or-later; the generated executables are
> not affected by the GPL.

---

## Internationalization (i18n) Tools

These packages are used to extract, update, and compile translation catalogs.

| Package | Used for | License | URL |
|---------|----------|---------|-----|
| [Babel](https://pypi.org/project/Babel/) | `pybabel` CLI — extracts translatable strings from Python source, updates `.po` files, and compiles them to binary `.mo` catalogs loaded at runtime | BSD-3-Clause | https://babel.pocoo.org |

---

## Documentation Generation Tools

These packages generate the tracked PDF user manual and are not shipped as
application runtime components. `export_manual_pdf.py` uses WeasyPrint when
available and otherwise falls back to xhtml2pdf.

| Package | Used for | License | URL |
|---------|----------|---------|-----|
| [Markdown](https://pypi.org/project/Markdown/) | Converts `docs/user-manual.md` to HTML | BSD-3-Clause | https://python-markdown.github.io |
| [Pygments](https://pypi.org/project/Pygments/) | Syntax highlighting for fenced code in the generated manual | BSD-2-Clause | https://pygments.org |
| [WeasyPrint](https://pypi.org/project/weasyprint/) | Preferred HTML-to-PDF renderer | BSD-3-Clause | https://weasyprint.org |
| [xhtml2pdf](https://pypi.org/project/xhtml2PDF/) | Fallback HTML-to-PDF renderer | Apache-2.0 | https://github.com/xhtml2pdf/xhtml2pdf |

---

## Development & Test Dependencies

These packages are used during development and CI, not shipped in releases.

| Package | Used for | License | URL |
|---------|----------|---------|-----|
| [pytest](https://pypi.org/project/pytest/) | Test runner — executes all unit and integration tests under `tests/` | MIT | https://docs.pytest.org |
| [pytest-qt](https://pypi.org/project/pytest-qt/) | Qt/PySide6 test helpers — provides the `qtbot` fixture used in GUI tests to drive the live QML window | MIT | https://github.com/pytest-dev/pytest-qt |
| [pytest-timeout](https://pypi.org/project/pytest-timeout/) | Enforces per-test timeouts and emits stack dumps for wedged native/Qt tests | MIT | https://github.com/pytest-dev/pytest-timeout |
| [mypy](https://pypi.org/project/mypy/) | Static type checker — enforces `--strict` type correctness across the entire `src/` tree | MIT | https://www.mypy-lang.org |

---

## System / External Tools

These tools must be available on `PATH` at runtime or build time.
They are **not** Python packages.

| Tool | Used for | License | URL |
|------|----------|---------|-----|
| [ExifTool](https://exiftool.org/) | Metadata extraction and derivative writes — reads EXIF, IPTC, and XMP metadata, then writes and verifies XMP Subject and IPTC Keywords on temporary derivative copies only | Artistic License / GPL (same terms as Perl) | https://exiftool.org |
| `iconutil` *(macOS)* | `build_macos.py` — converts PNG icon assets into an `.icns` file embedded in the `.app` bundle | Proprietary (Xcode Command Line Tools) | https://developer.apple.com/xcode |
| `hdiutil` *(macOS)* | `build_macos.py` — packages the built `.app` bundle into a distributable `.dmg` disk image | Proprietary (macOS built-in) | https://developer.apple.com/macos |

---

## Bundled Third-Party Binaries (Windows MSI)

The Windows MSI installer includes the following third-party binary as an
optional, pre-selected feature.  It is installed into a dedicated
`exiftool\` subfolder inside the application directory and is **not** added
to the system PATH.  exif-turbo uses this bundled copy only when no
system-wide ExifTool is found on PATH.

### ExifTool (Windows 64-bit executable)

- **Author:** Phil Harvey
- **Version bundled:** latest stable at build time (fetched from exiftool.org)
- **Source:** https://exiftool.org/ — https://github.com/exiftool/exiftool
- **License:** Free software; redistributable under the same terms as Perl itself —
  either the [GNU General Public License, version 1 or later](https://dev.perl.org/licenses/gpl1.html),
  or the [Artistic License](https://dev.perl.org/licenses/artistic.html).

The Windows binary package is based on work by Oliver Betz and uses his
launcher.  See https://oliverbetz.de/pages/Artikel/ExifTool-for-Windows.

Redistribution of the ExifTool Windows executable in this installer is
permitted by its license.  The unmodified Windows package includes the full
Perl Artistic and GPL license texts in `Licenses_Strawberry_Perl.zip`.

---

## Sample & Screenshot Image Credits

The photographs used in the documentation screenshots and as test sample data
are by **Giles Laurent**, published on
[Wikimedia Commons](https://commons.wikimedia.org/wiki/User:Giles_Laurent)
under the
[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/)
license.

Mandatory attribution per the license:

> © Giles Laurent, gileslaurent.com, License CC BY-SA

| Used in | Description |
|---------|-------------|
| Documentation screenshots | Search (all / eagle / Milky Way), Browse, folder-filter, and AI-mode screenshot composites (`02`, `03`, `04`, `05`, `07`, and `09`) contain scaled/cropped Giles Laurent photographs and are distributed under CC BY-SA 4.0 |
| `tests/sample-data/schweiz/` | 13 wildlife, landscape, and astrophotography test images |

Full per-file attribution is listed in
[tests/sample-data/ATTRIBUTION.md](tests/sample-data/ATTRIBUTION.md).

`01_lock_screen.png`, `06_indexed_folders.png`, and `11_tagging_settings.png`
contain no third-party photographs.

---

## GPS Screenshot Image Credit

The GPS location bar and tagging-drawer screenshots
(`docs/screenshots/08_gps_location_bar.png` and
`docs/screenshots/10_tagging_drawer.png`) use a photograph of the Xenakis UPIC
system published on
[Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Xenakis_UPIC_system_computer_unit_2.jpg)
under the [Creative Commons CC0 1.0 Universal Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/).

- **Author:** 1904.CC (Manuel Schmalstieg)
- **Attribution (voluntary):** 1904.CC (Manuel Schmalstieg), CC0, via Wikimedia Commons
- **Sample files:** `tests/sample-data/gps/Xenakis_UPIC_system_computer_unit_2.jpg` and `tests/sample-data/computer/Xenakis UPIC system computer unit 2.jpg`
