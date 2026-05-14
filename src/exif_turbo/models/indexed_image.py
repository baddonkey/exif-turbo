from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class IndexedImage:
    path: str
    filename: str
    mtime: float
    size: int
    metadata: Dict[str, str]
    metadata_text: str
    captured_at: float | None = field(default=None)
