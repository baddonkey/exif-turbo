from __future__ import annotations

import json
import logging
import queue
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as cf_wait
from pathlib import Path
from typing import Callable, Dict, List

_log = logging.getLogger(__name__)

from ..data.image_index_repository import ImageIndexRepository
from ..models.indexed_image import IndexedImage
from .exif_metadata_extractor import ExifMetadataExtractor
from .image_finder import ImageFinder
from .metadata_extractor import MetadataExtractor


class _UnchangedType:
    """Sentinel: the file's mtime/size match the DB — no re-extraction needed."""


_UNCHANGED = _UnchangedType()


def metadata_to_text(metadata: Dict[str, str]) -> str:
    parts: List[str] = []
    for key, value in metadata.items():
        parts.append(key)
        parts.append(value)
    parts.append(json.dumps(metadata, ensure_ascii=False))
    return " ".join(parts)


class IndexerService:
    def __init__(
        self,
        repo: ImageIndexRepository,
        extractor: MetadataExtractor | None = None,
        finder: ImageFinder | None = None,
    ) -> None:
        self.repo = repo
        self.extractor = extractor or ExifMetadataExtractor()
        self.finder = finder or ImageFinder()

    def build_index(
        self,
        folders: List[Path],
        json_path: Path | None = None,
        on_progress: Callable[[int, int, Path], None] | None = None,
        workers: int = 1,
        cancel_check: Callable[[], bool] | None = None,
        force: bool = False,
        folder_id: int | None = None,
    ) -> tuple[int, int]:  # (indexed_count, error_count)
        existing_paths: List[str] = []
        count = 0
        error_count = 0
        canceled = False
        scan_total = 0

        if force:
            # Wipe only the rows that belong to the folders being rescanned.
            # clear_all() would destroy images from every other folder.
            self.repo.delete_missing([], folder_roots=[str(f) for f in folders])

        # Fetch DB stamps upfront so the pipeline can start comparing immediately
        # without waiting for the full scan to finish.
        # Empty when force=True so every file is re-extracted.
        known_stamps = {} if force else self.repo.get_all_stamps()
        if cancel_check and cancel_check():
            return 0, 0

        # ── scanner thread ────────────────────────────────────────────────────
        # iter_images runs in a background thread, pushing FindEntry tuples onto
        # scan_queue.  The main thread (or EXIF pool) consumes immediately so
        # filesystem I/O and EXIF extraction overlap instead of running in
        # sequence.
        #
        # Progress convention (unchanged from before):
        #   on_progress(N, 0, path)         — pipeline active, N indexed so far
        #   on_progress(0, total, Path("")) — scan complete (sentinel, once)
        #   on_progress(N, total, path)     — post-scan extraction (multi-worker)
        _SCAN_DONE: object = object()
        scan_queue: queue.Queue = queue.Queue(maxsize=2000)
        scan_total_ref = [0]

        def _scan_producer() -> None:
            n = 0
            try:
                for entry in self.finder.iter_images(folders, cancel_check=cancel_check):
                    if cancel_check and cancel_check():
                        return
                    while True:
                        try:
                            scan_queue.put(entry, timeout=0.1)
                            break
                        except queue.Full:
                            if cancel_check and cancel_check():
                                return
                    n += 1
            finally:
                scan_total_ref[0] = n
                try:
                    scan_queue.put(_SCAN_DONE, timeout=5.0)
                except queue.Full:
                    pass  # canceled — consumer has already stopped

        scan_thread = threading.Thread(target=_scan_producer, daemon=True)
        scan_thread.start()

        def build_item(
            path: Path,
            find_mtime: float | None,
            find_size: int | None,
        ) -> IndexedImage | None | _UnchangedType:
            # Fast bail-out: don't start a new (potentially slow) extraction after cancel.
            if cancel_check and cancel_check():
                return None
            try:
                stamp = known_stamps.get(str(path))
                if stamp and find_mtime is not None and find_size is not None:
                    # find already called lstat(); use its mtime+size directly.
                    # 1-second tolerance handles BSD stat integer precision on macOS.
                    if int(stamp[0]) == int(find_mtime) and stamp[1] == find_size:
                        return _UNCHANGED
                    # Changed file — trust find's fresh values, no extra stat needed.
                    mtime: float = find_mtime
                    size: int = find_size
                else:
                    # macOS/Windows fallback: no find stamp available.
                    stat = path.stat()
                    if stamp and stamp[0] == stat.st_mtime and stamp[1] == stat.st_size:
                        return _UNCHANGED
                    mtime = stat.st_mtime
                    size = stat.st_size
                if cancel_check and cancel_check():
                    return None
                metadata = self.extractor.extract(path)
                metadata_text = metadata_to_text(metadata)
                return IndexedImage(
                    path=str(path),
                    filename=path.name,
                    mtime=mtime,
                    size=size,
                    metadata=metadata,
                    metadata_text=metadata_text,
                )
            except Exception as exc:
                _log.warning("Skipping %s: %s", path, exc)
                return None

        def should_cancel() -> bool:
            return bool(cancel_check and cancel_check())

        def record(item: IndexedImage | None | _UnchangedType, path: Path) -> None:
            nonlocal count, error_count
            if isinstance(item, _UnchangedType):
                existing_paths.append(str(path))
                count += 1
                return
            if not item:
                error_count += 1
                return
            self.repo.upsert_image(
                item.path,
                item.filename,
                item.mtime,
                item.size,
                item.metadata,
                item.metadata_text,
                folder_id=folder_id,
            )
            existing_paths.append(item.path)
            count += 1

        if workers > 1:
            # Multi-worker pipeline: scanner + EXIF extraction overlap.
            # Phase A (scan in progress): submit futures as entries arrive,
            #   collect any that finish early, emit (completed, 0, path).
            # Phase B (scan done): emit sentinel (0, total, Path("")), then
            #   drain remaining futures emitting (completed, total, path).
            executor = ThreadPoolExecutor(max_workers=workers)
            pending: dict = {}
            completed = 0
            scan_done = False

            try:
                while not canceled:
                    # Ingest next scan item (50 ms timeout so we can also
                    # collect completed futures while the scanner is busy).
                    if not scan_done:
                        try:
                            entry = scan_queue.get(timeout=0.05)
                        except queue.Empty:
                            entry = None

                        if entry is _SCAN_DONE:
                            scan_done = True
                            scan_total = scan_total_ref[0]
                            if scan_total == 0:
                                break
                            if on_progress:
                                on_progress(0, scan_total, Path(""))
                        elif entry is not None:
                            if should_cancel():
                                canceled = True
                                break
                            e_path, find_mtime, find_size = entry
                            pending[
                                executor.submit(build_item, e_path, find_mtime, find_size)
                            ] = e_path

                    # Collect any futures that finished.
                    if scan_done and pending:
                        # Phase B: block until at least one finishes.
                        done_set, _ = cf_wait(
                            set(pending.keys()), timeout=0.2, return_when=FIRST_COMPLETED
                        )
                    else:
                        done_set = {f for f in pending if f.done()}

                    for future in done_set:
                        if should_cancel():
                            canceled = True
                            break
                        f_path = pending.pop(future)
                        completed += 1
                        total_val = scan_total if scan_done else 0
                        if on_progress:
                            on_progress(completed, total_val, f_path)
                        record(future.result(), f_path)

                    if canceled:
                        break
                    if scan_done and not pending:
                        break
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            # Single-worker pipeline: extraction runs in the main thread while
            # the scanner runs in scan_thread.
            while not canceled:
                try:
                    entry = scan_queue.get(timeout=0.1)
                except queue.Empty:
                    if should_cancel():
                        canceled = True
                    continue

                if entry is _SCAN_DONE:
                    scan_total = scan_total_ref[0]
                    break

                if should_cancel():
                    canceled = True
                    break

                e_path, find_mtime, find_size = entry
                record(build_item(e_path, find_mtime, find_size), e_path)
                if on_progress:
                    on_progress(count, 0, e_path)

            if not canceled and scan_total > 0:
                if on_progress:
                    on_progress(0, scan_total, Path(""))

        scan_thread.join(timeout=5.0)

        # Only purge stale DB rows when the scan completed fully.  Calling
        # delete_missing on a partial/canceled scan would wipe every file that
        # wasn't reached yet — potentially deleting the entire index.
        if not canceled:
            self.repo.delete_missing(
                existing_paths,
                folder_roots=[str(f) for f in folders],
                folder_id=folder_id,
            )
        self.repo.commit()

        if json_path and not canceled:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "path": r[0],
                    "filename": r[1],
                    "mtime": r[2],
                    "size": r[3],
                    "metadata": json.loads(r[4]),
                }
                for r in self.repo.all_images()
            ]
            json_path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        if error_count:
            _log.warning(
                "build_index: %d file(s) skipped due to errors out of %d total",
                error_count,
                scan_total,
            )
        return count, error_count
