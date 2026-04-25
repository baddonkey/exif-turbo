from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QIcon, QImageReader
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ..config import db_path_for_name, default_db_path, settings_path, thumb_cache_dir
from .gettext_translator import GettextTranslator
from .models.exif_list_model import ExifListModel
from .models.folder_list_model import FolderListModel
from .models.search_list_model import SearchListModel
from .models.settings_model import SettingsModel
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
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Exif-Turbo")
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "app_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Install gettext-backed translator so QML qsTr() resolves via gettext.
    translator = GettextTranslator(app)
    app.installTranslator(translator)

    db_path = db_path_for_name(args.db) if args.db else default_db_path()
    settings = SettingsModel(settings_path(db_path))
    search_model = SearchListModel(cache_dir=thumb_cache_dir(db_path))
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    controller = AppController(db_path, search_model, exif_model, folder_model, settings)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel", settings)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        sys.exit(1)

    # Re-evaluate all qsTr() bindings in live QML objects when language changes.
    settings.retranslateRequested.connect(engine.retranslate)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
