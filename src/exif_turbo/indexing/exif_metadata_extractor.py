from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from PIL import Image

_log = logging.getLogger(__name__)


class ExifMetadataExtractor:
    def extract(self, path: Path) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        try:
            # On Windows, CREATE_NO_WINDOW prevents a console flash per subprocess.
            # On POSIX, start_new_session detaches the child from the controlling terminal.
            _platform_kwargs: dict[str, Any] = (
                {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
            )
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
                **_platform_kwargs,
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
        except Exception as exc:
            _log.warning("exiftool extraction failed for %s: %s", path, exc)

        if path.suffix.lower() in {".png", ".gif", ".bmp", ".webp"}:
            try:
                with Image.open(path) as im:
                    info = getattr(im, "info", {}) or {}
                    for key, value in info.items():
                        metadata[f"PIL:{key}"] = str(value)
            except Exception as exc:
                _log.warning("Pillow metadata extraction failed for %s: %s", path, exc)

        return metadata
