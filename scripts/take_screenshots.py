#!/usr/bin/env python3
"""Generate user-manual screenshots for exif-turbo.

Usage (from the project root, with the venv active):
    python scripts/take_screenshots.py
    python scripts/take_screenshots.py --demo-only
     python scripts/take_screenshots.py --derivative-only

Requirements:
    - ExifTool must be on PATH (used by IndexerService)
    - Sample images in tests/sample-data/schweiz/
    - GPS sample image in tests/sample-data/gps/

The script:
1. Builds a demo SQLite index from the sample images
2. Pre-builds all thumbnails (144×144 PNG) and preview JPEGs (2048px) so
   that the UI shows fully loaded cards and a "Show Preview" toggle, not just
   placeholder spinners.
3. Launches the QML application pointing at that index (empty password)
4. Drives the UI through several states with QTimer callbacks
5. Saves screenshots to docs/screenshots/

Output files:
    01_lock_screen.png       -- startup password prompt
    02_search_all.png        -- search tab with all images loaded
    03_search_eagle.png      -- search results for "eagle"
    04_search_milky_way.png  -- search results for "milky way"
    05_browse_tab.png        -- browse tab (folder tree navigation)
    06_indexed_folders_basic.png  -- indexed folders in Basic mode
    06_indexed_folders_expert.png -- indexed folders in Expert mode
    07_folder_filter.png     -- folder filter popup (Schlösser, Sky, Wildlife)
    08_gps_location_bar.png  -- GPS location bar (image with GPS coordinates selected)
    09_ai_search_mode.png    -- Search tab in AI mode (EXIF/AI toggle + precision picker)
    10_sets_overview.png     -- Sets tab with named sets and image members
    11_set_filter_editor.png -- Saved set filter editor
    12_tagging_drawer.png    -- Custom tagging drawer on a set member
    13_copy_tags_and_descriptions.png -- Bulk tag/description copy panel
    14_set_action_menu.png   -- Action menu scoped to a selected set
    15_derivative_export_settings.png -- Derivative export flavour settings
    16_derivative_export_dialog.png -- Export dialog with flavour previews
    demo_indexed_folders.png -- indexed folders in a taller demo window
    demo_exif_results.png    -- broad EXIF search with bottom metadata visible
    demo_ai_mode.png         -- AI search with bottom metadata visible
    demo_browse_tab.png      -- Browse tab with bottom metadata visible
"""

from __future__ import annotations

import ctypes
import shutil
import os
import sys
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

# -- Resolve project root and make the src package importable ------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

SAMPLE_DATA = _REPO_ROOT / "tests" / "sample-data" / "schweiz"
GPS_SAMPLE_FOLDER = _REPO_ROOT / "tests" / "sample-data" / "gps"
SAMPLE_FOLDERS = [
    SAMPLE_DATA / "Schl\u00f6sser",
    SAMPLE_DATA / "Sky",
    SAMPLE_DATA / "Wildlife",
    GPS_SAMPLE_FOLDER,
]
TAGGING_SAMPLE_SOURCE = (
    SAMPLE_DATA / "Wildlife" / "014 Wild Red Deer Switzerland Photo by Giles Laurent.jpg"
)
SCREENSHOTS_DIR = _REPO_ROOT / "docs" / "screenshots"
DB_PATH = SCREENSHOTS_DIR / "demo.db"
THUMB_CACHE = SCREENSHOTS_DIR / "thumbs"

# -- Qt must be imported after sys.path is updated ----------------------------
from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon, QImageReader  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

from exif_turbo.data.image_index_repository import ImageIndexRepository  # noqa: E402
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository  # noqa: E402
from exif_turbo.indexing.indexer_service import IndexerService  # noqa: E402
from exif_turbo.tagging.sidecar_repository import FilesystemSidecarRepository  # noqa: E402
from exif_turbo.tagging.tagging_service import TaggingService  # noqa: E402
from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel  # noqa: E402
from exif_turbo.ui.models.exif_list_model import ExifListModel  # noqa: E402
from exif_turbo.ui.models.folder_list_model import FolderListModel  # noqa: E402
from exif_turbo.ui.models.search_list_model import SearchListModel  # noqa: E402
from exif_turbo.ui.models.settings_model import SettingsModel  # noqa: E402
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider  # noqa: E402
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider  # noqa: E402
from exif_turbo.ui.providers.thumb_image_provider import ThumbnailImageProvider  # noqa: E402
from exif_turbo.ui.view_models.app_controller import AppController  # noqa: E402
from exif_turbo.utils.preview_cache import preview_cache_name_from_stamp, preview_dir  # noqa: E402
from exif_turbo.utils.preview_render import MAX_PREVIEW_PX, render_preview  # noqa: E402
from exif_turbo.utils.thumb_cache import thumb_cache_name_from_stamp  # noqa: E402

_STEPS = [
    "01_lock_screen",
    "02_search_all",
    "09_ai_search_mode",
    "03_search_eagle",
    "04_search_milky_way",
    "05_browse_tab",
    "06_indexed_folders_basic",
    "06_indexed_folders_expert",
    "07_folder_filter",
    "08_gps_location_bar",
    "10_sets_overview",
    "11_set_filter_editor",
    "12_tagging_drawer",
    "13_copy_tags_and_descriptions",
    "14_set_action_menu",
    "15_derivative_export_settings",
    "16_derivative_export_dialog",
]


# -- Database builder ----------------------------------------------------------

def build_demo_db(extra_folders: list[Path]) -> None:
    """Index each sample sub-folder as a separate indexed folder into the demo database."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)

    repo = ImageIndexRepository(DB_PATH, key="")
    service = IndexerService(repo)
    folder_counts: list[tuple[Path, int]] = []
    for subfolder in [*SAMPLE_FOLDERS, *extra_folders]:
        print(f"Indexing {subfolder.name} ...")
        count, _errors = service.build_index(
            folders=[subfolder],
            on_progress=lambda cur, tot, p: print(f"  {cur}/{tot}  {p.name}"),
            workers=4,
        )
        repo.commit()
        folder_counts.append((subfolder, count))
    repo.close()

    # Register each sub-folder so they all appear in the Indexed Folders tab
    folder_repo = IndexedFolderRepository(DB_PATH, key="")
    for subfolder, count in folder_counts:
        folder = folder_repo.add(str(subfolder))
        folder_repo.update_status(folder.id, "indexed", image_count=count)
    folder_repo.close()

    repo = ImageIndexRepository(DB_PATH, key="")
    tagged_sample = next(
        Path(path)
        for path in repo.get_enabled_stamps()
        if Path(path).name == TAGGING_SAMPLE_SOURCE.name
        and Path(path).parent == extra_folders[0]
    )
    tagging_service = TaggingService(repo, FilesystemSidecarRepository())
    tagging_service.add_free_tag(str(tagged_sample), "Wildlife")
    tagging_service.add_free_tag(str(tagged_sample), "Switzerland")
    tagging_service.set_description(
        str(tagged_sample), "Red deer photographed in the Swiss Alps.", "replace"
    )

    wildlife_paths = sorted(
        str(path)
        for path in (SAMPLE_DATA / "Wildlife").rglob("*.jpg")
    )[:5]
    alpine_set_id = repo.create_image_set(
        "Alpine Wildlife",
        {
            "op": "and",
            "conditions": [
                {"field": "text", "operator": "matches", "value": "deer"}
            ],
        },
    )
    repo.add_images_to_set(alpine_set_id, wildlife_paths)
    favorites_set_id = repo.create_image_set("Weekend Favorites")
    favorite_paths = sorted(
        str(path)
        for folder in (SAMPLE_DATA / "Schl\u00f6sser", SAMPLE_DATA / "Sky")
        for path in folder.rglob("*.jpg")
    )[:5]
    repo.add_images_to_set(favorites_set_id, favorite_paths)
    tagging_demo_id = repo.create_image_set("Tagging Demo")
    repo.add_images_to_set(
        tagging_demo_id,
        [str(tagged_sample), str(TAGGING_SAMPLE_SOURCE)],
    )
    repo.close()

    total = sum(c for _, c in folder_counts)
    print(f"Indexed {total} image(s) across {len(folder_counts)} folders into {DB_PATH}")


# -- Offline thumbnail + preview builder ---------------------------------------

def build_thumbs_and_previews() -> None:
    """Pre-build all thumbnails and preview JPEGs before the GUI starts.

    Generates:
    - ``THUMB_CACHE/<sha1>.png``         — 144×144 thumbnails
    - ``THUMB_CACHE/previews/<sha1>.jpg`` — up-to-2048px preview JPEGs

    Runs synchronously, no Qt required.  Because both artefacts use the same
    SHA-1 content-hash as the in-app workers, the GUI finds them already
    cached and immediately shows fully-rendered cards and preview images.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    _THUMB_SIZE = (144, 144)
    _PREVIEW_LONG_EDGE = min(2048, MAX_PREVIEW_PX)

    THUMB_CACHE.mkdir(parents=True, exist_ok=True)
    prev_dir = preview_dir(THUMB_CACHE)
    prev_dir.mkdir(parents=True, exist_ok=True)

    repo = ImageIndexRepository(DB_PATH, key="")
    stamps: dict[str, tuple[float, int]] = repo.get_enabled_stamps()
    repo.close()

    total = len(stamps)
    print(f"Pre-building {total} thumbnails + previews ...")
    for idx, (path, (mtime, size)) in enumerate(stamps.items(), 1):
        thumb_name = thumb_cache_name_from_stamp(path, mtime, size)
        thumb_path = THUMB_CACHE / thumb_name
        prev_name = preview_cache_name_from_stamp(path, mtime, size)
        prev_path = prev_dir / prev_name

        needs_thumb = not thumb_path.exists()
        needs_preview = not prev_path.exists()
        if not (needs_thumb or needs_preview):
            continue

        print(f"  [{idx}/{total}] {Path(path).name}")
        try:
            pil_img: Image.Image | None = None

            if needs_thumb or needs_preview:
                # Decode once at preview resolution; downsample for the thumb
                pil_img = render_preview(path, _PREVIEW_LONG_EDGE)
                pil_img = ImageOps.exif_transpose(pil_img) if hasattr(pil_img, "info") else pil_img

            if needs_preview and pil_img is not None:
                pil_img.convert("RGB").save(str(prev_path), "JPEG", quality=90)

            if needs_thumb and pil_img is not None:
                thumb_img = pil_img.copy()
                thumb_img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
                thumb_img.convert("RGBA").save(str(thumb_path), "PNG")

        except (OSError, UnidentifiedImageError, Exception) as exc:
            print(f"    WARNING: skipped {Path(path).name}: {exc}")

    print(f"Done — thumbnails in {THUMB_CACHE.relative_to(_REPO_ROOT)}")
    print(f"Done — previews   in {prev_dir.relative_to(_REPO_ROOT)}")


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


def _grab_demo(window: Any, name: str) -> None:
    """Capture a tall-window source frame for the product demo video."""
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.processEvents()
    image = window.grabWindow()
    out = SCREENSHOTS_DIR / f"{name}.png"
    if image.save(str(out)):
        print(f"  Saved demo source {out.relative_to(_REPO_ROOT)}")
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

def _run_gui(
    demo_only: bool = False,
    tagged_sample: Path | None = None,
    derivative_only: bool = False,
) -> None:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Exif-Turbo")

    if os.name == "nt":
        ui_font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"
        if ui_font.exists() and QFontDatabase.addApplicationFont(str(ui_font)) >= 0:
            app.setFont(QFont("Segoe UI", 10))
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
    settings = SettingsModel(THUMB_CACHE / "settings.json")
    settings.setTaggingEnabled(True)
    thumb_provider = ThumbnailImageProvider()
    ctrl = AppController(
        DB_PATH,
        search_model,
        exif_model,
        folder_model,
        settings,
        cache_dir=THUMB_CACHE,
        thumb_provider=thumb_provider,
        allow_plaintext_db=True,
    )
    filter_proxy = CheckedFilterProxyModel()
    filter_proxy.setSourceModel(search_model)
    ctrl.set_filter_proxy(filter_proxy)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    engine.addImageProvider("thumb", thumb_provider)
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", ctrl)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("filteredSearchModel", filter_proxy)
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
    root.showNormal()
    root.setProperty("_demoMode", demo_only)
    root.setProperty("width", 1920 if demo_only else 1200)
    root.setProperty("height", 1080 if demo_only else 800)

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
        if not demo_only and not derivative_only:
            _grab(root, "01_lock_screen")
        ctrl.unlock("")
        ctrl._start_auto_thumbs()  # not triggered automatically on a pre-built DB
        print("  Unlocked -- waiting for thumbnails to build ...")
        QTimer.singleShot(100, step_0_wait_thumbs)

    def step_0_wait_thumbs() -> None:
        if ctrl.isBuildingThumbs:
            QTimer.singleShot(100, step_0_wait_thumbs)
            return
        print(f"  Thumbnails done ({ctrl._thumb_total}) -- waiting for preview to decode ...")
        if derivative_only:
            QTimer.singleShot(400, step_9_derivative_settings)
            return
        if demo_only:
            QTimer.singleShot(400, step_demo_folders)
            return
        ctrl.selectResult(0)  # same fix as Browse tab: explicitly trigger the load
        _wait_for_preview(root, ctrl, step_1_search_all, prev_source="")

    def step_demo_folders() -> None:
        switch_tab(2)
        QTimer.singleShot(400, step_demo_folders_grab)

    def step_demo_folders_grab() -> None:
        _grab_demo(root, "demo_indexed_folders")
        step_1_search_all()

    # -- Step 1: search tab (all results) -------------------------------------
    def step_1_search_all() -> None:
        switch_tab(0)
        if demo_only:
            from PySide6.QtCore import QObject

            search_field = root.findChild(QObject, "searchField")
            if search_field is None:
                raise RuntimeError("Search field not found")
            search_field.setProperty("text", "Photo")
            ctrl.search("Photo")
            QTimer.singleShot(1500, step_demo_exif_grab)
            return
        _grab(root, "02_search_all")
        prev = str(ctrl.selectedImageSource)
        ctrl.search("chateau")
        print("  Searching 'chateau' -- waiting for preview to decode ...")
        _wait_for_preview(root, ctrl, step_1_prepare_ai_mode, prev_source=prev)

    def step_demo_exif_grab() -> None:
        _grab_demo(root, "demo_exif_results")
        from PySide6.QtCore import QObject

        search_field = root.findChild(QObject, "searchField")
        prev = str(ctrl.selectedImageSource)
        ctrl.search("chateau")
        if search_field is not None:
            search_field.setProperty("text", "chateau")
        print("  Searching 'chateau' -- preparing AI-mode demo frame ...")
        _wait_for_preview(root, ctrl, step_1_prepare_ai_mode, prev_source=prev)

    # -- Step 1a: prepare AI screenshot on a castle result -------------------
    def step_1_prepare_ai_mode() -> None:
        ctrl.setAiEnabled(True)
        from PySide6.QtCore import QObject
        search_field = root.findChild(QObject, "searchField")
        if search_field is not None:
            search_field.setProperty("text", "castle on a lake at dusk")
        root.setProperty("_aiSearchPrecision", "normal")
        root.setProperty("_aiSearchMode", True)
        ctrl.setAiSearchMode(True)
        next_step = step_demo_ai_grab if demo_only else step_1_ai_mode
        QTimer.singleShot(350, next_step)

    def step_demo_ai_grab() -> None:
        _grab_demo(root, "demo_ai_mode")
        switch_tab(1)
        ctrl.browseFolder(str(SAMPLE_FOLDERS[2]))
        ctrl.selectResult(0)
        print("  Browse tab -- waiting for demo preview to decode ...")
        _wait_for_preview(
            root,
            ctrl,
            step_demo_browse_grab,
            preview_id="fullPreview2",
            prev_source="",
        )

    def step_demo_browse_grab() -> None:
        _grab_demo(root, "demo_browse_tab")
        print(f"  Demo source captures saved in {SCREENSHOTS_DIR.relative_to(_REPO_ROOT)}/")
        QTimer.singleShot(300, app.quit)

    # -- Step 1b: search tab (AI mode controls visible) ----------------------
    def step_1_ai_mode() -> None:
        _grab(root, "09_ai_search_mode")
        root.setProperty("_aiSearchMode", False)
        ctrl.setAiSearchMode(False)
        prev = str(ctrl.selectedImageSource)
        ctrl.search("eagle")
        print("  Searching 'eagle' -- waiting for preview to decode ...")
        _wait_for_preview(root, ctrl, step_2_eagle, prev_source=prev)

    # -- Step 2: eagle search -------------------------------------------------
    def step_2_eagle() -> None:
        _grab(root, "03_search_eagle")
        prev = str(ctrl.selectedImageSource)
        ctrl.search("milky way")
        print("  Searching 'milky way' -- waiting for preview to decode ...")
        _wait_for_preview(root, ctrl, step_3_milky_way, prev_source=prev)

    # -- Step 3: milky way search → browse tab --------------------------------
    def step_3_milky_way() -> None:
        _grab(root, "04_search_milky_way")
        switch_tab(1)
        ctrl.browseFolder(str(SAMPLE_FOLDERS[2]))
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

    # -- Step 5: indexed folders tab, Basic mode ------------------------------
    def step_5_folders() -> None:
        from PySide6.QtCore import QObject
        folders_panel = root.findChild(QObject, "foldersPanel")
        if folders_panel is None:
            raise RuntimeError("FoldersPanel not found")
        folders_panel.setProperty("expertMode", False)
        _grab(root, "06_indexed_folders_basic")
        folders_panel.setProperty("expertMode", True)
        print("  Indexed Folders Expert mode -- waiting for view to settle ...")
        QTimer.singleShot(750, step_5_folders_expert)

    # -- Step 5a: indexed folders tab, Expert mode ----------------------------
    def step_5_folders_expert() -> None:
        _grab(root, "06_indexed_folders_expert")
        switch_tab(0)
        ctrl.search("")
        # Select Schlösser filter so its results appear in the background
        ctrl.toggleSearchFolderFilter(str(SAMPLE_FOLDERS[0]))
        print("  Schlösser filter active -- waiting for results to settle ...")
        QTimer.singleShot(1500, step_6_open_popup)

    # -- Step 6: folder filter popup (Schlösser selected, popup open) ---------
    def step_6_open_popup() -> None:
        from PySide6.QtCore import QMetaObject, Qt, QCoreApplication
        QCoreApplication.processEvents()
        # openFolderFilterPopup() is a QML function defined at the root level
        QMetaObject.invokeMethod(root, "openFolderFilterPopup", Qt.ConnectionType.DirectConnection)
        print("  Popup open -- taking screenshot ...")
        QTimer.singleShot(800, step_6_grab)

    def step_6_grab() -> None:
        _grab(root, "07_folder_filter")
        QTimer.singleShot(500, step_7_gps_setup)

    # -- Step 7: GPS location bar (image with GPS coordinates) ----------------
    def step_7_gps_setup() -> None:
        from PySide6.QtCore import QMetaObject, Qt
        # Close the folder filter popup, clear all folder filters, then
        # filter to the GPS-only folder so result 0 is the Xenakis image.
        QMetaObject.invokeMethod(root, "closeFolderFilterPopup", Qt.ConnectionType.DirectConnection)
        ctrl.clearSearchFolderFilters()
        ctrl.toggleSearchFolderFilter(str(GPS_SAMPLE_FOLDER))
        ctrl.search("")
        prev = str(ctrl.selectedImageSource)
        ctrl.selectResult(0)
        print("  GPS image -- waiting for preview to decode ...")
        _wait_for_preview(root, ctrl, step_7_gps_grab, prev_source=prev or "")

    def step_7_gps_grab() -> None:
        _grab(root, "08_gps_location_bar")
        QTimer.singleShot(500, step_8_sets)

    def click_named(name: str) -> None:
        from PySide6.QtCore import QObject, QMetaObject, Qt

        button = root.findChild(QObject, name)
        if button is None or not QMetaObject.invokeMethod(
            button, "click", Qt.ConnectionType.DirectConnection
        ):
            raise RuntimeError(f"Unable to click QML control {name!r}")

    def step_8_sets() -> None:
        from PySide6.QtCore import QObject

        if tagged_sample is None:
            raise RuntimeError("A temporary tagged sample is required for set captures")
        switch_tab(3)
        sets_page = root.findChild(QObject, "setsPage")
        if sets_page is None:
            raise RuntimeError("Sets page not found")
        sets_page.setProperty("selectedSetId", 1)
        ctrl.selectImageSetMember(str(TAGGING_SAMPLE_SOURCE))
        QTimer.singleShot(900, step_8_sets_grab)

    def step_8_sets_grab() -> None:
        _grab(root, "10_sets_overview")
        click_named("editSetFilterButton")
        QTimer.singleShot(500, step_8_filter_grab)

    def step_8_filter_grab() -> None:
        from PySide6.QtCore import QObject, QMetaObject, Qt

        _grab(root, "11_set_filter_editor")
        filter_dialog = root.findChild(QObject, "imageSetFilterDialog")
        if filter_dialog is None or not QMetaObject.invokeMethod(
            filter_dialog, "close", Qt.ConnectionType.DirectConnection
        ):
            raise RuntimeError("Unable to close the set filter editor")
        QTimer.singleShot(350, step_8_tagging)

    def step_8_tagging() -> None:
        from PySide6.QtCore import QObject

        sets_page = root.findChild(QObject, "setsPage")
        if sets_page is None or tagged_sample is None:
            raise RuntimeError("Tagging demo set is unavailable")
        sets_page.setProperty("selectedSetId", 3)
        ctrl.selectImageSetMember(str(tagged_sample))
        QTimer.singleShot(500, step_8_open_tagging)

    def step_8_open_tagging() -> None:
        click_named("taggingWorkbenchButton")
        QTimer.singleShot(650, step_8_tagging_grab)

    def step_8_tagging_grab() -> None:
        _grab(root, "12_tagging_drawer")
        click_named("taggingWorkbenchButton")
        QTimer.singleShot(350, step_8_copy_panel)

    def step_8_copy_panel() -> None:
        click_named("copyTaggingWorkbenchButton")
        QTimer.singleShot(650, step_8_copy_panel_grab)

    def step_8_copy_panel_grab() -> None:
        _grab(root, "13_copy_tags_and_descriptions")
        click_named("copyTaggingWorkbenchButton")
        QTimer.singleShot(350, step_8_action_menu)

    def step_8_action_menu() -> None:
        from PySide6.QtCore import QObject

        sets_page = root.findChild(QObject, "setsPage")
        if sets_page is None:
            raise RuntimeError("Sets page not found")
        sets_page.setProperty("selectedSetId", 1)
        ctrl.selectImageSetMember(str(TAGGING_SAMPLE_SOURCE))
        QTimer.singleShot(500, step_8_open_action_menu)

    def step_8_open_action_menu() -> None:
        from PySide6.QtCore import QObject, QMetaObject, Qt

        menu_bar = root.findChild(QObject, "mainMenuBar")
        action_menu = None
        if menu_bar is not None:
            action_menu = next(
                (
                    child
                    for child in menu_bar.children()
                    if str(child.property("title") or "").replace("&", "") == "Action"
                ),
                None,
            )
        if action_menu is None or not QMetaObject.invokeMethod(
            action_menu, "open", Qt.ConnectionType.DirectConnection
        ):
            raise RuntimeError("Unable to open the Action menu for the Sets capture")
        QTimer.singleShot(350, step_8_action_grab)

    def step_8_action_grab() -> None:
        _grab(root, "14_set_action_menu")
        QTimer.singleShot(300, step_9_derivative_settings)

    def step_9_derivative_settings() -> None:
        root.setProperty("height", 1000)
        switch_tab(4)
        QTimer.singleShot(500, step_9_select_web_jpeg)

    def step_9_select_web_jpeg() -> None:
        from PySide6.QtCore import QObject

        page = root.findChild(QObject, "derivativeExportPage")
        if page is None:
            raise RuntimeError("Derivative Export page not found")
        flavours = json.loads(str(settings.property("derivativeExportFlavoursJson")))
        web_jpeg = next(
            (flavour for flavour in flavours if flavour.get("name") == "Web JPEG"),
            None,
        )
        if web_jpeg is None:
            raise RuntimeError("Web JPEG flavour not found")
        page.setProperty("selectedFlavourId", web_jpeg["id"])
        QTimer.singleShot(350, step_9_settings_grab)

    def step_9_settings_grab() -> None:
        _grab(root, "15_derivative_export_settings")
        flavours = json.loads(str(settings.property("derivativeExportFlavoursJson")))
        for flavour in flavours:
            if flavour.get("name") == "Web PNG":
                flavour["selected_by_default"] = False
        settings.setDerivativeExportFlavours(json.dumps(flavours))
        switch_tab(2)
        QTimer.singleShot(500, step_9_open_dialog)

    def step_9_open_dialog() -> None:
        from PySide6.QtCore import QObject, Q_ARG, QMetaObject, Qt

        dialog = root.findChild(QObject, "derivativeExportDialog")
        if dialog is None:
            raise RuntimeError("Derivative export dialog not found")
        root.setProperty("height", 1000)
        opened = QMetaObject.invokeMethod(
            dialog,
            "openForScope",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", "results"),
        )
        if not opened:
            raise RuntimeError("Unable to open the derivative export dialog")
        dialog.setProperty("sampleSourcePath", r"C:\Photos\DSC_1234.jpg")
        dialog.setProperty(
            "outputDirectoryText", r"C:\Users\Public\Pictures\Derivatives"
        )
        QTimer.singleShot(500, step_9_dialog_grab)

    def step_9_dialog_grab() -> None:
        _grab(root, "16_derivative_export_dialog")
        print(f"  Done -- screenshots in {SCREENSHOTS_DIR.relative_to(_REPO_ROOT)}/")
        QTimer.singleShot(300, app.quit)

    # Kick off after a settle delay (QML init + window paint)
    QTimer.singleShot(800, step_0_lock)

    app.exec()


def main() -> None:
    demo_only = "--demo-only" in sys.argv
    if demo_only:
        sys.argv.remove("--demo-only")
    derivative_only = "--derivative-only" in sys.argv
    if derivative_only:
        sys.argv.remove("--derivative-only")
    logging.basicConfig(level=logging.WARNING)
    with tempfile.TemporaryDirectory(prefix="exif-turbo-docs-") as temp_dir:
        tagged_folder = Path(temp_dir) / "Wildlife"
        tagged_folder.mkdir()
        tagged_sample = tagged_folder / TAGGING_SAMPLE_SOURCE.name
        shutil.copy2(TAGGING_SAMPLE_SOURCE, tagged_sample)
        build_demo_db([tagged_folder])
        build_thumbs_and_previews()
        print("\nLaunching UI for screenshot capture ...")
        _run_gui(
            demo_only=demo_only,
            tagged_sample=tagged_sample,
            derivative_only=derivative_only,
        )


if __name__ == "__main__":
    main()
