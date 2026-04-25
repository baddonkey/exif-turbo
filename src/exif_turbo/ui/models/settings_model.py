from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from PySide6.QtCore import Property, QObject, Signal, Slot


_CPU_COUNT = os.cpu_count() or 2
_DEFAULT_WORKERS = max(1, _CPU_COUNT // 2)
_MIN_WORKERS = 1
_MAX_WORKERS = _CPU_COUNT

# Patterns that are almost always noise — applied as defaults on first run
_DEFAULT_BLACKLIST: List[str] = [
    ".*",           # hidden files / dotfiles
    "Thumbs.db",    # Windows thumbnail cache
    "desktop.ini",  # Windows folder metadata
    "@eaDir",       # Synology thumbnail dirs
    ".DS_Store",    # macOS metadata
]


class SettingsModel(QObject):
    """Persistent settings stored per-database as JSON.

    Exposes:
    - ``workerCount``  — parallel threads for indexing / thumbnail generation
    - ``blacklist``    — list of glob patterns; matching paths are skipped
    """

    workerCountChanged = Signal()
    blacklistChanged = Signal()

    def __init__(self, settings_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = settings_path
        self._worker_count: int = _DEFAULT_WORKERS
        self._blacklist: List[str] = list(_DEFAULT_BLACKLIST)
        self._load()

    # ── Properties ───────────────────────────────────────────────────────────

    @Property(int, notify=workerCountChanged)
    def workerCount(self) -> int:
        return self._worker_count

    @Property(int, constant=True)
    def minWorkers(self) -> int:
        return _MIN_WORKERS

    @Property(int, constant=True)
    def maxWorkers(self) -> int:
        return _MAX_WORKERS

    @Property("QVariantList", notify=blacklistChanged)
    def blacklist(self) -> List[str]:
        return list(self._blacklist)

    # ── Slots ─────────────────────────────────────────────────────────────────

    @Slot(int)
    def setWorkerCount(self, value: int) -> None:
        clamped = max(_MIN_WORKERS, min(_MAX_WORKERS, value))
        if self._worker_count == clamped:
            return
        self._worker_count = clamped
        self.workerCountChanged.emit()
        self._save()

    @Slot(str)
    def addBlacklistEntry(self, pattern: str) -> None:
        pattern = pattern.strip()
        if not pattern or pattern in self._blacklist:
            return
        self._blacklist.append(pattern)
        self.blacklistChanged.emit()
        self._save()

    @Slot(int)
    def removeBlacklistEntry(self, index: int) -> None:
        if 0 <= index < len(self._blacklist):
            del self._blacklist[index]
            self.blacklistChanged.emit()
            self._save()

    @Slot(result="QVariantList")
    def getBlacklist(self) -> List[str]:
        return list(self._blacklist)

    # ── Python-only API (used by IndexWorker) ────────────────────────────────

    @property
    def blacklist_patterns(self) -> List[str]:
        """Return the raw pattern list for use in the indexing layer."""
        return list(self._blacklist)

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data.get("workerCount"), int):
                self._worker_count = max(_MIN_WORKERS, min(_MAX_WORKERS, data["workerCount"]))
            if isinstance(data.get("blacklist"), list):
                self._blacklist = [str(p) for p in data["blacklist"] if p]
        except Exception:
            pass  # corrupt/missing file — use defaults

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {"workerCount": self._worker_count, "blacklist": self._blacklist},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass  # read-only filesystem — silently ignore

