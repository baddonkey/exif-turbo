from __future__ import annotations

import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:
    _RAWPY_AVAILABLE = False

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtCore import QThread, Signal

from ...utils.thumb_cache import thumb_cache_name_from_stamp, thumb_cache_path

_THUMB_SIZE = (144, 144)

# RAW extensions handled via rawpy (libraw)
_RAW_EXTENSIONS = {
    ".cr2", ".cr3",          # Canon
    ".nef", ".nrw",          # Nikon
    ".arw", ".srf", ".sr2",  # Sony
    ".dng",                   # Adobe DNG
    ".orf",                   # Olympus
    ".rw2",                   # Panasonic
    ".pef",                   # Pentax
    ".raf",                   # Fujifilm
    ".rwl",                   # Leica
    ".srw",                   # Samsung
}


def _open_image(path: str) -> Image.Image:
    """Open any image as a Pillow Image, using rawpy for RAW files."""
    ext = Path(path).suffix.lower()
    if ext in _RAW_EXTENSIONS and _RAWPY_AVAILABLE:
        with rawpy.imread(path) as raw:
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    img = Image.open(io.BytesIO(thumb.data))
                    img.load()   # detach from BytesIO before context exits
                    return img
                else:
                    return Image.fromarray(thumb.data)
            except rawpy.LibRawNoThumbnailError:
                # Fall back to full demosaic
                rgb = raw.postprocess(use_camera_wb=True, half_size=True)
                return Image.fromarray(rgb)
    img = Image.open(path)
    return ImageOps.exif_transpose(img)


class ThumbWorker(QThread):
    finished = Signal(int, int)
    failed = Signal(str)
    progress = Signal(int, int, str)
    canceled = Signal(int, int)

    def __init__(
        self,
        paths: List[str],
        cache_dir: Path,
        max_thumb_bytes: int,
        workers: int = 1,
        stamps: Optional[Dict[str, Tuple[float, int]]] = None,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.cache_dir = cache_dir
        self.max_thumb_bytes = max_thumb_bytes
        self.workers = max(1, workers)
        self._stamps = stamps or {}
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            total = len(self.paths)
            cached = 0

            # Pre-scan cache dir once — O(1) set lookup replaces per-file exists()
            existing: set[str] = set()
            try:
                with os.scandir(self.cache_dir) as it:
                    for entry in it:
                        if entry.name.endswith(".png"):
                            existing.add(entry.name)
            except OSError:
                pass

            def build_thumb(path: str) -> bool:
                if not path:
                    return False
                # Compute cache filename — use DB stamp to avoid network stat
                stamp = self._stamps.get(path)
                if stamp is not None:
                    cache_name = thumb_cache_name_from_stamp(path, stamp[0], stamp[1])
                    if cache_name in existing:
                        return True
                    cache_path_obj = self.cache_dir / cache_name
                else:
                    cache_path_obj = thumb_cache_path(path, self.cache_dir)
                    if cache_path_obj.name in existing:
                        return True
                try:
                    if os.path.getsize(path) > self.max_thumb_bytes:
                        return False
                except OSError:
                    return False
                try:
                    img = _open_image(path)
                    img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
                    img.save(str(cache_path_obj), "PNG")
                    existing.add(cache_path_obj.name)
                    return True
                except (UnidentifiedImageError, OSError, Exception):
                    return False

            if self.workers > 1 and total > 0:
                executor = ThreadPoolExecutor(max_workers=self.workers)
                futures = {executor.submit(build_thumb, path): path for path in self.paths}
                completed = 0
                try:
                    for future in as_completed(futures):
                        if self._cancel_event.is_set():
                            self.canceled.emit(cached, total)
                            return
                        path = futures[future]
                        completed += 1
                        self.progress.emit(completed, total, path)
                        if future.result():
                            cached += 1
                finally:
                    executor.shutdown(wait=not self._cancel_event.is_set(), cancel_futures=True)
            else:
                for idx, path in enumerate(self.paths, start=1):
                    if self._cancel_event.is_set():
                        self.canceled.emit(cached, total)
                        return
                    self.progress.emit(idx, total, path)
                    if build_thumb(path):
                        cached += 1

            if self._cancel_event.is_set():
                self.canceled.emit(cached, total)
            else:
                self.finished.emit(cached, total)
        except Exception as exc:
            self.failed.emit(str(exc))

