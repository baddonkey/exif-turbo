from __future__ import annotations

from pathlib import Path
from typing import Dict, Protocol


class MetadataExtractor(Protocol):
    def extract(self, path: Path) -> Dict[str, str]:
        ...
