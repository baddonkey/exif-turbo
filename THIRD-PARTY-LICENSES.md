# Third-Party Licenses

This file lists all third-party software used in exif-turbo, along with their
licenses and upstream URLs.

---

## Python Runtime Dependencies

These packages are required at runtime by the application.

| Package | Used for | License | URL |
|---------|----------|---------|-----|
| [PySide6](https://pypi.org/project/PySide6/) | Qt bindings — QML engine, Qt Quick / Material UI, threading (`QThread`), file dialogs, and the application event loop | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| [Pillow](https://pypi.org/project/Pillow/) | Thumbnail generation — opens JPEG / PNG / TIFF images, applies EXIF orientation correction via `ImageOps.exif_transpose`, resizes to cache-sized PNGs | HPND (Historical Permission Notice and Disclaimer) | https://pillow.readthedocs.io |
| [rawpy](https://pypi.org/project/rawpy/) | RAW image decoding — wraps libraw to extract embedded JPEG previews or full-colour bitmaps from CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF, RWL, SRW files | MIT | https://github.com/letmaik/rawpy |
| [av (PyAV)](https://pypi.org/project/av/) | Video thumbnail and preview extraction — wraps FFmpeg to decode frames from MP4, MOV, AVI, MKV, WMV, M4V, MTS, M2TS, 3GP, WebM, and FLV files; uses the embedded thumbnail when present, otherwise extracts a frame at 1/3 of the duration; applies rotation from the `tkhd` display matrix | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| [sqlcipher3](https://pypi.org/project/sqlcipher3/) | Encrypted SQLite database — stores the image index at rest using AES-256 via SQLCipher; exposes the standard Python `sqlite3` API | MIT | https://github.com/coleifer/sqlcipher3 |
| [cryptography](https://pypi.org/project/cryptography/) | Thumbnail and preview cache encryption — AES-256-GCM symmetric encryption of cached thumbnail PNGs and preview JPEGs on disk; key derivation and wrapped-key model for password changes | Apache-2.0 OR BSD-3-Clause | https://cryptography.io |
| [markdown](https://pypi.org/project/Markdown/) | User manual export — converts `docs/user-manual.md` to HTML as an intermediate step when generating the PDF via `export_manual_pdf.py` | BSD-2-Clause | https://python-markdown.github.io |
| [pyvips](https://pypi.org/project/pyvips/) | Large-image rendering — Python bindings for libvips; used to decode images exceeding 100 MP (panoramas, large TIFFs, medium-format scans) via streaming tile I/O so memory use stays constant; initialised lazily | MIT | https://github.com/libvips/pyvips |
| [pyvips-binary](https://pypi.org/project/pyvips-binary/) | Pre-built libvips shared library — bundled libvips binary wheels that provide the native library for `pyvips` on Windows and Linux without a separate system install | MIT | https://github.com/libvips/pyvips |

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

## Development & Test Dependencies

These packages are used during development and CI, not shipped in releases.

| Package | Used for | License | URL |
|---------|----------|---------|-----|
| [pytest](https://pypi.org/project/pytest/) | Test runner — executes all unit and integration tests under `tests/` | MIT | https://docs.pytest.org |
| [pytest-qt](https://pypi.org/project/pytest-qt/) | Qt/PySide6 test helpers — provides the `qtbot` fixture used in GUI tests to drive the live QML window | MIT | https://github.com/pytest-dev/pytest-qt |
| [mypy](https://pypi.org/project/mypy/) | Static type checker — enforces `--strict` type correctness across the entire `src/` tree | MIT | https://www.mypy-lang.org |

---

## System / External Tools

These tools must be available on `PATH` at runtime or build time.
They are **not** Python packages.

| Tool | Used for | License | URL |
|------|----------|---------|-----|
| [ExifTool](https://exiftool.org/) | EXIF extraction — invoked as an external process (`exiftool -g1 -j`) to extract all EXIF, IPTC, and XMP metadata from image files | Artistic License / GPL (same terms as Perl) | https://exiftool.org |
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
permitted by its license.  The full Perl license texts are available at
https://dev.perl.org/licenses/.

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
| Documentation screenshots | Lock screen, Search (all / eagle / Milky Way), Browse, Indexed Folders, and folder-filter screenshots (`01_lock_screen.png` – `07_folder_filter.png`) |
| `tests/sample-data/schweiz/` | 13 wildlife, landscape, and astrophotography test images |

Full per-file attribution is listed in
[tests/sample-data/ATTRIBUTION.md](tests/sample-data/ATTRIBUTION.md).

---

## GPS Screenshot Image Credit

The GPS location bar screenshot (`docs/screenshots/08_gps_location_bar.png`) uses
a photograph of the Xenakis UPIC system published on
[Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Xenakis_UPIC_system_computer_unit_2.jpg)
under the [Creative Commons CC0 1.0 Universal Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/).

- **Author:** 1904.CC (Manuel Schmalstieg)
- **Attribution (voluntary):** 1904.CC (Manuel Schmalstieg), CC0, via Wikimedia Commons
