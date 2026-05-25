from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchResult:
    path: str
    filename: str
    metadata_json: str
    size: int = 0
    mtime: float = 0.0
    image_id: int = 0
