from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import Property, QObject, Signal, Slot

from exif_turbo.i18n import apply_language, available_languages, current_theme, set_theme


_CPU_COUNT = os.cpu_count() or 2
_DEFAULT_WORKERS = max(1, _CPU_COUNT // 2)
_MIN_WORKERS = 1
_MAX_WORKERS = min(_CPU_COUNT, 16)

# Patterns that are almost always noise — applied as defaults on first run
_DEFAULT_BLACKLIST: List[str] = [
    ".*",           # hidden files / dotfiles
    "Thumbs.db",    # Windows thumbnail cache
    "desktop.ini",  # Windows folder metadata
    "@eaDir",       # Synology thumbnail dirs
    ".DS_Store",    # macOS metadata
]

# Allowed long-edge sizes for the on-disk preview cache.  Anything larger than
# 4K is rarely useful as a preview — if the user wants 1:1 they can flip the
# in-preview toggle to fall back to the full-resolution raw provider.
_PREVIEW_SIZE_CHOICES: List[int] = [1280, 1600, 2048, 2560, 3840]
_DEFAULT_PREVIEW_SIZE = 2048

_DEFAULT_SORT = "captured_desc"
_VALID_SORTS = {
    "filename_asc", "filename_desc",
    "path_asc",     "path_desc",
    "size_desc",    "size_asc",
    "captured_desc", "captured_asc",
}

_IS_MACOS_INTEL = sys.platform == "darwin" and platform.machine().lower() in {"x86_64", "amd64"}
_AI_FEATURE_SUPPORTED = not _IS_MACOS_INTEL
_AI_UNAVAILABLE_REASON = "PyTorch is not available on macOS Intel for Python 3.13+."


class SettingsModel(QObject):
    """Persistent settings stored per-database as JSON.

    Exposes:
    - ``workerCount``  — parallel threads for indexing / thumbnail generation
    - ``blacklist``    — list of glob patterns; matching paths are skipped
    - ``language``     — UI language code (persisted globally, not per-DB)
    """

    workerCountChanged = Signal()
    blacklistChanged = Signal()
    themeChanged = Signal()
    languageChanged = Signal()
    retranslateRequested = Signal()
    previewMaxSizeChanged = Signal()
    sortByChanged = Signal()
    aiEnabledChanged = Signal()

    def __init__(self, settings_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = settings_path
        self._worker_count: int = _DEFAULT_WORKERS
        self._blacklist: List[str] = list(_DEFAULT_BLACKLIST)
        self._theme: str = current_theme()
        self._language: str = "en"
        self._preview_max_size: int = _DEFAULT_PREVIEW_SIZE
        self._sort_by: str = _DEFAULT_SORT
        self._ai_enabled: bool = False
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

    @Property(int, constant=True)
    def defaultWorkers(self) -> int:
        return _DEFAULT_WORKERS

    @Property(int, constant=True)
    def cpuCount(self) -> int:
        return _CPU_COUNT

    @Property(bool, constant=True)
    def workersLocked(self) -> bool:
        return False

    # ── AI features ───────────────────────────────────────────────────────────

    @Property(bool, notify=aiEnabledChanged)
    def aiEnabled(self) -> bool:
        return self._ai_enabled

    @Property(bool, constant=True)
    def aiFeatureAvailable(self) -> bool:
        return _AI_FEATURE_SUPPORTED

    @Property(str, constant=True)
    def aiFeatureUnavailableReason(self) -> str:
        return _AI_UNAVAILABLE_REASON if not _AI_FEATURE_SUPPORTED else ""

    @property
    def ai_enabled(self) -> bool:
        """Python-only accessor for AppController."""
        return self._ai_enabled

    @Slot(bool)
    def setAiEnabled(self, value: bool) -> None:
        if value and not _AI_FEATURE_SUPPORTED:
            return
        if self._ai_enabled == value:
            return
        self._ai_enabled = value
        self.aiEnabledChanged.emit()
        self._save()

    @Property("QVariantList", notify=blacklistChanged)
    def blacklist(self) -> List[str]:
        return list(self._blacklist)

    # ── Preview cache ──────────────────────────────────────────────────────────

    @Property(int, notify=previewMaxSizeChanged)
    def previewMaxSize(self) -> int:
        return self._preview_max_size

    @Property("QVariantList", constant=True)
    def previewSizeChoices(self) -> List[int]:
        return list(_PREVIEW_SIZE_CHOICES)

    @Slot(int)
    def setPreviewMaxSize(self, value: int) -> None:
        if value not in _PREVIEW_SIZE_CHOICES:
            return
        if self._preview_max_size == value:
            return
        self._preview_max_size = value
        self.previewMaxSizeChanged.emit()
        self._save()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _get_theme(self) -> str:
        return self._theme

    def _set_theme(self, value: str) -> None:
        if self._theme != value:
            self._theme = value
            set_theme(value)
            self.themeChanged.emit()

    theme = Property(str, _get_theme, _set_theme, notify=themeChanged)

    # ── Language ──────────────────────────────────────────────────────────────

    def _get_language(self) -> str:
        return self._language

    def _set_language(self, value: str) -> None:
        if self._language != value:
            self._language = value
            apply_language(value)
            self.languageChanged.emit()
            self.retranslateRequested.emit()
            self._save()

    language = Property(str, _get_language, _set_language, notify=languageChanged)

    def _get_language_names(self) -> List[str]:
        return [name for _, name in available_languages()]

    def _get_language_codes(self) -> List[str]:
        return [code for code, _ in available_languages()]

    languageNames = Property("QVariantList", _get_language_names, constant=True)  # noqa: N815
    languageCodes = Property("QVariantList", _get_language_codes, constant=True)  # noqa: N815

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

    # ── Sort order ────────────────────────────────────────────────────────────

    @Property(str, notify=sortByChanged)
    def sortBy(self) -> str:
        return self._sort_by

    @property
    def sort_by(self) -> str:
        """Python-only accessor for AppController."""
        return self._sort_by

    @Slot(str)
    def setSortBy(self, value: str) -> None:
        if value not in _VALID_SORTS or self._sort_by == value:
            return
        self._sort_by = value
        self.sortByChanged.emit()
        self._save()

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
            if isinstance(data.get("previewMaxSize"), int) and data["previewMaxSize"] in _PREVIEW_SIZE_CHOICES:
                self._preview_max_size = data["previewMaxSize"]
            if isinstance(data.get("sortBy"), str) and data["sortBy"] in _VALID_SORTS:
                self._sort_by = data["sortBy"]
            if isinstance(data.get("language"), str) and data["language"] in {c for c, _ in available_languages()}:
                self._language = data["language"]
                apply_language(self._language)
            if isinstance(data.get("aiEnabled"), bool):
                self._ai_enabled = data["aiEnabled"] and _AI_FEATURE_SUPPORTED
        except Exception:
            pass  # corrupt/missing file — use defaults

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {
                        "workerCount": self._worker_count,
                        "blacklist": self._blacklist,
                        "previewMaxSize": self._preview_max_size,
                        "sortBy": self._sort_by,
                        "language": self._language,
                        "aiEnabled": self._ai_enabled,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass  # read-only filesystem — silently ignore

