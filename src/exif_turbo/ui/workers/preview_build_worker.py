"""Background worker that renders preview JPEGs for one indexed folder.

Counterpart to :class:`ThumbWorker`: scans the cache directory once,
renders only the missing previews, and writes them as JPEGs (encrypted
with :class:`ThumbCrypto` when a DB key is set).

Independent of the thumbnail worker — they may run concurrently.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...utils.preview_cache import preview_cache_name_from_stamp, preview_dir
from ...utils.preview_render import render_preview
from ...utils.thumb_crypto import ThumbCrypto
from ._macos_activity import AppNapAssertion

_log = logging.getLogger(__name__)

_JPEG_QUALITY = 85


def _lower_thread_priority() -> None:
    """Lower the calling thread's OS scheduling priority (best-effort).

    Keeps preview-build threads from competing with the live preview
    provider threads, which run at HighPriority on Qt's async pool.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            # THREAD_PRIORITY_BELOW_NORMAL = -1
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), -1
            )
        except Exception:  # noqa: BLE001
            pass
    elif sys.platform == "darwin":
        try:
            import ctypes
            # PRIO_DARWIN_THREAD (3) scopes setpriority() to the calling thread
            # only — unlike nice() which lowers the whole process on macOS.
            libc = ctypes.CDLL("libSystem.B.dylib", use_errno=True)
            libc.setpriority(3, 0, 10)
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            # Linux: setpriority(PRIO_PROCESS, tid, niceness) where tid is the
            # kernel thread ID scopes the change to the calling thread only.
            import ctypes
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            tid = libc.syscall(186)  # SYS_gettid
            libc.setpriority(0, tid, 10)  # PRIO_PROCESS = 0
        except Exception:  # noqa: BLE001
            pass


class PreviewBuildWorker(QThread):
    """Render preview JPEGs for every image associated with one folder."""

    finished = Signal(int, int)          # built, total_in_folder
    failed = Signal(str)                 # error message
    progress = Signal(int, int, str)     # done, total_missing, current_path
    canceled = Signal(int, int)          # built, total_in_folder

    def __init__(
        self,
        db_path: Path,
        cache_dir: Path,
        folder_id: int,
        target_long_edge: int,
        *,
        workers: int = 1,
        key: str = "",
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._cache_dir = cache_dir
        self._folder_id = folder_id
        self._target = target_long_edge
        self._workers = max(1, workers)
        self._key = key
        self._cancel_event = threading.Event()

    @property
    def folder_id(self) -> int:
        return self._folder_id

    def cancel(self) -> None:
        self._cancel_event.set()

    # ── QThread.run ──────────────────────────────────────────────────────

    def run(self) -> None:  # noqa: C901 — mirror of ThumbWorker structure
        _nap = AppNapAssertion("Building image previews")
        try:
            repo = ImageIndexRepository(self._db_path, key=self._key)
            try:
                stamps = repo.get_folder_stamps(self._folder_id)
            finally:
                repo.close()

            total = len(stamps)
            if self._cancel_event.is_set() or total == 0:
                # Nothing to do — emit a zero-progress finished so the UI clears.
                if self._cancel_event.is_set():
                    self.canceled.emit(0, total)
                else:
                    self.finished.emit(0, total)
                return

            out_dir = preview_dir(self._cache_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            crypto = ThumbCrypto(self._key, self._cache_dir)
            ext = ".jpg.enc" if crypto.is_active else ".jpg"

            existing = _scan_existing(out_dir, encrypted=crypto.is_active)

            def expected_name(path: str) -> str:
                stamp = stamps[path]
                base = preview_cache_name_from_stamp(path, stamp[0], stamp[1])
                return base[:-4] + ext  # swap .jpg for .jpg or .jpg.enc

            paths = [p for p in stamps if expected_name(p) not in existing]
            missing = len(paths)
            self.progress.emit(0, missing, "")

            built = 0

            def build_one(path: str) -> bool:
                if self._cancel_event.is_set():
                    return False
                if not os.path.exists(path):
                    return False
                try:
                    img = render_preview(path, self._target)
                    buf = io.BytesIO()
                    # Drop alpha for JPEG; flatten transparent pixels onto white.
                    if img.mode in ("RGBA", "LA", "P"):
                        img = img.convert("RGB")
                    img.save(buf, "JPEG", quality=_JPEG_QUALITY, optimize=True)
                    name = expected_name(path)
                    out_path = out_dir / name
                    if crypto.is_active:
                        out_path.write_bytes(crypto.encrypt(buf.getvalue()))
                    else:
                        out_path.write_bytes(buf.getvalue())
                    return True
                except Exception as exc:  # noqa: BLE001
                    _log.warning("Preview build failed for %r: %s", path, exc)
                    return False

            if self._workers > 1 and missing > 0:
                with ThreadPoolExecutor(
                    max_workers=self._workers,
                    initializer=_lower_thread_priority,
                ) as executor:
                    futures = {executor.submit(build_one, p): p for p in paths}
                    completed = 0
                    for future in as_completed(futures):
                        if self._cancel_event.is_set():
                            executor.shutdown(wait=False, cancel_futures=True)
                            self.canceled.emit(built, total)
                            return
                        path = futures[future]
                        completed += 1
                        self.progress.emit(completed, missing, path)
                        if future.result():
                            built += 1
            else:
                _lower_thread_priority()
                for idx, path in enumerate(paths, start=1):
                    if self._cancel_event.is_set():
                        self.canceled.emit(built, total)
                        return
                    self.progress.emit(idx, missing, path)
                    if build_one(path):
                        built += 1

            if self._cancel_event.is_set():
                self.canceled.emit(built, total)
            else:
                self.finished.emit(built, total)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            _nap.release()


def _scan_existing(out_dir: Path, *, encrypted: bool) -> set[str]:
    """Return the set of preview filenames already present in *out_dir*."""
    suffix = ".jpg.enc" if encrypted else ".jpg"
    found: set[str] = set()
    try:
        with os.scandir(out_dir) as it:
            for entry in it:
                if entry.name.endswith(suffix):
                    found.add(entry.name)
    except OSError:
        pass
    return found
