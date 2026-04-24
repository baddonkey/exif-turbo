from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from ..config import load_config
from .image_utils import is_image_file


class ImageFinder:
    def __init__(self, *, skip_dotfiles: bool | None = None) -> None:
        if skip_dotfiles is None:
            skip_dotfiles = load_config().skip_dotfiles
        self.skip_dotfiles = skip_dotfiles

    def iter_images(self, folders: Iterable[Path]) -> Iterable[Path]:
        for folder in folders:
            if not folder.exists():
                continue
            for root, _, files in os.walk(folder):
                for file_name in files:
                    if self.skip_dotfiles and file_name.startswith("."):
                        continue
                    path = Path(root) / file_name
                    if is_image_file(path):
                        yield path
