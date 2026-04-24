from __future__ import annotations

import hashlib
import os
from pathlib import Path


def thumb_cache_path(path: str, cache_dir: Path) -> Path:
    try:
        stat = os.stat(path)
        key = f"{path}|{stat.st_mtime}|{stat.st_size}"
    except OSError:
        key = path
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()
    return cache_dir / f"{digest}.png"


def thumb_cache_name_from_stamp(path: str, mtime: float, size: int) -> str:
    """Return the cache filename (no directory) using pre-known mtime/size.

    Avoids hitting the filesystem to stat the source file — use DB-stored
    stamps instead of a live os.stat call.
    """
    key = f"{path}|{mtime}|{size}"
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()
    return f"{digest}.png"
