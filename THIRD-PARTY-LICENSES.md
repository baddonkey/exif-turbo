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
| [sqlcipher3](https://pypi.org/project/sqlcipher3/) | Encrypted SQLite database — stores the image index at rest using AES-256 via SQLCipher; exposes the standard Python `sqlite3` API | MIT | https://github.com/coleifer/sqlcipher3 |

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
| [ExifTool](https://exiftool.org/) | EXIF extraction — invoked as an external process (`exiftool -g1 -j`) to extract all EXIF, IPTC, and XMP metadata from image files | Artistic License / GPL | https://exiftool.org |
| `iconutil` *(macOS)* | `build_macos.sh` — converts PNG icon assets into an `.icns` file embedded in the `.app` bundle | Proprietary (Xcode Command Line Tools) | https://developer.apple.com/xcode |
| `hdiutil` *(macOS)* | `build_macos.sh` — packages the built `.app` bundle into a distributable `.dmg` disk image | Proprietary (macOS built-in) | https://developer.apple.com/macos |
