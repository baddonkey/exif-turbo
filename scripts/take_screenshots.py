#!/usr/bin/env python3
"""Generate user-manual screenshots for exif-turbo.

Usage (from the project root, with the venv active):
    python scripts/take_screenshots.py

Requirements:
    - ExifTool must be on PATH (used by IndexerService)
    - Sample images in tests/sample-data/schweiz/

The script:
1. Builds a demo SQLite index from the sample images
2. Launches the QML application pointing at that index (empty password)
3. Drives the UI through several states with QTimer callbacks
4. Saves screenshots to docs/screenshots/

Output files:
    01_lock_screen.png       — startup password prompt
    02_search_all.png        — search tab with all images loaded
    03_search_eagle.png      — search results for "eagle"
    04_search_milky_way.png  — search results for "milky way"
    05_browse_tab.png        — browse tab (folder tree navigation)
    06_indexed_folders.png   — indexed folders management tab
"""

from __future__ import annotations

import ctypes
import os
import sys
import logging
from pathlib import Path
from typing import Any

# ── Resolve project root and make the src package importable ──────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

SAMPLE_DATA = _REPO_ROOT / "tests" / "sample-data" / "schweiz"
SCREENSHOTS_DIR = _REPO_ROOT / "docs" / "screenshots"
DB_PATH = SCREENSHOTS_DIR / "demo.db"
THUMB_CACHE = SCREENSHOTS_DIR / "thumbs"

# ── Qt must be imported after sys.path is updated ─────────────────────────────
from PySide6.QtCore import QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QIcon, QImageReader  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

from exif_turbo.data.image_index_repository import ImageIndexRepository  # noqa: E402
from exif_turbo.indexing.indexer_service import IndexerService  # noqa: E402
from exif_turbo.ui.models.exif_list_model import ExifListModel  # noqa: E402
from exif_turbo.ui.models.folder_list_model import FolderListModel  # noqa: E402
from exif_turbo.ui.models.search_list_model import SearchListModel  # noqa: E402
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider  # noqa: E402
from exif_turbo.ui.view_models.app_controller import AppController  # noqa: E402


# ── Database builder ──────────────────────────────────────────────────────────

def build_demo_db() -> None:
    """Index the sample images into the demo database (empty password)."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)

    print(f"Indexing sample images from {SAMPLE_DATA} …")
    repo = ImageIndexRepository(DB_PATH, key="")
    service = IndexerService(repo)
    total = service.build_index(
        folders=[SAMPLE_DATA],
        on_progress=lambda cur, tot, p: print(f"  {cur}/{tot}  {p.name}"),
        workers=4,
    )
    repo.commit()
    repo.close()
    print(f"Indexed {total} image(s) into {DB_PATH}")


# ── Screenshot helpers ────────────────────────────────────────────────────────

def _grab(window: Any, name: str) -> None:
    """Capture the window to docs/screenshots/<name>.png."""
    screen = window.screen() if hasattr(window, "screen") else None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    pixmap = screen.grabWindow(int(window.winId()))
    out = SCREENSHOTS_DIR / f"{name}.png"
    if pixmap.save(str(out)):
        print(f"  Saved: {out.relative_to(_REPO_ROOT)}")
    else:
        print(f"  WARNING: failed to save {out}")


# ── UI driver ────────────────────────────────────────────────────────────────

class ScreenshotDriver:
    """Drives the running QML window through screenshot states.

    Each step either:
    - fires immediately (actions), or
    - waits for a *readiness condition* to be true before grabbing (screenshots).

    Readiness conditions are polled every 300 ms with a 30-second safety timeout
    so the script never hangs if thumbnails or previews take unusually long.
    """

    _POLL_MS = 300
    _TIMEOUT_MS = 30_000

    def __init__(self, controller: AppController, engine: QQmlApplicationEngine) -> None:
        self._ctrl = controller
        self._engine = engine
        self._window: Any = None
        # Keep timer references alive; GC would stop them otherwise.
        self._poll_timer: QTimer | None = None

    def start(self) -> None:
        roots = self._engine.rootObjects()
        if roots:
            self._window = roots[0]
        # Begin the sequence after a short settle delay.
        QTimer.singleShot(600, self._step_lock_screen)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _wait_for(self, condition_fn: Any, callback: Any) -> None:
        """Poll condition_fn every _POLL_MS ms, then call callback when ready."""
        elapsed = [0]
        timer = QTimer()
        timer.setInterval(self._POLL_MS)
        self._poll_timer = timer

        def _check() -> None:
            elapsed[0] += self._POLL_MS
            if condition_fn():
                print(f"    ready after {elapsed[0]} ms")
                timer.stop()
                # Extra 400 ms so Qt finishes painting after condition is met
                QTimer.singleShot(400, callback)
            elif elapsed[0] >= self._TIMEOUT_MS:
                print(f"    WARNING: timeout waiting for condition, grabbing anyway")
                timer.stop()
                QTimer.singleShot(0, callback)

        timer.timeout.connect(_check)
        timer.start()

    def _ready_search(self) -> bool:
        """True when results are loaded, first image is selected, and thumbs are done."""
        return (
            self._ctrl.totalResults >= 0
            and bool(self._ctrl.selectedImageSource)
            and not self._ctrl.isBuildingThumbs
        )

    def _ready_any_preview(self) -> bool:
        """True when a preview image is showing and thumb worker has gone idle."""
        return bool(self._ctrl.selectedImageSource) and not self._ctrl.isBuildingThumbs

    # ── Step sequence ─────────────────────────────────────────────────────

    def _step_lock_screen(self) -> None:
        _grab(self._window, "01_lock_screen")
        self._ctrl.unlock("")
        print("  Unlocked — waiting for all results + thumbnails …")
        self._wait_for(self._ready_search, self._step_shot_search_all)

    def _step_shot_search_all(self) -> None:
        _grab(self._window, "02_search_all")
        self._ctrl.search("eagle")
        print("  Searching 'eagle' — waiting for results + thumbnails …")
        self._wait_for(self._ready_any_preview, self._step_shot_eagle)

    def _step_shot_eagle(self) -> None:
        _grab(self._window, "03_search_eagle")
        self._ctrl.search("milky way")
        print("  Searching 'milky way' — waiting for results + thumbnails …")
        self._wait_for(self._ready_any_preview, self._step_shot_milky_way)

    def _step_shot_milky_way(self) -> None:
        _grab(self._window, "04_search_milky_way")
        # Return to all results, then switch to Browse tab (index 1)
        self._ctrl.search("")
        print("  Loading Browse tab — waiting for preview …")
        # Browse tab switch: give QML 1 s to render the folder tree, then grab
        QTimer.singleShot(1200, self._step_shot_browse)

    def _step_shot_browse(self) -> None:
        _grab(self._window, "05_browse_tab")
        print("  Loading Indexed Folders tab …")
        QTimer.singleShot(800, self._step_shot_folders)

    def _step_shot_folders(self) -> None:
        _grab(self._window, "06_indexed_folders")
        QTimer.singleShot(300, QGuiApplication.quit)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    build_demo_db()

    print("\nLaunching UI for screenshot capture …")

    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "exif-turbo.screenshots"
            )
        except Exception:
            pass

    try:
        QImageReader.setAllocationLimit(1024)
    except Exception:
        pass

    QQuickStyle.setStyle("Material")

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Exif-Turbo")

    icon_path = _SRC / "exif_turbo" / "assets" / "app_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    search_model = SearchListModel(cache_dir=THUMB_CACHE)
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    controller = AppController(DB_PATH, search_model, exif_model, folder_model)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)

    qml_path = _SRC / "exif_turbo" / "ui" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        print("ERROR: QML failed to load.")
        sys.exit(1)

    # Show the window maximised so screenshots look realistic
    root = engine.rootObjects()[0]
    root.showMaximized()

    driver = ScreenshotDriver(controller, engine)
    driver.start()

    code = app.exec()
    print(f"\nDone. Screenshots saved to {SCREENSHOTS_DIR.relative_to(_REPO_ROOT)}/")
    sys.exit(code)


if __name__ == "__main__":
    main()
