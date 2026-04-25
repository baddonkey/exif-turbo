"""QTranslator bridge — delegates QML qsTr() calls to gettext."""

from __future__ import annotations

from PySide6.QtCore import QTranslator

from exif_turbo.i18n import _


class GettextTranslator(QTranslator):
    """Custom QTranslator that forwards translation lookups to gettext.

    QML's ``qsTr()`` calls go through Qt's translator stack.  This subclass
    intercepts those lookups and resolves them via the project's gettext
    singleton so that QML and Python share one translation catalog.
    """

    def translate(  # type: ignore[override]
        self,
        context: str | None,
        source_text: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        return _(source_text)


__all__ = ["GettextTranslator"]
