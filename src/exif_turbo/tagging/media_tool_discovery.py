from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


_TOOL_NAMES = {
    "imagemagick": ("magick", "magick.exe"),
    "ffmpeg": ("ffmpeg", "ffmpeg.exe"),
    "ffprobe": ("ffprobe", "ffprobe.exe"),
}


def find_media_tool(tool: str) -> str | None:
    names = _TOOL_NAMES.get(tool)
    if names is None:
        raise ValueError(f"unsupported media tool: {tool}")
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for directory in _bundled_media_tool_directories():
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    return None


def _bundled_media_tool_directories() -> tuple[Path, ...]:
    roots = [Path(sys.executable).resolve().parent]
    frozen_directory = getattr(sys, "_MEIPASS", None)
    if isinstance(frozen_directory, str):
        roots.append(Path(frozen_directory))
    directories: list[Path] = []
    for root in roots:
        for candidate in (
            root / "media-tools",
            root / "media-tools" / "bin",
            root / "media-tools" / "imagemagick",
            root / "media-tools" / "ffmpeg" / "bin",
        ):
            if candidate not in directories:
                directories.append(candidate)
    return tuple(directories)


def _version(executable: str | None, arguments: tuple[str, ...]) -> str:
    if executable is None:
        return ""
    options: dict[str, Any] = {"capture_output": True, "text": True, "timeout": 10}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True
    try:
        result = subprocess.run([executable, *arguments], check=False, **options)
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else ""


def check_media_tools() -> list[dict[str, str | bool]]:
    imagemagick_path = find_media_tool("imagemagick")
    imagemagick_version = _version(imagemagick_path, ("-version",))
    ffmpeg_path = find_media_tool("ffmpeg")
    ffprobe_path = find_media_tool("ffprobe")
    ffmpeg_version = _version(ffmpeg_path, ("-version",))
    ffprobe_version = _version(ffprobe_path, ("-version",))

    return [
        {
            "id": "imagemagick",
            "name": "ImageMagick",
            "available": bool(imagemagick_version),
            "version": imagemagick_version,
            "path": imagemagick_path or "",
            "detail": "" if imagemagick_version else "magick executable not found or failed",
        },
        {
            "id": "ffmpeg",
            "name": "FFmpeg",
            "available": bool(ffmpeg_version and ffprobe_version),
            "version": ffmpeg_version,
            "path": ffmpeg_path or "",
            "detail": "" if ffmpeg_version and ffprobe_version else (
                "ffmpeg and ffprobe executables are both required"
            ),
        },
    ]