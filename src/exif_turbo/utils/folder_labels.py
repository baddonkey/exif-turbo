"""Friendly display labels for filesystem folders.

The indexed-folder repository stores a ``display_name`` per folder which
is normally ``Path(folder).name``. That works for ordinary directories,
but ``Path("C:\\").name`` is the empty string, so drive roots (and the
POSIX root ``/``) end up with no label in the search-tab folder filter.

This module computes a sensible, human-readable label for such roots.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


def _is_windows_drive_root(path: str) -> bool:
    """True if *path* is a Windows drive root like ``C:\\`` or ``D:/``."""
    if sys.platform != "win32" or len(path) < 2 or path[1] != ":":
        return False
    tail = path[2:]
    return tail in ("", "\\", "/", "\\\\", "//")


def _windows_volume_label(drive: str) -> str:
    """Return the volume label for *drive* (e.g. ``"C:\\"``) or ``""``.

    Uses ``GetVolumeInformationW``; failures (unmounted drive, access
    denied, non-Windows) return an empty string.
    """
    if sys.platform != "win32":
        return ""
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        volume_name_buffer = ctypes.create_unicode_buffer(261)
        fs_name_buffer = ctypes.create_unicode_buffer(261)
        serial_number = ctypes.c_ulong(0)
        max_component_len = ctypes.c_ulong(0)
        file_system_flags = ctypes.c_ulong(0)
        ok = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive),
            volume_name_buffer,
            ctypes.sizeof(volume_name_buffer) // ctypes.sizeof(ctypes.c_wchar),
            ctypes.byref(serial_number),
            ctypes.byref(max_component_len),
            ctypes.byref(file_system_flags),
            fs_name_buffer,
            ctypes.sizeof(fs_name_buffer) // ctypes.sizeof(ctypes.c_wchar),
        )
        if not ok:
            return ""
        return volume_name_buffer.value or ""
    except (OSError, AttributeError):
        return ""


def friendly_folder_label(path: str) -> str:
    """Return a human-readable label for *path*.

    - Windows drive roots (``C:\\``) → ``"OS (C:)"`` if a volume label is
      available, otherwise ``"C:\\"``.
    - POSIX root (``/``) → ``"/"``.
    - Everything else → ``Path(path).name``, falling back to the
      normalised path when ``name`` is empty.
    """
    if not path:
        return ""

    normalised = os.path.normpath(path)

    if _is_windows_drive_root(normalised):
        drive_root = normalised[:2] + "\\"  # e.g. "C:\\"
        label = _windows_volume_label(drive_root)
        if label:
            return f"{label} ({normalised[:2]})"
        return drive_root

    if normalised in ("/", os.sep) and sys.platform != "win32":
        return "/"

    name = Path(normalised).name
    return name or normalised
