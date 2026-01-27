from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict

from PIL import Image


class ExifMetadataExtractor:
    def extract(self, path: Path) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        try:
            result = subprocess.run(
                [
                    "exiftool",
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
        except Exception:
            pass

        if path.suffix.lower() in {".png", ".gif", ".bmp", ".webp"}:
            try:
                with Image.open(path) as im:
                    info = getattr(im, "info", {}) or {}
                    for key, value in info.items():
                        metadata[f"PIL:{key}"] = str(value)
            except Exception:
                pass

        return metadata
