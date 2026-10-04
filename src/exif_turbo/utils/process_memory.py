"""Best-effort current resident memory (RSS) of this process."""
from __future__ import annotations

import os
from pathlib import Path

_STATM_PATH = Path("/proc/self/statm")


def current_rss_bytes(statm_path: Path = _STATM_PATH) -> int | None:
    """Return the current resident set size in bytes, or ``None`` if unknown.

    Reads ``/proc/self/statm`` (Linux).  Other platforms return ``None``.
    """
    try:
        fields = statm_path.read_text(encoding="ascii").split()
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError, AttributeError):
        return None
