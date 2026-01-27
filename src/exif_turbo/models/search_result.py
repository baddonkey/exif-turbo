from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchResult:
    path: str
    filename: str
    metadata_json: str
