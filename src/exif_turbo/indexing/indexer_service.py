from __future__ import annotations

import json
import logging
import queue
import threading
from calendar import timegm
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as cf_wait
from pathlib import Path
from time import strptime
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


# EXIF date keys tried in priority order (exiftool -g1 format: "Group:Tag").
_EXIF_DATE_KEYS = [
    "ExifIFD:DateTimeOriginal",
    "ExifIFD:CreateDate",
    "IFD0:DateTimeOriginal",
    "IFD0:CreateDate",
    "Composite:SubSecDateTimeOriginal",
]
# exiftool date format (with -n: numeric, dates keep string format).
_EXIF_DT_FMT = "%Y:%m:%d %H:%M:%S"
# Date-only format used by e.g. IPTC:DateCreated.
_EXIF_DATE_ONLY_FMT = "%Y:%m:%d"
# Oldest timestamp accepted by the secondary-key scan: 1900-01-01 UTC.
_MIN_SANE_YEAR_TS: float = float(timegm((1900, 1, 1, 0, 0, 0, 0, 1, 0)))
# Secondary capture/creation keys tried when the primary list yields nothing.
# Deliberately excludes infrastructure groups (ICC_Profile:, JFIF:, APP14:,
# etc.) whose dates reflect software/standard creation, not image capture.
_SECONDARY_DATE_KEYS: list[str] = [
    "XMP-xmp:CreateDate",
    "XMP-photoshop:DateCreated",
    "XMP-exif:DateTimeOriginal",
    "XMP-tiff:DateTime",
    "IPTC:DateCreated",
    "QuickTime:CreateDate",
    "QuickTime:TrackCreateDate",
    "QuickTime:MediaCreateDate",
    # Modification date is last resort — edit time, not capture,
    # but better than ICC_Profile or filesystem for scanned/archival images.
    "IFD0:ModifyDate",
    "ExifIFD:ModifyDate",
]


def _try_parse_exif_dt(raw: str) -> float | None:
    """Parse an ExifTool date string to a UTC epoch float.

    Handles sub-second suffixes ("2023:06:15 10:30:00.789"), timezone suffixes
    ("2023:06:15 10:30:00+02:00"), and date-only values ("2023:06:15").
    Returns None if the value cannot be parsed.
    """
    base = raw.split(".")[0].strip()
    # Full datetime: truncate to 19 chars to drop any trailing timezone.
    if len(base) >= 19:
        try:
            return float(timegm(strptime(base[:19], _EXIF_DT_FMT)))
        except ValueError:
            pass
    # Date-only (e.g. IPTC:DateCreated): truncate to 10 chars.
    if len(base) >= 10:
        try:
            return float(timegm(strptime(base[:10], _EXIF_DATE_ONLY_FMT)))
        except ValueError:
            pass
    return None


def _resolve_captured_at(metadata: Dict[str, str], path: Path, mtime: float) -> float | None:
    """Return a UTC Unix timestamp for when the image was captured.

    Priority:
    1. EXIF date tags (DateTimeOriginal / CreateDate, etc.) — treated as local
       wall-clock time and stored as UTC epoch (no timezone conversion, same
       approach used by most EXIF consumers).
    2. Oldest parseable date among _SECONDARY_DATE_KEYS — XMP, IPTC,
       QuickTime, and modification tags.  Deliberately excludes infrastructure
       groups (ICC_Profile:, JFIF:, etc.) whose dates reflect software/standard
       creation, not image capture.
    3. Oldest parseable date among System:File* keys reported by exiftool
       (e.g. System:FileModifyDate, System:FileCreateDate).
    4. File creation time (st_birthtime on macOS, st_ctime on Windows).
    5. File modification time (mtime) as last resort on Linux where no
       creation time is available.
    Returns None only if everything fails.
    """
    for key in _EXIF_DATE_KEYS:
        raw = metadata.get(key, "")
        if not raw:
            continue
        # Some values have a sub-second suffix: "2023:06:15 12:34:56.789"
        raw_base = raw.split(".")[0].strip()
        try:
            t = strptime(raw_base, _EXIF_DT_FMT)
            return float(timegm(t))
        except ValueError:
            continue

    # Second pass: try an explicit allowlist of secondary capture/creation keys.
    # ICC_Profile:, JFIF:, and similar infrastructure groups are not included
    # because their dates reflect software/standard creation, not image capture.
    _tried = frozenset(_EXIF_DATE_KEYS)
    candidates: list[float] = []
    for key in _SECONDARY_DATE_KEYS:
        if key in _tried:
            continue
        raw = metadata.get(key, "")
        if not raw:
            continue
        ts = _try_parse_exif_dt(raw)
        if ts is not None and ts >= _MIN_SANE_YEAR_TS:
            candidates.append(ts)
    if candidates:
        return min(candidates)

    # Third pass: System:File*Date* keys reported by exiftool itself.
    # Takes the oldest to match the secondary-key strategy.
    sys_candidates: list[float] = []
    for key, raw in metadata.items():
        if not key.startswith("System:File") or "Date" not in key or not raw:
            continue
        ts = _try_parse_exif_dt(raw)
        if ts is not None and ts >= _MIN_SANE_YEAR_TS:
            sys_candidates.append(ts)
    if sys_candidates:
        return min(sys_candidates)

    # Fall back to file-system timestamps.
    try:
        st = path.stat()
        # macOS / FreeBSD: st_birthtime is the true creation time.
        birth = getattr(st, "st_birthtime", None)
        if birth is not None:
            return float(birth)
        # Windows: st_ctime is the file creation time (not "change time").
        import os as _os
        if _os.name == "nt":
            return float(st.st_ctime)
    except OSError:
        pass

    # Linux last resort: use mtime.
    return mtime


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
                captured_at = _resolve_captured_at(metadata, path, mtime)
                return IndexedImage(
                    path=str(path),
                    filename=path.name,
                    mtime=mtime,
                    size=size,
                    metadata=metadata,
                    metadata_text=metadata_text,
                    captured_at=captured_at,
                )
            except Exception as exc:
                _log.warning("Skipping %s: %s", path, exc)
                return None

        def should_cancel() -> bool:
            return bool(cancel_check and cancel_check())

        _BATCH_SIZE = 100
        _write_batch: list[tuple[str, str, float, int, dict, str, int | None]] = []

        def flush_batch() -> None:
            if _write_batch:
                self.repo.upsert_images_batch(_write_batch)
                _write_batch.clear()

        def record(item: IndexedImage | None | _UnchangedType, path: Path) -> None:
            nonlocal count, error_count
            if isinstance(item, _UnchangedType):
                existing_paths.append(str(path))
                count += 1
                return
            if not item:
                error_count += 1
                return
            _write_batch.append((
                item.path, item.filename, item.mtime, item.size,
                item.metadata, item.metadata_text, folder_id, item.captured_at,
            ))
            existing_paths.append(item.path)
            count += 1
            if len(_write_batch) >= _BATCH_SIZE:
                flush_batch()

        if workers > 1:
            # Multi-worker pipeline: scanner + EXIF extraction overlap.
            # Phase A (scan in progress): submit futures as entries arrive,
            #   collect any that finish early, emit (completed, 0, path).
            # Phase B (scan done): emit sentinel (0, total, Path("")), then
            #   drain remaining futures emitting (completed, total, path).
            #
            # Backpressure: cap pending to workers*4 so the dict never grows
            # to tens-of-thousands of entries when scanning outpaces extraction.
            _MAX_PENDING = workers * 4
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
                            # Backpressure: drain at least one future before
                            # submitting when the cap is reached.
                            if len(pending) >= _MAX_PENDING:
                                drain, _ = cf_wait(
                                    set(pending.keys()),
                                    timeout=1.0,
                                    return_when=FIRST_COMPLETED,
                                )
                                for future in drain:
                                    if should_cancel():
                                        canceled = True
                                        break
                                    f_path = pending.pop(future)
                                    completed += 1
                                    if on_progress:
                                        on_progress(completed, 0, f_path)
                                    record(future.result(), f_path)
                                if canceled:
                                    break
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

        # Flush any remaining buffered writes before the cleanup phase.
        if not canceled:
            flush_batch()
            # Fold the WAL into the main DB file now that all writes are done.
            # One checkpoint here (rather than after every batch) avoids I/O
            # pressure on the indexer thread during scanning, which was causing
            # the UI to stall when the search connection tried concurrent reads.
            # PASSIVE is non-blocking: it folds whatever the search connection
            # isn't currently reading and returns immediately.
            self.repo.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

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
