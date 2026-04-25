"""Internationalization — gettext-based translation support.

The module-level ``_()`` function and language helpers are lazy: the
underlying :class:`Translator` is constructed on first use, never at
import time.  This keeps ``import exif_turbo.i18n`` side-effect-free for
tests and lets embedders inject a custom translator before the first
lookup runs.
"""

from __future__ import annotations

from typing import Sequence

from exif_turbo.i18n.translator import Translator

_translator: Translator | None = None


def _get() -> Translator:
    """Return the process-wide :class:`Translator`, creating it lazily."""
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def set_translator(translator: Translator | None) -> None:
    """Replace (or clear) the process-wide translator.

    Tests use this to install a translator with no settings backend.
    Pass ``None`` to discard the current instance so the next call to
    :func:`_get` re-creates a fresh default.
    """
    global _translator
    _translator = translator


# Public functions defer to the lazy singleton.
def _(message: str) -> str:
    return _get().gettext(message)


def set_language(lang: str) -> None:
    _get().set_language(lang)


def apply_language(lang: str) -> None:
    _get().apply_language(lang)


def current_language() -> str:
    return _get().current_language()


def current_theme() -> str:
    return _get().current_theme()


def set_theme(theme: str) -> None:
    _get().set_theme(theme)


def available_languages() -> Sequence[tuple[str, str]]:
    return Translator.available_languages()


__all__ = [
    "Translator",
    "_",
    "apply_language",
    "available_languages",
    "current_language",
    "current_theme",
    "set_language",
    "set_theme",
    "set_translator",
]
