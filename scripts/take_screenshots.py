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
    01_lock_screen.png       -- startup password prompt
    02_search_all.png        -- search tab with all images loaded
    03_search_eagle.png      -- search results for "eagle"
    04_search_milky_way.png  -- search results for "milky way"
    05_browse_tab.png        -- browse tab (folder tree navigation)
    06_indexed_folders.png   -- indexed folders management tab
"""

from __future__ import annotations

import ctypes
import os
import sys
import logging
from pathlib import Path
from typing import Any

# -- Resolve project root and make the src package importable ------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

SAMPLE_DATA = _REPO_ROOT / "tests" / "sample-data" / "schweiz"
SCREENSHOTS_DIR = _REPO_ROOT / "docs" / "screenshots"
DB_PATH = SCREENSHOTS_DIR / "demo.db"
THUMB_CACHE = SCREENSHOTS_DIR / "thumbs"

# -- Qt must be imported after sys.path is updated ----------------------------
from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication, QIcon, QImageReader  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

from exif_turbo.data.image_index_repository import ImageIndexRepository  # noqa: E402
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository  # noqa: E402
from exif_turbo.indexing.indexer_service import IndexerService  # noqa: E402
from exif_turbo.ui.models.exif_list_model import ExifListModel  # noqa: E402
from exif_turbo.ui.models.folder_list_model import FolderListModel  # noqa: E402
from exif_turbo.ui.models.search_list_model import SearchListModel  # noqa: E402
from exif_turbo.ui.models.settings_model import SettingsModel  # noqa: E402
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider  # noqa: E402
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider  # noqa: E402
from exif_turbo.ui.view_models.app_controller import AppController  # noqa: E402

_STEPS = [
    "01_lock_screen",
    "02_search_all",
    "03_search_eagle",
    "04_search_milky_way",
    "05_browse_tab",
    "06_indexed_folders",
]


# -- Database builder ----------------------------------------------------------

def build_demo_db() -> None:
    """Index the sample images into the demo database (empty password)."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)

    print(f"Indexing sample images from {SAMPLE_DATA} ...")
    repo = ImageIndexRepository(DB_PATH, key="")
    service = IndexerService(repo)
    indexed_count, _errors = service.build_index(
        folders=[SAMPLE_DATA],
        on_progress=lambda cur, tot, p: print(f"  {cur}/{tot}  {p.name}"),
        workers=4,
    )
    repo.commit()
    repo.close()

    # Register the folder so it appears in the Indexed Folders tab
    folder_repo = IndexedFolderRepository(DB_PATH, key="")
    folder = folder_repo.add(str(SAMPLE_DATA))
    folder_repo.update_status(folder.id, "indexed", image_count=indexed_count)
    folder_repo.close()

    print(f"Indexed {indexed_count} image(s) into {DB_PATH}")


# -- Screenshot helper ---------------------------------------------------------

def _grab(window: Any, name: str) -> None:
    """Capture window to docs/screenshots/<name>.png via QQuickWindow.grabWindow()."""
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.processEvents()
    image = window.grabWindow()
    out = SCREENSHOTS_DIR / f"{name}.png"
    idx = _STEPS.index(name) + 1
    if image.save(str(out)):
        print(f"  [{idx}/{len(_STEPS)}] {out.relative_to(_REPO_ROOT)}")
    else:
        print(f"  WARNING: failed to save {out}")


# -- Preview wait helper -------------------------------------------------------
def _wait_for_preview(
    root: Any,
    ctrl: Any,
    callback: Any,
    preview_id: str = "fullPreview",
    prev_source: str | None = None,
    timeout_ms: int = 15_000,
) -> None:
    """Poll until the named QML Image is fully loaded, then call *callback*.

    How it works
    ------------
    1. If *prev_source* is not None, keep polling until ctrl.selectedImageSource
       changes from that value AND is non-empty.  This guards against two races:
       a) The 150 ms debounce in AppController that briefly leaves
          selectedImageSource as "" before the new URL is set.
       b) The auto-select that fires after search() resolves.
       Pass prev_source="" to wait for *any* new non-empty source (e.g. after
       calling selectResult when the source was previously "").
       Pass prev_source=None to skip phase 1 entirely and wait on Image.status.
    2. Once a non-empty, changed source is seen (or phase 1 is skipped), poll
       the QML Image's *status* property until it reaches Image.Ready (1) or
       Image.Error (3).
    3. Wait an extra 400 ms after Ready so the 150 ms opacity fade-in and any
       GPU texture upload have both completed before grabWindow() is called.
    """
    from PySide6.QtCore import QObject

    # Qt QML Image status codes
    _IMAGE_READY = 1
    _IMAGE_ERROR = 3

    elapsed = [0]

    def poll() -> None:
        cur = ctrl.selectedImageSource

        # --- Phase 1: wait for the source to change from prev_source ----------
        if prev_source is not None:
            if cur == prev_source or not cur:
                # Source hasn't changed yet (or debounce set it to "" briefly)
                elapsed[0] += 100
                if elapsed[0] < timeout_ms:
                    QTimer.singleShot(100, poll)
                else:
                    print(f"  WARNING: source unchanged after {timeout_ms} ms, proceeding")
                    callback()
                return

        # --- Phase 2: prev_source is None and source is empty → nothing to wait
        if not cur:
            callback()
            return

        # --- Phase 3: poll Image.loadStatus (int alias for status) until Ready or Error ---
        preview = root.findChild(QObject, preview_id)
        if preview is not None:
            try:
                raw = preview.property("loadStatus")
                # loadStatus is a QML int property — should come back as a plain int
                status = int(raw.value if hasattr(raw, "value") else raw)
            except (TypeError, ValueError, AttributeError):
                status = 0
            if status in (_IMAGE_READY, _IMAGE_ERROR):
                # 400 ms: covers the 150 ms opacity animation + GPU upload buffer
                QTimer.singleShot(400, callback)
                return

        elapsed[0] += 100
        if elapsed[0] < timeout_ms:
            QTimer.singleShot(100, poll)
        else:
            print(f"  WARNING: {preview_id!r} timed out after {timeout_ms} ms")
            callback()

    poll()


# -- GUI runner ----------------------------------------------------------------

def _run_gui() -> None:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Exif-Turbo")

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

    icon_path = _SRC / "exif_turbo" / "assets" / "logo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    QQuickStyle.setStyle("Material")

    search_model = SearchListModel(cache_dir=THUMB_CACHE)
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings = SettingsModel(DB_PATH.parent / "settings.json")
    ctrl = AppController(DB_PATH, search_model, exif_model, folder_model, settings)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", ctrl)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel", settings)
    ctx.setContextProperty("thirdPartyLicensesHtml", "")
    ctx.setContextProperty("userManualUrl", "")

    qml_path = _SRC / "exif_turbo" / "ui" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        print("ERROR: QML failed to load.")
        sys.exit(1)

    root = engine.rootObjects()[0]
    root.showMaximized()

    def switch_tab(index: int) -> None:
        """Switch the main tab bar by objectName."""
        from PySide6.QtCore import QObject
        tab_bar = root.findChild(QObject, "mainTabBar")
        if tab_bar:
            tab_bar.setProperty("currentIndex", index)
        else:
            print("  WARNING: mainTabBar not found -- tab switch skipped")

    # -- Step 0: lock screen ---------------------------------------------------
    def step_0_lock() -> None:
        switch_tab(0)
        _grab(root, "01_lock_screen")
        ctrl.unlock("")
        ctrl._start_auto_thumbs()  # not triggered automatically on a pre-built DB
        print("  Unlocked -- waiting for thumbnails to build ...")
        QTimer.singleShot(100, step_0_wait_thumbs)

    def step_0_wait_thumbs() -> None:
        if ctrl._thumb_total == 0 or ctrl.isBuildingThumbs:
            QTimer.singleShot(100, step_0_wait_thumbs)
            return
        print(f"  Thumbnails done ({ctrl._thumb_total}) -- waiting for preview to decode ...")
        ctrl.selectResult(0)  # same fix as Browse tab: explicitly trigger the load
        _wait_for_preview(root, ctrl, step_1_search_all, prev_source="")

    # -- Step 1: search tab (all results) -------------------------------------
    def step_1_search_all() -> None:
        switch_tab(0)
        _grab(root, "02_search_all")
        prev = ctrl.selectedImageSource
        ctrl.search("eagle")
        print("  Searching 'eagle' -- waiting for preview to decode ...")
        _wait_for_preview(root, ctrl, step_2_eagle, prev_source=prev)

    # -- Step 2: eagle search -------------------------------------------------
    def step_2_eagle() -> None:
        _grab(root, "03_search_eagle")
        prev = ctrl.selectedImageSource
        ctrl.search("milky way")
        print("  Searching 'milky way' -- waiting for preview to decode ...")
        _wait_for_preview(root, ctrl, step_3_milky_way, prev_source=prev)

    # -- Step 3: milky way search → browse tab --------------------------------
    def step_3_milky_way() -> None:
        _grab(root, "04_search_milky_way")
        switch_tab(1)
        ctrl.browseFolder(str(SAMPLE_DATA))
        # browseFolder only populates the list; nothing is selected yet.
        # Select the first result so the preview panel shows a full image.
        ctrl.selectResult(0)
        prev = ""  # source was empty before selectResult — wait for any non-empty URL
        print("  Browse tab -- waiting for preview to decode ...")
        _wait_for_preview(root, ctrl, step_4_browse_grab, preview_id="fullPreview2", prev_source=prev)

    # -- Step 4: browse tab ---------------------------------------------------
    def step_4_browse_grab() -> None:
        _grab(root, "05_browse_tab")
        switch_tab(2)
        print("  Indexed Folders tab -- waiting for view to settle ...")
        QTimer.singleShot(1000, step_5_folders)

    # -- Step 5: indexed folders tab ------------------------------------------
    def step_5_folders() -> None:
        _grab(root, "06_indexed_folders")
        print(f"  Done -- screenshots in {SCREENSHOTS_DIR.relative_to(_REPO_ROOT)}/")
        QTimer.singleShot(300, app.quit)

    # Kick off after a settle delay (QML init + window paint)
    QTimer.singleShot(800, step_0_lock)

    app.exec()


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    build_demo_db()
    print("\nLaunching UI for screenshot capture ...")
    _run_gui()


if __name__ == "__main__":
    main()
