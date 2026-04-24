from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QImageReader
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ..data.image_index_repository import ImageIndexRepository
from .models.exif_list_model import ExifListModel
from .models.search_list_model import SearchListModel
from .view_models.app_controller import AppController


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
    parser.add_argument("--db", required=True, help="SQLite database path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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

    repo = ImageIndexRepository(Path(args.db))
    search_model = SearchListModel()
    exif_model = ExifListModel()
    controller = AppController(repo, search_model, exif_model)

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
