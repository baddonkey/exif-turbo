from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Protocol

from PIL import Image

from .db import ImageIndexRepository

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".png", ".bmp", ".gif", ".webp"}


@dataclass
class IndexedImage:
    path: str
    filename: str
    mtime: float
    size: int
    metadata: Dict[str, str]
    metadata_text: str


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


class MetadataExtractor(Protocol):
    def extract(self, path: Path) -> Dict[str, str]:
        ...


class ExifMetadataExtractor:
    def extract(self, path: Path) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        try:
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
        except Exception:
            pass

        if path.suffix.lower() in {".png", ".gif", ".bmp", ".webp"}:
            try:
                with Image.open(path) as im:
                    info = getattr(im, "info", {}) or {}
                    for key, value in info.items():
                        metadata[f"PIL:{key}"] = str(value)
            except Exception:
                pass

        return metadata


def metadata_to_text(metadata: Dict[str, str]) -> str:
    parts: List[str] = []
    for key, value in metadata.items():
        parts.append(key)
        parts.append(value)
    parts.append(json.dumps(metadata, ensure_ascii=False))
    return " ".join(parts)


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
    ) -> int:
        self.repo.clear_all()
        existing_paths: List[str] = []
        count = 0
        canceled = False

        paths = list(self.finder.iter_images(folders))
        total = len(paths)

        def build_item(path: Path) -> IndexedImage | None:
            try:
                stat = path.stat()
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

        if workers > 1 and total > 0:
            executor = ThreadPoolExecutor(max_workers=workers)
            futures = {executor.submit(build_item, path): path for path in paths}
            completed = 0
            try:
                for future in as_completed(futures):
                    if should_cancel():
                        canceled = True
                        break
                    path = futures[future]
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, path)
                    item = future.result()
                    if not item:
                        continue
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
            finally:
                executor.shutdown(wait=not canceled, cancel_futures=True)
        else:
            for idx, path in enumerate(paths, start=1):
                if should_cancel():
                    canceled = True
                    break
                if on_progress:
                    on_progress(idx, total, path)
                item = build_item(path)
                if not item:
                    continue
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
