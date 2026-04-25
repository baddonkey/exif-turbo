from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IndexedFolder:
    id: int
    path: str
    display_name: str
    enabled: bool = True
    recursive: bool = True
    # "new" | "indexed" | "scanning" | "disabled" | "missing" | "error"
    status: str = "new"
    image_count: int = 0
    last_scanned_at: float | None = None
    error_message: str | None = None
