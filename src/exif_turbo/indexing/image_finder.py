from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .image_utils import is_image_file


class ImageFinder:
    def iter_images(self, folders: Iterable[Path]) -> Iterable[Path]:
        for folder in folders:
            if not folder.exists():
                continue
            for root, _, files in os.walk(folder):
                for file_name in files:
                    path = Path(root) / file_name
                    if is_image_file(path):
                        yield path
