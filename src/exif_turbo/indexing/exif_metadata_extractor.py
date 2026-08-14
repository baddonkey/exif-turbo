from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from PIL import Image

_log = logging.getLogger(__name__)

# When the app runs as a frozen .app bundle on macOS (or a similar restricted
# environment on Windows), the process PATH is minimal and does not include
# Homebrew or other user-installed tool directories.  Build a best-effort
# augmented PATH so shutil.which() can locate exiftool.
_EXTRA_PATHS = [
    "/usr/local/bin",       # Homebrew (Intel Mac)
    "/opt/homebrew/bin",    # Homebrew (Apple Silicon)
    "/opt/homebrew/sbin",
    "/usr/bin",
    "/bin",
]


def _bundled_exiftool() -> Path | None:
    """Return the path to the exiftool bundled with the Windows MSI installer.

    The MSI installs ExifTool into an ``exiftool/`` subfolder next to the
    application executable.  When running as a PyInstaller frozen bundle
    ``sys.executable`` points to the .exe itself, so its parent is the app
    directory.  In dev mode we return None so the system PATH is used.
    """
    if os.name != "nt":
        return None
    import sys
    app_dir = Path(sys.executable).parent
    candidate = app_dir / "exiftool" / "exiftool.exe"
    return candidate if candidate.exists() else None


def find_exiftool() -> str:
    """Return the path to exiftool.

    Search order:
    1. ``exiftool`` found on the system PATH (including common extra locations).
    2. Bundled copy installed by the Windows MSI alongside the application.
    3. Bare ``"exiftool"`` name — will produce a clear error if missing.
    """
    augmented = os.pathsep.join(
        [os.environ.get("PATH", "")] + _EXTRA_PATHS
    )
    found = shutil.which("exiftool", path=augmented)
    if found:
        return found
    bundled = _bundled_exiftool()
    if bundled:
        return str(bundled)
    return "exiftool"  # fall back to bare name; will fail with a clear error


def is_exiftool_available() -> bool:
    """Return True if exiftool can be found and executed."""
    augmented = os.pathsep.join(
        [os.environ.get("PATH", "")] + _EXTRA_PATHS
    )
    found = shutil.which("exiftool", path=augmented)
    if not found:
        bundled = _bundled_exiftool()
        found = str(bundled) if bundled else None
    if not found:
        return False
    try:
        _platform_kwargs: dict = (
            {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
        )
        result = subprocess.run(
            [found, "-ver"],
            capture_output=True,
            timeout=10,
            **_platform_kwargs,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def get_exiftool_version() -> str:
    """Return the exiftool version string, or empty string if not available."""
    augmented = os.pathsep.join(
        [os.environ.get("PATH", "")] + _EXTRA_PATHS
    )
    found = shutil.which("exiftool", path=augmented)
    if not found:
        bundled = _bundled_exiftool()
        found = str(bundled) if bundled else None
    if not found:
        return ""
    try:
        _platform_kwargs: dict = (
            {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
        )
        result = subprocess.run(
            [found, "-ver"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            **_platform_kwargs,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return ""
    except Exception:  # noqa: BLE001
        return ""


class ExifMetadataExtractor:
    def extract(self, path: Path) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        try:
            # On Windows, CREATE_NO_WINDOW prevents a console flash per subprocess.
            # On POSIX, start_new_session detaches the child from the controlling terminal.
            _platform_kwargs: dict[str, Any] = (
                {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
            )
            result = subprocess.run(
                [
                    find_exiftool(),
                    "-json",
                    "-g1",
                    "-n",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
                **_platform_kwargs,
            )
            if result.stdout:
                items = json.loads(result.stdout)
                if items and isinstance(items, list):
                    for key, value in items[0].items():
                        if isinstance(value, dict):
                            for sub_key, sub_value in value.items():
                                metadata[f"{key}:{sub_key}"] = str(sub_value)
                        else:
                            metadata[str(key)] = str(value)
        except subprocess.TimeoutExpired as exc:
            _log.warning("exiftool timed out for %s: %s", path, exc)
        except Exception as exc:
            _log.warning("exiftool extraction failed for %s: %s", path, exc)

        if path.suffix.lower() in {".png", ".gif", ".bmp", ".webp"}:
            try:
                with Image.open(path) as im:
                    info = getattr(im, "info", {}) or {}
                    for key, value in info.items():
                        metadata[f"PIL:{key}"] = str(value)
            except Exception as exc:
                _log.warning("Pillow metadata extraction failed for %s: %s", path, exc)

        return metadata
