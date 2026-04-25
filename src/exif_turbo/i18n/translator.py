"""Translator — gettext wrapper with runtime language switching."""

from __future__ import annotations

import gettext
import json
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

_log = logging.getLogger(__name__)

_DOMAIN = "exif_turbo"
_LOCALES_DIR = Path(__file__).parent / "locales"

# Language code -> display name (shown in the Settings combo box).
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "it": "Italiano",
    "rm": "Rumantsch",
}


def _global_settings_path() -> Path:
    """Return the global settings file path (language is user-global, not per-DB)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "exif-turbo" / "settings.json"


class _JsonSettings:
    """Minimal JSON key-value store for the global settings file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, object] = self._load()

    def value(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def set_value(self, key: str, value: object) -> None:
        self._data[key] = value
        self._save()

    def _load(self) -> dict[str, object]:
        try:
            if self._path.exists():
                return dict(json.loads(self._path.read_text(encoding="utf-8")))
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception:
            pass


class Translator:
    """Loads gettext translations and exposes a switchable ``gettext`` callable.

    The language choice is persisted to a global settings file
    (``~/.exif-turbo/settings.json`` on Linux, platform equivalent elsewhere)
    so it survives across database switches.

    Pass ``settings=None`` to skip persistence entirely — useful in
    unit tests where you only want in-memory language switching.
    """

    def __init__(self, settings: _JsonSettings | None | object = ...) -> None:
        # Sentinel ``...`` means "use the default global settings file".
        # Explicit ``None`` means "no persistence at all".
        if settings is ...:
            self._settings: _JsonSettings | None = _JsonSettings(_global_settings_path())
        else:
            self._settings = settings  # type: ignore[assignment]
        self._lang: str = "en"
        self._gt: gettext.GNUTranslations | gettext.NullTranslations = gettext.NullTranslations()
        self._load_saved_language()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def gettext(self, message: str) -> str:
        """Translate *message* using the active language."""
        return self._gt.gettext(message)

    def set_language(self, lang: str) -> None:
        """Switch the active language and persist the choice."""
        self._apply_language(lang)
        if self._settings is not None:
            self._settings.set_value("language", lang)

    def apply_language(self, lang: str) -> None:
        """Switch the active language **without** persisting."""
        self._apply_language(lang)

    def current_language(self) -> str:
        """Return the active language code (e.g. ``'de'``)."""
        return self._lang

    @staticmethod
    def available_languages() -> Sequence[tuple[str, str]]:
        """Return ``(code, display_name)`` pairs for all supported languages."""
        return list(LANGUAGE_NAMES.items())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_language(self, lang: str) -> None:
        self._lang = lang
        self._gt = self._load(lang)

    def _load_saved_language(self) -> None:
        if self._settings is None:
            self._apply_language("en")
            return
        lang = str(self._settings.value("language", "en"))
        self._apply_language(lang)

    @staticmethod
    def _load(lang: str) -> gettext.GNUTranslations | gettext.NullTranslations:
        """Load the ``.mo`` file for *lang*, falling back to NullTranslations."""
        try:
            return gettext.translation(
                _DOMAIN,
                localedir=str(_LOCALES_DIR),
                languages=[lang],
            )
        except FileNotFoundError:
            return gettext.NullTranslations()


__all__ = ["Translator", "LANGUAGE_NAMES"]
