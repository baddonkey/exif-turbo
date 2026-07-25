"""Shared generator for the Windows ``version_info.py`` exe-metadata file.

``version_info.py`` is derived solely from the project version string. It is
consumed by PyInstaller (via ``exif-turbo.spec``) to stamp the Windows EXE
resource metadata. Keeping the template here lets both the PyInstaller spec and
the release tooling produce byte-identical output from a single source.
"""

from __future__ import annotations

from pathlib import Path


def render_version_info(version: str) -> str:
    """Return the ``version_info.py`` contents for a given semantic version."""
    major, minor, patch = (version.split(".") + ["0", "0", "0"])[:3]
    version_tuple = (int(major), int(minor), int(patch), 0)
    return f'''\
# Auto-generated from exif-turbo.spec — do not edit manually.
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers={version_tuple},
        prodvers={version_tuple},
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "exif-turbo"),
                        StringStruct("FileDescription", "exif-turbo — Image EXIF metadata search and indexing tool"),
                        StringStruct("FileVersion", "{version}"),
                        StringStruct("InternalName", "exif-turbo"),
                        StringStruct("LegalCopyright", "Copyright (c) 2025 exif-turbo contributors"),
                        StringStruct("OriginalFilename", "exif-turbo.exe"),
                        StringStruct("ProductName", "exif-turbo"),
                        StringStruct("ProductVersion", "{version}"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
'''


def write_version_info(version: str, path: Path) -> None:
    """Write ``version_info.py`` for ``version`` to ``path`` (UTF-8)."""
    path.write_text(render_version_info(version), encoding="utf-8")
