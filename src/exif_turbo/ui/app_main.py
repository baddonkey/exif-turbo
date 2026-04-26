from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from pathlib import Path

from PIL import Image as _PILImage

# Raise the decompression bomb limit 10× above Pillow's default (89 MP → 894 MP).
# Large panoramas and high-resolution TIFFs legitimately exceed the default.
_PILImage.MAX_IMAGE_PIXELS = 894_784_850

from PySide6.QtCore import QUrl, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QIcon, QImageReader
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWebEngineQuick import QtWebEngineQuick

from ..config import db_path_for_name, default_db_path, settings_path, thumb_cache_dir
from .gettext_translator import GettextTranslator
from .models.exif_list_model import ExifListModel
from .models.folder_list_model import FolderListModel
from .models.search_list_model import SearchListModel
from .models.settings_model import SettingsModel
from .providers.preview_image_provider import PreviewImageProvider
from .providers.raw_image_provider import RawImageProvider
from .view_models.app_controller import AppController


_qt_log = logging.getLogger("qt")

_QT_MSG_LEVEL = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def _qt_message_handler(msg_type: QtMsgType, _context: object, message: str) -> None:
    _qt_log.log(_QT_MSG_LEVEL.get(msg_type, logging.WARNING), message)


def _ensure_pyside6_dll_search_path() -> None:
    # On Windows, Qt plugins (e.g. imageformats/qsvg.dll, iconengines/qsvgicon.dll) are loaded
    # from subfolders, but depend on Qt6*.dll living in the PySide6 package directory. If that
    # directory isn't in the DLL search path, SVG support appears "installed" but silently fails.
    if os.name != "nt":
        return
    try:
        import PySide6

        pyside_dir = Path(PySide6.__file__).resolve().parent
        os.add_dll_directory(str(pyside_dir))
    except Exception:
        # Best-effort; if this fails, icon loading may still fall back to default behavior.
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exif Turbo UI")
    parser.add_argument(
        "--db",
        default=None,
        metavar="NAME",
        help=(
            "Database name, e.g. 'work' or 'holidays'. "
            "The database is always stored in ~/.exif-turbo/data/<NAME>.db. "
            f"Default: index (i.e. {default_db_path()})"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.WARNING)
    qInstallMessageHandler(_qt_message_handler)
    _ensure_pyside6_dll_search_path()
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("exif-turbo")
        except Exception:
            pass
    try:
        QImageReader.setAllocationLimit(1024)
    except Exception:
        pass

    QQuickStyle.setStyle("Material")
    QtWebEngineQuick.initialize()  # must be called before QGuiApplication
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Exif-Turbo")
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Install gettext-backed translator so QML qsTr() resolves via gettext.
    translator = GettextTranslator(app)
    app.installTranslator(translator)

    db_path = db_path_for_name(args.db) if args.db else default_db_path()
    settings = SettingsModel(settings_path(db_path))
    _cache_dir = thumb_cache_dir(db_path)
    search_model = SearchListModel(cache_dir=_cache_dir)
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    controller = AppController(db_path, search_model, exif_model, folder_model, settings, cache_dir=_cache_dir)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel", settings)

    # Third-party licenses — bundled beside assets in frozen builds,
    # or read from the project root in dev mode.
    # Converted to HTML so Qt renders it with proper link colours instead of
    # baking the system-palette navy into QTextCharFormat at markdown-parse time.
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    _licenses_candidates = [
        assets_dir / "THIRD-PARTY-LICENSES.md",
        Path(__file__).resolve().parents[3] / "THIRD-PARTY-LICENSES.md",
    ]
    _licenses_text = ""
    for _p in _licenses_candidates:
        if _p.exists():
            _licenses_text = _p.read_text(encoding="utf-8")
            break

    _licenses_html = ""  # will be set below
    try:
        import re as _re

        import markdown as _md_lib

        _body = _md_lib.markdown(_licenses_text, extensions=["tables"])
        # Auto-link bare URLs that ended up as plain text inside <td> cells.
        _body = _re.sub(
            r'(?<=>)(https?://[^\s<"]+)(?=\s*</td>)',
            r'<a href="\1">\1</a>',
            _body,
        )
        _licenses_html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>"
            "body{font-family:sans-serif;font-size:13px;color:TEXTCOLOR;background:BGCOLOR;margin:12px 16px;}"
            "h1,h2,h3{color:TEXTCOLOR;}"
            "a{color:LINKCOLOR;}"
            "table{border-collapse:collapse;width:100%;}"
            "th,td{border:1px solid BORDERCOLOR;padding:4px 8px;text-align:left;}"
            "th{background:HEADERBG;}"
            "code{background:CODEBG;padding:1px 4px;border-radius:3px;font-size:12px;}"
            "</style></head><body>"
            + _body
            + "</body></html>"
        )
    except Exception:
        _licenses_html = "<pre>" + _licenses_text + "</pre>"

    ctx.setContextProperty("thirdPartyLicensesHtml", _licenses_html)

    # User manual PDF — bundled beside assets in frozen builds,
    # or looked up in docs/ in dev mode.
    _manual_candidates = [
        assets_dir / "user-manual.pdf",
        Path(__file__).resolve().parents[3] / "docs" / "user-manual.pdf",
    ]
    _manual_url = ""
    for _p in _manual_candidates:
        if _p.exists():
            _manual_url = QUrl.fromLocalFile(str(_p)).toString()
            break
    ctx.setContextProperty("userManualUrl", _manual_url)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        sys.exit(1)

    # Re-evaluate all qsTr() bindings in live QML objects when language changes.
    settings.retranslateRequested.connect(engine.retranslate)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
