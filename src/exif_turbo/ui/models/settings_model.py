from __future__ import annotations

import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import Property, QObject, Signal, Slot

from exif_turbo.i18n import _, apply_language, available_languages, current_theme, set_theme
from exif_turbo.models.vocabulary import REQUIRED_VOCABULARY_LOCALES
from exif_turbo.utils.json_export import JsonExportFormat
from exif_turbo.utils.preview_render import (
    DEFAULT_VIPS_ALLOWED_EXTENSIONS,
    configure_vips_allowed_extensions,
    normalize_vips_extension,
)


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

# JSON export formatting defaults — compact (one record per line) keeps the
# historical output unchanged unless the user opts in to pretty-printing.
_DEFAULT_JSON_PRETTY = False
_VALID_INDENT_STYLES = {"space", "tab"}
_DEFAULT_JSON_INDENT_STYLE = "space"
_DEFAULT_JSON_INDENT_SIZE = 2
_JSON_INDENT_SIZE_CHOICES: List[int] = [2, 4, 8]
_MIN_JSON_INDENT_SIZE = 1
_MAX_JSON_INDENT_SIZE = 8

_IS_MACOS_INTEL = sys.platform == "darwin" and platform.machine().lower() in {"x86_64", "amd64"}
_AI_FEATURE_SUPPORTED = not _IS_MACOS_INTEL
_AI_UNAVAILABLE_REASON = _("PyTorch is not available on macOS Intel for Python 3.13+.")

# XLM-R CLIP cosine-similarity policy, calibrated against the multilingual
# model.  Automatic acceptance remains materially stricter than suggestions.
_DEFAULT_PROPOSAL_THRESHOLD = 0.20
_DEFAULT_AUTO_ACCEPT_THRESHOLD = 0.28
_LEGACY_PROPOSAL_THRESHOLD = 0.24
_LEGACY_AUTO_ACCEPT_THRESHOLD = 0.32
_THRESHOLD_CALIBRATION = "openclip-xlm-r-b32-laion5b-v1"
_MIN_THRESHOLD = 0.0
_MAX_PROPOSAL_THRESHOLD = 0.99
_MAX_THRESHOLD = 1.0
_MIN_THRESHOLD_GAP = 0.01
_VALID_TAG_EXPORT_MODES = {"canonical", "interface", "selected"}
_LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
_METADATA_LANGUAGE_CODES = ("en", "de", "fr", "it")
assert frozenset(_METADATA_LANGUAGE_CODES) == REQUIRED_VOCABULARY_LOCALES


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
    libvipsExtensionsChanged = Signal()
    sortByChanged = Signal()
    aiEnabledChanged = Signal()
    taggingSettingsChanged = Signal()
    jsonExportFormatChanged = Signal()

    def __init__(self, settings_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = settings_path
        self._worker_count: int = _DEFAULT_WORKERS
        self._blacklist: List[str] = list(_DEFAULT_BLACKLIST)
        self._theme: str = current_theme()
        self._language: str = "en"
        self._preview_max_size: int = _DEFAULT_PREVIEW_SIZE
        self._libvips_extensions: List[str] = list(DEFAULT_VIPS_ALLOWED_EXTENSIONS)
        self._sort_by: str = _DEFAULT_SORT
        self._ai_enabled: bool = False
        self._tagging_enabled: bool = False
        self._proposal_threshold: float = _DEFAULT_PROPOSAL_THRESHOLD
        self._auto_accept_enabled: bool = False
        self._auto_accept_threshold: float = _DEFAULT_AUTO_ACCEPT_THRESHOLD
        self._show_raw_tag_candidates: bool = False
        self._threshold_calibration: str = _THRESHOLD_CALIBRATION
        self._metadata_language: str = "en"
        self._tag_export_mode: str = "canonical"
        self._tag_export_languages: List[str] = ["en"]
        self._json_pretty: bool = _DEFAULT_JSON_PRETTY
        self._json_indent_style: str = _DEFAULT_JSON_INDENT_STYLE
        self._json_indent_size: int = _DEFAULT_JSON_INDENT_SIZE
        self._load()
        configure_vips_allowed_extensions(self._libvips_extensions)

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

    # ── Tagging ───────────────────────────────────────────────────────────────

    @Property(bool, notify=taggingSettingsChanged)
    def taggingEnabled(self) -> bool:
        return self._tagging_enabled

    @property
    def tagging_enabled(self) -> bool:
        return self._tagging_enabled

    @Slot(bool)
    def setTaggingEnabled(self, value: bool) -> None:
        if self._tagging_enabled == value:
            return
        self._tagging_enabled = value
        self.taggingSettingsChanged.emit()
        self._save()

    @Property(float, notify=taggingSettingsChanged)
    def proposalThreshold(self) -> float:
        return self._proposal_threshold

    @property
    def proposal_threshold(self) -> float:
        return self._proposal_threshold

    @Slot(float)
    def setProposalThreshold(self, value: float) -> None:
        proposal = self._clamp(value, _MIN_THRESHOLD, _MAX_PROPOSAL_THRESHOLD)
        auto_accept = max(
            self._auto_accept_threshold,
            min(_MAX_THRESHOLD, proposal + _MIN_THRESHOLD_GAP),
        )
        if (
            self._proposal_threshold == proposal
            and self._auto_accept_threshold == auto_accept
        ):
            return
        self._proposal_threshold = proposal
        self._auto_accept_threshold = auto_accept
        self.taggingSettingsChanged.emit()
        self._save()

    @Property(bool, notify=taggingSettingsChanged)
    def autoAcceptEnabled(self) -> bool:
        return self._auto_accept_enabled

    @property
    def auto_accept_enabled(self) -> bool:
        return self._auto_accept_enabled

    @Slot(bool)
    def setAutoAcceptEnabled(self, value: bool) -> None:
        if self._auto_accept_enabled == value:
            return
        self._auto_accept_enabled = value
        self.taggingSettingsChanged.emit()
        self._save()

    @Property(float, notify=taggingSettingsChanged)
    def autoAcceptThreshold(self) -> float:
        return self._auto_accept_threshold

    @property
    def auto_accept_threshold(self) -> float:
        return self._auto_accept_threshold

    @Slot(float)
    def setAutoAcceptThreshold(self, value: float) -> None:
        minimum = min(_MAX_THRESHOLD, self._proposal_threshold + _MIN_THRESHOLD_GAP)
        threshold = self._clamp(value, minimum, _MAX_THRESHOLD)
        if self._auto_accept_threshold == threshold:
            return
        self._auto_accept_threshold = threshold
        self.taggingSettingsChanged.emit()
        self._save()

    @Property(bool, notify=taggingSettingsChanged)
    def showRawTagCandidates(self) -> bool:
        return self._show_raw_tag_candidates

    @property
    def show_raw_tag_candidates(self) -> bool:
        return self._show_raw_tag_candidates

    @Slot(bool)
    def setShowRawTagCandidates(self, value: bool) -> None:
        if self._show_raw_tag_candidates == value:
            return
        self._show_raw_tag_candidates = value
        self.taggingSettingsChanged.emit()
        self._save()

    @Property(str, notify=taggingSettingsChanged)
    def metadataLanguage(self) -> str:
        return self._metadata_language

    @Property("QVariantList", constant=True)
    def metadataLanguageCodes(self) -> list[str]:
        return list(_METADATA_LANGUAGE_CODES)

    @property
    def metadata_language(self) -> str:
        return self._metadata_language

    @Slot(str)
    def setMetadataLanguage(self, value: str) -> None:
        if value not in REQUIRED_VOCABULARY_LOCALES or value == self._metadata_language:
            return
        self._metadata_language = value
        self.taggingSettingsChanged.emit()
        self._save()

    @Property(str, notify=taggingSettingsChanged)
    def tagExportMode(self) -> str:
        return self._tag_export_mode

    @property
    def tag_export_mode(self) -> str:
        return self._tag_export_mode

    @Slot(str)
    def setTagExportMode(self, value: str) -> None:
        if value not in _VALID_TAG_EXPORT_MODES or value == self._tag_export_mode:
            return
        self._tag_export_mode = value
        self.taggingSettingsChanged.emit()
        self._save()

    @Property("QVariantList", notify=taggingSettingsChanged)
    def tagExportLanguages(self) -> List[str]:
        return list(self._tag_export_languages)

    @property
    def tag_export_languages(self) -> tuple[str, ...]:
        return tuple(self._tag_export_languages)

    @Slot(str, bool)
    def setTagExportLanguageEnabled(self, locale: str, enabled: bool) -> None:
        if _LOCALE_PATTERN.fullmatch(locale) is None:
            return
        updated = list(self._tag_export_languages)
        if enabled and locale not in updated:
            updated.append(locale)
        elif not enabled and locale in updated:
            updated.remove(locale)
        updated.sort()
        if updated == self._tag_export_languages:
            return
        self._tag_export_languages = updated
        self.taggingSettingsChanged.emit()
        self._save()

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, float(value)))

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

    # ── libvips security ─────────────────────────────────────────────────────

    @Property("QVariantList", notify=libvipsExtensionsChanged)
    def libvipsExtensions(self) -> List[str]:
        return list(self._libvips_extensions)

    @Slot(str)
    def addLibvipsExtension(self, value: str) -> None:
        extension = normalize_vips_extension(value)
        if extension is None or extension in self._libvips_extensions:
            return
        self._libvips_extensions.append(extension)
        self._apply_libvips_extensions()

    @Slot(int)
    def removeLibvipsExtension(self, index: int) -> None:
        if not 0 <= index < len(self._libvips_extensions):
            return
        del self._libvips_extensions[index]
        self._apply_libvips_extensions()

    def _apply_libvips_extensions(self) -> None:
        configure_vips_allowed_extensions(self._libvips_extensions)
        self.libvipsExtensionsChanged.emit()
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

    # ── JSON export formatting ────────────────────────────────────────────────

    @Property(bool, notify=jsonExportFormatChanged)
    def jsonExportPretty(self) -> bool:
        return self._json_pretty

    @Slot(bool)
    def setJsonExportPretty(self, value: bool) -> None:
        if self._json_pretty == value:
            return
        self._json_pretty = value
        self.jsonExportFormatChanged.emit()
        self._save()

    @Property(str, notify=jsonExportFormatChanged)
    def jsonExportIndentStyle(self) -> str:
        return self._json_indent_style

    @Slot(str)
    def setJsonExportIndentStyle(self, value: str) -> None:
        if value not in _VALID_INDENT_STYLES or self._json_indent_style == value:
            return
        self._json_indent_style = value
        self.jsonExportFormatChanged.emit()
        self._save()

    @Property(int, notify=jsonExportFormatChanged)
    def jsonExportIndentSize(self) -> int:
        return self._json_indent_size

    @Property("QVariantList", constant=True)
    def jsonExportIndentSizeChoices(self) -> List[int]:
        return list(_JSON_INDENT_SIZE_CHOICES)

    @Slot(int)
    def setJsonExportIndentSize(self, value: int) -> None:
        clamped = max(_MIN_JSON_INDENT_SIZE, min(_MAX_JSON_INDENT_SIZE, value))
        if self._json_indent_size == clamped:
            return
        self._json_indent_size = clamped
        self.jsonExportFormatChanged.emit()
        self._save()

    @property
    def json_export_format(self) -> JsonExportFormat:
        """Python-only accessor for AppController — the current export format."""
        return JsonExportFormat(
            pretty=self._json_pretty,
            indent_style=self._json_indent_style,
            indent_size=self._json_indent_size,
        )

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
            migrate_thresholds = data.get("proposalThresholdCalibration") != _THRESHOLD_CALIBRATION
            if isinstance(data.get("workerCount"), int):
                self._worker_count = max(_MIN_WORKERS, min(_MAX_WORKERS, data["workerCount"]))
            if isinstance(data.get("blacklist"), list):
                self._blacklist = [str(p) for p in data["blacklist"] if p]
            if isinstance(data.get("previewMaxSize"), int) and data["previewMaxSize"] in _PREVIEW_SIZE_CHOICES:
                self._preview_max_size = data["previewMaxSize"]
            if isinstance(data.get("libvipsExtensions"), list):
                loaded_extensions: List[str] = []
                for value in data["libvipsExtensions"]:
                    extension = normalize_vips_extension(str(value))
                    if extension is not None and extension not in loaded_extensions:
                        loaded_extensions.append(extension)
                self._libvips_extensions = loaded_extensions
            if isinstance(data.get("sortBy"), str) and data["sortBy"] in _VALID_SORTS:
                self._sort_by = data["sortBy"]
            if isinstance(data.get("language"), str) and data["language"] in {c for c, _ in available_languages()}:
                self._language = data["language"]
                apply_language(self._language)
            if isinstance(data.get("aiEnabled"), bool):
                self._ai_enabled = data["aiEnabled"] and _AI_FEATURE_SUPPORTED
            if isinstance(data.get("taggingEnabled"), bool):
                self._tagging_enabled = data["taggingEnabled"]
            if isinstance(data.get("proposalThreshold"), (int, float)):
                self._proposal_threshold = self._clamp(
                    data["proposalThreshold"],
                    _MIN_THRESHOLD,
                    _MAX_PROPOSAL_THRESHOLD,
                )
            if isinstance(data.get("autoAcceptEnabled"), bool):
                self._auto_accept_enabled = data["autoAcceptEnabled"]
            if isinstance(data.get("autoAcceptThreshold"), (int, float)):
                self._auto_accept_threshold = self._clamp(
                    data["autoAcceptThreshold"],
                    _MIN_THRESHOLD,
                    _MAX_THRESHOLD,
                )
            if isinstance(data.get("showRawTagCandidates"), bool):
                self._show_raw_tag_candidates = data["showRawTagCandidates"]
            if (
                migrate_thresholds
                and self._proposal_threshold == _LEGACY_PROPOSAL_THRESHOLD
                and self._auto_accept_threshold == _LEGACY_AUTO_ACCEPT_THRESHOLD
            ):
                self._proposal_threshold = _DEFAULT_PROPOSAL_THRESHOLD
                self._auto_accept_threshold = _DEFAULT_AUTO_ACCEPT_THRESHOLD
            if (
                isinstance(data.get("metadataLanguage"), str)
                and data["metadataLanguage"] in REQUIRED_VOCABULARY_LOCALES
            ):
                self._metadata_language = data["metadataLanguage"]
            if data.get("tagExportMode") in _VALID_TAG_EXPORT_MODES:
                self._tag_export_mode = str(data["tagExportMode"])
            if isinstance(data.get("tagExportLanguages"), list):
                self._tag_export_languages = sorted(
                    {
                        str(locale)
                        for locale in data["tagExportLanguages"]
                        if _LOCALE_PATTERN.fullmatch(str(locale)) is not None
                    }
                )
            self._auto_accept_threshold = max(
                self._auto_accept_threshold,
                min(
                    _MAX_THRESHOLD,
                    self._proposal_threshold + _MIN_THRESHOLD_GAP,
                ),
            )
            if isinstance(data.get("jsonExportPretty"), bool):
                self._json_pretty = data["jsonExportPretty"]
            if data.get("jsonExportIndentStyle") in _VALID_INDENT_STYLES:
                self._json_indent_style = data["jsonExportIndentStyle"]
            if isinstance(data.get("jsonExportIndentSize"), int):
                self._json_indent_size = max(
                    _MIN_JSON_INDENT_SIZE,
                    min(_MAX_JSON_INDENT_SIZE, data["jsonExportIndentSize"]),
                )
            if migrate_thresholds:
                self._save()
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
                        "libvipsExtensions": self._libvips_extensions,
                        "sortBy": self._sort_by,
                        "language": self._language,
                        "aiEnabled": self._ai_enabled,
                        "taggingEnabled": self._tagging_enabled,
                        "proposalThreshold": self._proposal_threshold,
                        "proposalThresholdCalibration": self._threshold_calibration,
                        "autoAcceptEnabled": self._auto_accept_enabled,
                        "autoAcceptThreshold": self._auto_accept_threshold,
                        "showRawTagCandidates": self._show_raw_tag_candidates,
                        "metadataLanguage": self._metadata_language,
                        "tagExportMode": self._tag_export_mode,
                        "tagExportLanguages": self._tag_export_languages,
                        "jsonExportPretty": self._json_pretty,
                        "jsonExportIndentStyle": self._json_indent_style,
                        "jsonExportIndentSize": self._json_indent_size,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass  # read-only filesystem — silently ignore

