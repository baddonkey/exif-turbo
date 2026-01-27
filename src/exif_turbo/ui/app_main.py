from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path

from PySide6.QtGui import QIcon, QImageReader
from PySide6.QtWidgets import QApplication

from ..data.image_index_repository import ImageIndexRepository
from .main_window import MainWindow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exif Turbo UI")
    parser.add_argument("--db", required=True, help="SQLite database path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("exif-turbo")
        except Exception:
            pass
    try:
        QImageReader.setAllocationLimit(1024)
    except Exception:
        pass
    app = QApplication([])
    app.setApplicationName("Exif-Turbo")
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "app_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    repo = ImageIndexRepository(Path(args.db))
    window = MainWindow(repo)
    window.showMaximized()
    app.exec()


if __name__ == "__main__":
    main()
