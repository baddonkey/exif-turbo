from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from ..config import load_config
from .image_utils import is_image_file


class ImageFinder:
    def __init__(
        self,
        *,
        skip_dotfiles: bool | None = None,
        blacklist: List[str] | None = None,
    ) -> None:
        if skip_dotfiles is None:
            skip_dotfiles = load_config().skip_dotfiles
        self.skip_dotfiles = skip_dotfiles
        # Patterns matched against individual path components (name or partial path)
        self._blacklist: List[str] = list(blacklist) if blacklist else []

    def _is_blacklisted(self, path: Path) -> bool:
        """Return True if *any* component of path matches a blacklist pattern."""
        if not self._blacklist:
            return False
        parts = path.parts
        for pattern in self._blacklist:
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    def iter_images(
        self,
        folders: Iterable[Path],
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Iterable[Path]:
        for folder in folders:
            if not folder.exists():
                continue
            for root, dirs, files in os.walk(folder):
                if cancel_check and cancel_check():
                    return
                root_path = Path(root)
                # Prune blacklisted directories in-place so os.walk skips them
                dirs[:] = [
                    d for d in dirs
                    if not self._is_blacklisted(root_path / d)
                ]
                for file_name in files:
                    if self.skip_dotfiles and file_name.startswith("."):
                        continue
                    path = root_path / file_name
                    if self._is_blacklisted(path):
                        continue
                    if is_image_file(path):
                        yield path

