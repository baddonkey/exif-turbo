from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as cf_wait
from pathlib import Path
from typing import Callable, Dict, List

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
    ) -> int:
        existing_paths: List[str] = []
        count = 0
        canceled = False

        if force:
            self.repo.clear_all()

        # Collect paths lazily so cancel_check fires per-file during discovery.
        paths = list(self.finder.iter_images(folders, cancel_check=cancel_check))
        if cancel_check and cancel_check():
            return 0
        total = len(paths)
        if total == 0:
            return 0

        # Snapshot of DB stamps — used to skip unchanged files without re-reading EXIF.
        # Empty when force=True so every file is re-extracted.
        known_stamps = {} if force else self.repo.get_all_stamps()
        if cancel_check and cancel_check():
            return 0

        def build_item(path: Path) -> IndexedImage | None | _UnchangedType:
            # Fast bail-out: don't start a new (potentially slow) extraction after cancel.
            if cancel_check and cancel_check():
                return None
            try:
                stat = path.stat()
                stamp = known_stamps.get(str(path))
                if stamp and stamp[0] == stat.st_mtime and stamp[1] == stat.st_size:
                    return _UNCHANGED
                if cancel_check and cancel_check():
                    return None
                metadata = self.extractor.extract(path)
                metadata_text = metadata_to_text(metadata)
                return IndexedImage(
                    path=str(path),
                    filename=path.name,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    metadata=metadata,
                    metadata_text=metadata_text,
                )
            except Exception:
                return None

        def should_cancel() -> bool:
            return bool(cancel_check and cancel_check())

        def record(item: IndexedImage | None | _UnchangedType, path: Path) -> None:
            nonlocal count
            if isinstance(item, _UnchangedType):
                existing_paths.append(str(path))
                count += 1
                return
            if not item:
                return
            self.repo.upsert_image(
                item.path,
                item.filename,
                item.mtime,
                item.size,
                item.metadata,
                item.metadata_text,
            )
            existing_paths.append(item.path)
            count += 1

        if workers > 1 and total > 0:
            executor = ThreadPoolExecutor(max_workers=workers)
            # Submit incrementally so cancel_check is tested before each submission,
            # rather than submitting all 40K futures at once.
            futures: dict = {}
            completed = 0
            try:
                for path in paths:
                    if should_cancel():
                        canceled = True
                        break
                    futures[executor.submit(build_item, path)] = path
                if not canceled:
                    # Poll with a short timeout so cancel_check is tested every 200 ms
                    # regardless of how long individual EXIF extractions take.
                    pending = set(futures.keys())
                    while pending:
                        if should_cancel():
                            canceled = True
                            break
                        done, pending = cf_wait(
                            pending, timeout=0.2, return_when=FIRST_COMPLETED
                        )
                        for future in done:
                            if should_cancel():
                                canceled = True
                                break
                            path = futures[future]
                            completed += 1
                            if on_progress:
                                on_progress(completed, total, path)
                            record(future.result(), path)
                        if canceled:
                            break
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            for idx, path in enumerate(paths, start=1):
                if should_cancel():
                    canceled = True
                    break
                if on_progress:
                    on_progress(idx, total, path)
                record(build_item(path), path)

        # Only purge stale DB rows when the scan completed fully.  Calling
        # delete_missing on a partial/canceled scan would wipe every file that
        # wasn't reached yet — potentially deleting the entire index.
        if not canceled:
            self.repo.delete_missing(existing_paths)
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

        return count
