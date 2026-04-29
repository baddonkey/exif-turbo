from __future__ import annotations

import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

try:
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:
    _RAWPY_AVAILABLE = False

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...indexing.image_utils import RAW_EXTENSIONS, orient_raw_thumb
from ...utils.thumb_cache import thumb_cache_name_from_stamp, thumb_cache_path

_THUMB_SIZE = (144, 144)

# Alias for readability within this module
_RAW_EXTENSIONS = RAW_EXTENSIONS


def _open_image(path: str) -> Image.Image:
    """Open any image as a Pillow Image, using rawpy for RAW files."""
    ext = Path(path).suffix.lower()
    if ext in _RAW_EXTENSIONS and _RAWPY_AVAILABLE:
        with rawpy.imread(path) as raw:
            raw_flip = raw.sizes.flip
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    img = Image.open(io.BytesIO(thumb.data))
                    img.load()   # detach from BytesIO before context exits
                else:
                    img = Image.fromarray(thumb.data)
            except rawpy.LibRawNoThumbnailError:
                # postprocess() applies orientation automatically.
                rgb = raw.postprocess(use_camera_wb=True, half_size=True)
                return Image.fromarray(rgb)
        return orient_raw_thumb(img, raw_flip)
    img = Image.open(path)
    return ImageOps.exif_transpose(img)


class ThumbWorker(QThread):
    finished = Signal(int, int)
    failed = Signal(str)
    progress = Signal(int, int, str)
    canceled = Signal(int, int)

    def __init__(
        self,
        db_path: Path,
        cache_dir: Path,
        max_thumb_bytes: int,
        workers: int = 1,
        key: str = "",
        excluded_paths: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self.cache_dir = cache_dir
        self.max_thumb_bytes = max_thumb_bytes
        self.workers = max(1, workers)
        self._key = key
        # Normalised prefix strings for disabled folders — images whose path
        # starts with any of these are skipped entirely.
        self._excluded_prefixes: tuple[str, ...] = tuple(
            os.path.normpath(p) + os.sep for p in (excluded_paths or [])
        )
        self._cancel_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()  # starts unpaused

    def cancel(self) -> None:
        self._cancel_event.set()
        self._resume_event.set()  # unblock any waiting build_thumb

    def pause(self) -> None:
        """Temporarily suspend thumbnail I/O to yield bandwidth to the preview."""
        self._resume_event.clear()

    def resume(self) -> None:
        """Resume thumbnail building after a preview has had time to load."""
        self._resume_event.set()

    def run(self) -> None:
        try:
            # Read paths and stamps from the DB on this background thread —
            # keeps the main thread free so QML can paint thumbnails immediately.
            repo = ImageIndexRepository(self._db_path, key=self._key)
            all_stamps = repo.get_all_stamps()
            repo.close()

            # Drop images that belong to disabled (excluded) folders.
            if self._excluded_prefixes:
                stamps = {
                    p: s for p, s in all_stamps.items()
                    if not os.path.normpath(p).startswith(self._excluded_prefixes)
                }
            else:
                stamps = all_stamps

            if self._cancel_event.is_set():
                self.canceled.emit(0, 0)
                return

            self.cache_dir.mkdir(parents=True, exist_ok=True)
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

            # Split all indexed images into already-cached and still-missing.
            # total_all is always the full DB size so the progress counter
            # always matches the user's total image count (e.g. "3/4" not "1/3"
            # when 3 are missing out of 4 total).
            def _expected_cache_name(path: str) -> str:
                stamp = stamps.get(path)
                if stamp is not None:
                    return thumb_cache_name_from_stamp(path, stamp[0], stamp[1])
                return thumb_cache_path(path, self.cache_dir).name

            total_all = len(stamps)
            already_cached = sum(
                1 for p in stamps if _expected_cache_name(p) in existing
            )
            paths = [p for p in stamps if _expected_cache_name(p) not in existing]

            # Announce: current = already cached, total = all images.
            # This way the progress bar shows "3/4" (not "1/3") when 3 are
            # missing out of 4 total, and "4/4" when all are done.
            self.progress.emit(already_cached, total_all, "")

            if self._cancel_event.is_set():
                self.canceled.emit(cached, total_all)
                return

            def build_thumb(path: str) -> bool:
                if not path:
                    return False
                # Yield to preview loads: wait while paused (2s max safety valve)
                if not self._resume_event.is_set():
                    self._resume_event.wait(timeout=2.0)
                if self._cancel_event.is_set():
                    return False
                # Compute cache filename — use DB stamp to avoid network stat
                stamp = stamps.get(path)
                if stamp is not None:
                    cache_name = thumb_cache_name_from_stamp(path, stamp[0], stamp[1])
                    cache_path_obj = self.cache_dir / cache_name
                else:
                    cache_path_obj = thumb_cache_path(path, self.cache_dir)
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

            if self.workers > 1 and len(paths) > 0:
                executor = ThreadPoolExecutor(max_workers=self.workers)
                futures = {executor.submit(build_thumb, path): path for path in paths}
                completed = already_cached
                try:
                    for future in as_completed(futures):
                        if self._cancel_event.is_set():
                            self.canceled.emit(cached, total_all)
                            return
                        path = futures[future]
                        completed += 1
                        self.progress.emit(completed, total_all, path)
                        if future.result():
                            cached += 1
                finally:
                    executor.shutdown(wait=not self._cancel_event.is_set(), cancel_futures=True)
            else:
                for idx, path in enumerate(paths, start=1):
                    if self._cancel_event.is_set():
                        self.canceled.emit(cached, total_all)
                        return
                    self.progress.emit(already_cached + idx, total_all, path)
                    if build_thumb(path):
                        cached += 1

            if self._cancel_event.is_set():
                self.canceled.emit(cached, total_all)
            else:
                self.finished.emit(cached, total_all)
        except Exception as exc:
            self.failed.emit(str(exc))
