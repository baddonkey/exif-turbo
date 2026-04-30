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

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError
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
    # Read all bytes first so the codec decodes from memory rather than making
    # many small seeks over a network share (NFS/SMB TIFF codecs are especially
    # seek-heavy — reading bytes sequentially first is orders of magnitude faster).
    with open(path, "rb") as f:
        data = f.read()
    buf = io.BytesIO(data)
    try:
        img = Image.open(buf)
        img.load()
    except UnidentifiedImageError:
        # Pillow 12 treats some valid-but-unusual files (e.g. 16-bit RGBA PNGs
        # with large metadata chunks) as truncated.  Retry with the truncated-
        # image flag so we still produce a thumbnail rather than silently skip.
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            buf.seek(0)
            img = Image.open(buf)
            img.load()
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
    img = ImageOps.exif_transpose(img)
    # Convert 16-bit / raw-mode images (e.g. mode "I;16" from 16-bit TIFFs) to
    # RGB before resampling.  LANCZOS on Pillow's integer/float modes is
    # extremely slow — converting to 8-bit first gives identical visual quality
    # for a 144×144 thumbnail and avoids multi-minute hangs.
    if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGB")
    return img


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

            # Pre-scan cache dir once — O(1) set lookup replaces per-file exists().
            # A ".skip" sentinel (e.g. abc123.skip) is written when thumbnailing
            # fails permanently (unsupported format, file too large).  We store the
            # corresponding ".png" name in `existing` so those images are excluded
            # from `paths` on every subsequent run.
            existing: set[str] = set()
            try:
                with os.scandir(self.cache_dir) as it:
                    for entry in it:
                        if entry.name.endswith(".png"):
                            existing.add(entry.name)
                        elif entry.name.endswith(".skip"):
                            existing.add(entry.name[:-5] + ".png")
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
            missing_total = len(paths)

            # Announce: 0 out of missing_total thumbnails built yet.
            # Only counts images that actually need building — so a rescan
            # of 87 images shows "0 / 8" instead of "44660 / 44668".
            self.progress.emit(0, missing_total, "")

            if self._cancel_event.is_set():
                self.canceled.emit(cached, total_all)
                return

            skip_log = self.cache_dir / "thumbs_skipped.log"

            def _mark_skip(cache_path_obj: Path, reason: str) -> None:
                """Write a .skip sentinel (containing the reason) so this image
                is excluded on future runs, and append a line to the skip log."""
                try:
                    cache_path_obj.with_suffix(".skip").write_text(
                        reason, encoding="utf-8"
                    )
                    existing.add(cache_path_obj.name)  # exclude for rest of this run
                except OSError:
                    pass
                try:
                    with skip_log.open("a", encoding="utf-8") as f:
                        f.write(f"{cache_path_obj.stem}\t{reason}\n")
                except OSError:
                    pass

            def build_thumb(path: str) -> bool:
                if not path:
                    return False
                # Skip immediately if the file is not reachable — avoids a
                # multi-second hang when a NAS or external volume is offline.
                if not os.path.exists(path):
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
                        size_mb = os.path.getsize(path) // (1024 * 1024)
                        _mark_skip(cache_path_obj, f"file too large ({size_mb} MB): {path}")
                        return False
                except OSError:
                    return False  # transient (e.g. NAS offline) — don't mark as skip
                try:
                    img = _open_image(path)
                    img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
                    img.save(str(cache_path_obj), "PNG")
                    existing.add(cache_path_obj.name)
                    return True
                except (UnidentifiedImageError, OSError, Exception) as exc:
                    _mark_skip(cache_path_obj, f"{type(exc).__name__}: {exc} — {path}")
                    return False

            if self.workers > 1 and len(paths) > 0:
                executor = ThreadPoolExecutor(max_workers=self.workers)
                futures = {executor.submit(build_thumb, path): path for path in paths}
                missing_completed = 0
                try:
                    for future in as_completed(futures):
                        if self._cancel_event.is_set():
                            self.canceled.emit(cached, total_all)
                            return
                        path = futures[future]
                        missing_completed += 1
                        self.progress.emit(missing_completed, missing_total, path)
                        if future.result():
                            cached += 1
                finally:
                    executor.shutdown(wait=not self._cancel_event.is_set(), cancel_futures=True)
            else:
                for idx, path in enumerate(paths, start=1):
                    if self._cancel_event.is_set():
                        self.canceled.emit(cached, total_all)
                        return
                    self.progress.emit(idx, missing_total, path)
                    if build_thumb(path):
                        cached += 1

            if self._cancel_event.is_set():
                self.canceled.emit(cached, total_all)
            else:
                self.finished.emit(cached, total_all)
        except Exception as exc:
            self.failed.emit(str(exc))
