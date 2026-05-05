"""On-disk cache for full-resolution-ish image previews.

Sibling of :mod:`thumb_cache` — same content-hash scheme, but the rendered
artefact is a JPEG sized for the on-screen preview pane (configurable in
settings) rather than a fixed 144×144 thumbnail.  Lives in a separate
``previews/`` subdirectory so the two caches can be cleared independently.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# Directory name (relative to the per-DB cache dir) where rendered previews live.
PREVIEW_SUBDIR = "previews"


def preview_dir(cache_dir: Path) -> Path:
    """Return the previews directory under *cache_dir*."""
    return cache_dir / PREVIEW_SUBDIR


def preview_cache_name_from_stamp(path: str, mtime: float, size: int) -> str:
    """Return the cache filename (no directory) using pre-known mtime/size.

    Avoids hitting the filesystem to stat the source file — use DB-stored
    stamps instead of a live os.stat call.
    """
    key = f"{path}|{mtime}|{size}"
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()
    return f"{digest}.jpg"


def preview_cache_path(path: str, cache_dir: Path) -> Path:
    """Return the full preview cache path, computed from a live ``os.stat``."""
    try:
        stat = os.stat(path)
        key = f"{path}|{stat.st_mtime}|{stat.st_size}"
    except OSError:
        key = path
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()
    return preview_dir(cache_dir) / f"{digest}.jpg"


def expected_preview_filenames(
    stamps: dict[str, tuple[float, int]],
    *,
    encrypted: bool,
) -> set[str]:
    """Return the set of cache basenames the given stamps would produce."""
    suffix = ".jpg.enc" if encrypted else ".jpg"
    out: set[str] = set()
    for path, (mtime, size) in stamps.items():
        base = preview_cache_name_from_stamp(path, mtime, size)
        out.add(base[:-4] + suffix)
    return out


def list_existing_previews(cache_dir: Path, *, encrypted: bool) -> set[str]:
    """Return the set of preview filenames currently on disk."""
    suffix = ".jpg.enc" if encrypted else ".jpg"
    out: set[str] = set()
    pdir = preview_dir(cache_dir)
    try:
        with os.scandir(pdir) as it:
            for entry in it:
                if entry.name.endswith(suffix):
                    out.add(entry.name)
    except OSError:
        pass
    return out


def count_cached_previews(
    cache_dir: Path,
    stamps: dict[str, tuple[float, int]],
    *,
    encrypted: bool,
    existing: set[str] | None = None,
) -> int:
    """Count how many of *stamps*' images already have a preview cached."""
    if not stamps:
        return 0
    expected = expected_preview_filenames(stamps, encrypted=encrypted)
    if existing is None:
        existing = list_existing_previews(cache_dir, encrypted=encrypted)
    return len(expected & existing)


def clear_cached_previews_for(
    cache_dir: Path,
    stamps: dict[str, tuple[float, int]],
    *,
    encrypted: bool,
) -> int:
    """Delete every preview file that belongs to one of *stamps*.

    Returns the number of files removed.  Files belonging to other folders
    are left untouched.
    """
    if not stamps:
        return 0
    expected = expected_preview_filenames(stamps, encrypted=encrypted)
    pdir = preview_dir(cache_dir)
    removed = 0
    for name in expected:
        try:
            (pdir / name).unlink()
            removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return removed
