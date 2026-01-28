from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QImageReader

from ...utils.thumb_cache import thumb_cache_path


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
    ) -> None:
        super().__init__()
        self.paths = paths
        self.cache_dir = cache_dir
        self.max_thumb_bytes = max_thumb_bytes
        self.workers = max(1, workers)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            total = len(self.paths)
            cached = 0

            def build_thumb(path: str) -> bool:
                if not path:
                    return False
                cache_path = thumb_cache_path(path, self.cache_dir)
                if cache_path.exists():
                    return True
                try:
                    if os.path.getsize(path) > self.max_thumb_bytes:
                        return False
                except OSError:
                    return False
                reader = QImageReader(path)
                reader.setAutoTransform(True)
                image = reader.read()
                if image.isNull():
                    return False
                scaled = image.scaled(
                    144,
                    144,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                if scaled.isNull():
                    return False
                return scaled.save(str(cache_path), "PNG")

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
