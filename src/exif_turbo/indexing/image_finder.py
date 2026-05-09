from __future__ import annotations

import fnmatch
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from ..config import load_config
from .image_utils import IMAGE_EXTENSIONS, is_image_file

# On POSIX systems (macOS / Linux) use ``find`` subprocesses so that all
# getdents()/lstat() syscalls happen inside a C binary — completely outside the
# Python GIL.  On macOS SMB mounts every scandir() entry has DT_UNKNOWN, which
# forces Python to issue an lstat() per file through the GIL, causing event-loop
# freezes with large collections.  Windows SMB returns file attributes inline so
# the os.walk() fallback is perfectly fast there.
_USE_FIND = sys.platform != "win32"

# Number of concurrent ``find`` processes.  Each top-level subdirectory gets
# its own process so the NAS can serve multiple directory walks in parallel.
_FIND_WORKERS = 8

# Sentinel pushed onto the results queue when all worker threads are done.
_SENTINEL = object()

# Type alias: (path, mtime_float_or_None, size_int_or_None)
# mtime/size are None only on the Windows os.walk() fallback.
FindEntry = Tuple[Path, Optional[float], Optional[int]]

_log = logging.getLogger(__name__)


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

    def _name_filter_args(self) -> List[str]:
        """Return the ( -iname "*.jpg" -o … ) portion of the find command."""
        name_args: List[str] = []
        for ext in sorted(IMAGE_EXTENSIONS):
            if name_args:
                name_args.append("-o")
            name_args += ["-iname", f"*{ext}"]
        return ["("] + name_args + [")"]

    def _build_find_cmd(self, target: str, maxdepth: int | None = None) -> List[str]:
        """Build a ``find`` command for *target*.

        On Linux (GNU find): uses -printf to stream path + mtime + size in one
        pass — the data is already in find's lstat() result, zero extra cost.
        On macOS (BSD find): outputs paths only.  stat()-ing files over SMB is
        expensive, so we let the indexer do it only for changed/new files.
        """
        cmd: List[str] = ["find", target, "-type", "f"]
        if maxdepth is not None:
            cmd += ["-maxdepth", str(maxdepth)]
        if self.skip_dotfiles:
            cmd += ["-not", "-name", ".*"]
        cmd += self._name_filter_args()

        if sys.platform == "linux":
            # GNU find: output path TAB mtime_float TAB size in a single pass.
            cmd += ["-printf", "%p\t%T@\t%s\n"]
        # macOS BSD find: just paths — no -exec stat, no extra NAS round-trips.

        return cmd

    def _parse_line(self, line: str) -> FindEntry | None:
        """Parse one output line from find into a (Path, mtime, size) tuple."""
        line = line.rstrip("\n")
        parts = line.rsplit("\t", 2)
        if len(parts) != 3:
            return None
        raw_path, raw_mtime, raw_size = parts
        if not raw_path:
            return None
        try:
            mtime = float(raw_mtime)
            size = int(raw_size)
        except ValueError:
            return None
        return Path(raw_path), mtime, size

    def _get_top_subdirs(self, folder: Path) -> List[Path]:
        """Return immediate non-blacklisted subdirectories of *folder*."""
        cmd = [
            "find", str(folder),
            "-maxdepth", "1", "-mindepth", "1",
            "-type", "d",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        subdirs: List[Path] = []
        for line in result.stdout.splitlines():
            p = Path(line)
            if not self._is_blacklisted(p):
                subdirs.append(p)
        return subdirs

    def _run_find_worker(
        self,
        cmd: List[str],
        out_queue: "queue.Queue[object]",
        cancel_check: Optional[Callable[[], bool]],
        active_procs: List["subprocess.Popen[str]"],
        procs_lock: threading.Lock,
    ) -> None:
        """Run one find command and push FindEntry tuples onto *out_queue*."""
        try:
            proc: "subprocess.Popen[str]" = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return
        with procs_lock:
            active_procs.append(proc)
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if cancel_check and cancel_check():
                    proc.kill()
                    return
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                # Linux: "path\tmtime\tsize"  macOS: "path"
                if "\t" in line:
                    entry = self._parse_line(line)
                    if entry is None:
                        continue
                    file_path, mtime, size = entry
                else:
                    file_path = Path(line)
                    mtime, size = None, None
                if self._is_blacklisted(file_path):
                    continue
                _log.info("found: %s", file_path)
                out_queue.put((file_path, mtime, size))
        finally:
            if proc.stdout:
                proc.stdout.close()
            proc.wait()
            with procs_lock:
                try:
                    active_procs.remove(proc)
                except ValueError:
                    pass

    def _iter_images_find(
        self,
        folder: Path,
        cancel_check: Optional[Callable[[], bool]],
    ) -> Iterable[FindEntry]:
        """Walk *folder* via parallel ``find`` subprocesses.

        On macOS/Linux, find already calls lstat() for -type f.  We attach
        -printf (Linux) or -exec stat (macOS) to surface mtime + size at no
        extra NAS cost, eliminating path.stat() calls in the indexer.
        """
        subdirs = self._get_top_subdirs(folder)

        if not subdirs:
            cmds = [self._build_find_cmd(str(folder))]
        else:
            # Root-level files only (maxdepth=1) + one unlimited find per subdir.
            cmds = [self._build_find_cmd(str(folder), maxdepth=1)]
            for d in subdirs:
                cmds.append(self._build_find_cmd(str(d)))

        out_queue: "queue.Queue[object]" = queue.Queue()
        active_procs: List["subprocess.Popen[str]"] = []
        procs_lock = threading.Lock()
        remaining = [len(cmds)]
        counter_lock = threading.Lock()

        def _worker(cmd: List[str]) -> None:
            try:
                self._run_find_worker(cmd, out_queue, cancel_check, active_procs, procs_lock)
            finally:
                with counter_lock:
                    remaining[0] -= 1
                    if remaining[0] == 0:
                        out_queue.put(_SENTINEL)

        n_workers = min(_FIND_WORKERS, len(cmds))
        _log.info(
            "parallel find: %d subdirs → %d find processes (%d workers)",
            len(subdirs), len(cmds), n_workers,
        )

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            for cmd in cmds:
                pool.submit(_worker, cmd)

            while True:
                try:
                    item = out_queue.get(timeout=0.1)
                except queue.Empty:
                    if cancel_check and cancel_check():
                        with procs_lock:
                            for p in list(active_procs):
                                p.kill()
                        return
                    continue
                if item is _SENTINEL:
                    break
                yield item  # type: ignore[misc]

    def _iter_images_walk(
        self,
        folder: Path,
        cancel_check: Optional[Callable[[], bool]],
    ) -> Iterable[FindEntry]:
        """Pure-Python os.walk() fallback (used on Windows).

        Yields (path, None, None) — mtime/size are fetched later by the indexer
        via path.stat() as before.
        """
        for root, dirs, files in os.walk(folder):
            if cancel_check and cancel_check():
                return
            # Yield to the OS scheduler once per directory.  On macOS,
            # time.sleep(0) (nanosleep 0) may return immediately without a
            # real context switch; a 2 ms sleep forces the scheduler to run
            # other threads (notably the Qt event loop) between directories.
            time.sleep(0.002)
            root_path = Path(root)
            # Prune blacklisted directories in-place so os.walk skips them.
            dirs[:] = [
                d for d in dirs
                if not self._is_blacklisted(root_path / d)
            ]
            for file_name in files:
                if cancel_check and cancel_check():
                    return
                if self.skip_dotfiles and file_name.startswith("."):
                    continue
                path = root_path / file_name
                if self._is_blacklisted(path):
                    continue
                if is_image_file(path):
                    _log.info("found: %s", path)
                    yield path, None, None

    def iter_images(
        self,
        folders: Iterable[Path],
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Iterable[FindEntry]:
        """Yield (path, mtime, size) for every image found under *folders*.

        mtime and size come directly from the find/stat pass so the indexer can
        skip path.stat() for unchanged files.  On Windows (os.walk fallback) both
        are None and the indexer falls back to path.stat() as before.
        """
        for folder in folders:
            if not folder.exists():
                continue
            if _USE_FIND:
                yield from self._iter_images_find(folder, cancel_check)
            else:
                yield from self._iter_images_walk(folder, cancel_check)
