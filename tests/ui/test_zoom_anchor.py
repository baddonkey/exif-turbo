"""E2E tests: cursor-anchored zoom in the Search-tab preview panel.

Invariant
─────────
After a zoom step triggered by the scroll wheel at cursor position (vx, vy),
the *image fraction* under the cursor must not change:

    image_fraction = (contentX + vx) / contentWidth

Derivation (viewport-coordinate formula)
─────────────────────────────────────────
Let:
  W  = previewHost.width      (viewport width, constant during one step)
  z0 = zoom before step
  z1 = zoom after  step,  actualFactor = z1 / z0
  cx = previewFlick.contentX  before step
  vx = cursor x in VIEWPORT coordinates (0 … W)

Image fraction under cursor before zoom:
    f = (cx + vx) / (W * z0)

After zoom the same fraction maps to content position (W * z1) * f.
For that content position to stay at viewport x = vx:
    new_contentX + vx = (W * z1) * f = (cx + vx) * actualFactor

    ⟹  new_contentX = (cx + vx) * actualFactor − vx          [formula VP]

The current WheelHandler uses exactly this formula — but it is only correct
if event.x is in *viewport* coordinates.

In Qt 6 / Flickable-hosted WheelHandler, event.x may be in *content*
coordinates (cx + vx). If so, the correct formula is:

    ⟹  new_contentX = event.x * (actualFactor − 1) + cx       [formula CT]

These formulas diverge whenever cx > 0 (i.e. after a horizontal pan):
    formula VP with content-coord event.x: overcorrects by cx*(actualFactor−1)
    formula CT with viewport-coord event.x: undercorrects by the same amount

The test fixture pans to a known contentX > 0, zooms once, then checks that
the image fraction is invariant.  If it fails, the assertion message shows:
  • the actual vs expected contentX
  • the image fraction before and after (should be equal)
  • which alternative formula would have produced the correct result

Run with:
    pytest tests/ui/test_zoom_anchor.py -v -s
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image as PilImage
from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QPoint,
    QPointF,
    Qt,
    QUrl,
)
from PySide6.QtGui import QWheelEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.view_models.app_controller import AppController

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)

# One real-ish image indexed for the preview to have something to show.
_SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample-data" / "schweiz"

_ZOOM_FACTOR = 1.2           # one wheel-notch zoom-in
_INITIAL_ZOOM = 2.0          # start zoomed in so contentWidth > viewport width
_INITIAL_CONTENT_X = 200.0   # simulate a horizontal pan — THIS is what exposes the bug


# ── helpers ───────────────────────────────────────────────────────────────────

def _image_fraction_x(content_x: float, cursor_viewport_x: float, content_w: float) -> float:
    """Fraction [0..1] of the content pixel that is under the cursor."""
    return (content_x + cursor_viewport_x) / content_w


def _expected_content_x_viewport_formula(
    old_cx: float,
    cursor_vx: float,
    factor: float,
    new_content_w: float,
    viewport_w: float,
) -> float:
    """Correct new_contentX (cursor-anchor invariant).

    Works from viewport cursor position directly:
      new_cx = (old_cx + cursor_vx) * factor - cursor_vx

    Equivalently, when event.x is a content coordinate (= old_cx + cursor_vx):
      new_cx = event.x * (factor - 1) + old_cx
    Both forms produce the same result.
    """
    raw = (old_cx + cursor_vx) * factor - cursor_vx
    return max(0.0, min(raw, new_content_w - viewport_w))


def _expected_content_x_content_formula(
    old_cx: float,
    cursor_vx: float,
    factor: float,
    new_content_w: float,
    viewport_w: float,
) -> float:
    """What the BROKEN QML formula produces when event.x is a content coordinate.

    The broken formula was: (oldContentX + event.x) * factor - event.x
    Qt 6 delivers event.x = old_cx + cursor_vx  (content coordinate), so:
      (old_cx + old_cx + cursor_vx) * factor - (old_cx + cursor_vx)
    This overcorrects by old_cx * (factor - 1) vs the correct answer.
    """
    event_x_content = old_cx + cursor_vx
    raw = (old_cx + event_x_content) * factor - event_x_content
    return max(0.0, min(raw, new_content_w - viewport_w))


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def zoom_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Single indexed image (from sample-data) for the zoom tests."""
    base = tmp_path_factory.mktemp("zoom_test")
    img_dir = base / "images"
    img_dir.mkdir()

    # Use a real JPEG from sample-data if available; otherwise create a synthetic one.
    sample_images = list(_SAMPLE_DIR.rglob("*.jpg")) + list(_SAMPLE_DIR.rglob("*.JPG"))
    if sample_images:
        src = sample_images[0]
        dst = img_dir / src.name
        dst.write_bytes(src.read_bytes())
        img_path = dst
    else:
        img_path = img_dir / "test.jpg"
        PilImage.new("RGB", (800, 600), color=(100, 150, 200)).save(str(img_path))

    repo = ImageIndexRepository(base / "zoom.db", key="")
    stat = img_path.stat()
    metadata = {"FileName": img_path.name, "Make": "Test", "Model": "ZoomCam"}
    text = f"{img_path.name} Test ZoomCam"
    repo.upsert_image(str(img_path), img_path.name, stat.st_mtime, stat.st_size, metadata, text)
    repo.commit()
    repo.close()
    return base / "zoom.db", base


@pytest.fixture
def zoom_engine(
    qtbot: QtBot,
    zoom_db: tuple[Path, Path],
) -> Generator[tuple[AppController, QQmlApplicationEngine, QObject], None, None]:
    """Full QML window backed by zoom_db; yields (controller, engine, root)."""
    db_path, base = zoom_db

    search_model = SearchListModel(cache_dir=base / "thumbs")
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings_model = SettingsModel(base / "settings.json")
    controller = AppController(db_path, search_model, exif_model, folder_model)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("controller", controller)
    ctx.setContextProperty("searchModel", search_model)
    ctx.setContextProperty("exifModel", exif_model)
    ctx.setContextProperty("folderListModel", folder_model)
    ctx.setContextProperty("settingsModel", settings_model)
    ctx.setContextProperty("thirdPartyLicensesHtml", "")
    ctx.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_PATH)))

    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
    root = engine.rootObjects()[0]

    # Unlock the controller so the Search tab is populated
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")

    yield controller, engine, root

    engine.deleteLater()
    qtbot.wait(200)


# ── pure-math reference tests (must always PASS) ─────────────────────────────

class TestZoomFormulaReference:
    """
    Verify the *correct* mathematical formula in isolation.

    These tests are pure arithmetic — no Qt involved.  They document what
    new_contentX MUST be so that the image fraction under the cursor is
    invariant after a zoom step.
    """

    def test_fraction_preserved_unscrolled_center(self) -> None:
        """Zoom 1.0 → 1.2 with cursor at center; contentX starts at 0."""
        vp_w = 500.0
        old_cx = 0.0
        vx = vp_w / 2          # 250
        z0, z1 = 1.0, 1.2
        factor = z1 / z0
        old_cw = vp_w * z0     # 500
        new_cw = vp_w * z1     # 600

        fraction_before = _image_fraction_x(old_cx, vx, old_cw)

        # Viewport-formula answer (also correct here since old_cx == 0)
        new_cx = _expected_content_x_viewport_formula(old_cx, vx, factor, new_cw, vp_w)

        fraction_after = _image_fraction_x(new_cx, vx, new_cw)
        assert math.isclose(fraction_before, fraction_after, rel_tol=1e-9), (
            f"fraction {fraction_before:.6f} → {fraction_after:.6f}, cx_new={new_cx}"
        )

    def test_fraction_preserved_scrolled_center(self) -> None:
        """
        Zoom 2.0 → 2.4 with cursor at centre; contentX = 200 (panned right).

        This is the scenario that exposes the coordinate-space ambiguity:
          event.x in viewport coords = 250
          event.x in content  coords = 200 + 250 = 450

          With viewport formula and event.x = 250:
            new_cx = (200+250)*1.2 − 250 = 540−250 = 290   ← correct

          With content  formula and event.x = 450:
            new_cx = 450*0.2 + 200 = 90+200 = 290           ← also correct

          The two formulas give the SAME correct answer from different inputs.
          The question is: which input does Qt 6.10 actually deliver?
        """
        vp_w = 500.0
        old_cx = _INITIAL_CONTENT_X   # 200
        vx = vp_w / 2                  # 250 (viewport coords)
        z0, z1 = _INITIAL_ZOOM, _INITIAL_ZOOM * _ZOOM_FACTOR
        factor = z1 / z0
        old_cw = vp_w * z0             # 1000
        new_cw = vp_w * z1             # 1200

        fraction_before = _image_fraction_x(old_cx, vx, old_cw)
        # Expected: 450/1000 = 0.45

        new_cx = _expected_content_x_viewport_formula(old_cx, vx, factor, new_cw, vp_w)
        # (200+250)*1.2 − 250 = 290

        fraction_after = _image_fraction_x(new_cx, vx, new_cw)
        # (290+250)/1200 = 540/1200 = 0.45 ✓

        assert new_cx == pytest.approx(290.0, abs=1e-9)
        assert math.isclose(fraction_before, fraction_after, rel_tol=1e-9)

    def test_fraction_preserved_scrolled_off_center(self) -> None:
        """Zoom with cursor at right third of viewport, already panned."""
        vp_w = 500.0
        old_cx = 150.0
        vx = vp_w * 0.7              # 350
        z0, z1 = 3.0, 3.0 * _ZOOM_FACTOR
        factor = z1 / z0
        old_cw = vp_w * z0
        new_cw = vp_w * z1

        fraction_before = _image_fraction_x(old_cx, vx, old_cw)
        new_cx = _expected_content_x_viewport_formula(old_cx, vx, factor, new_cw, vp_w)
        fraction_after = _image_fraction_x(new_cx, vx, new_cw)

        assert math.isclose(fraction_before, fraction_after, rel_tol=1e-9)


# ── e2e tests (interact with real QML) ───────────────────────────────────────

class TestZoomAnchorE2E:
    """
    Drive the real QML via synthesised wheel events and check contentX.

    EXPECTED TO FAIL with the current WheelHandler formula because:

      The current formula assumes event.x is in VIEWPORT coordinates:
          new_contentX = (oldContentX + event.x) * factor − event.x

      But Qt 6 delivers WheelHandler events inside a Flickable with
      event.x in CONTENT coordinates (scroll offset + viewport x).
      When contentX > 0 the formula overcorrects by contentX*(factor−1).

    The error is zero when contentX == 0, which is why the zoom looks
    correct before any panning.
    """

    @staticmethod
    def _send_zoom_in(
        qtbot: QtBot,
        qml_window: QObject,
        flick_item: QQuickItem,
        cursor_vx: float,
        cursor_vy: float,
    ) -> None:
        """Synthesise one upward wheel notch at (cursor_vx, cursor_vy) in the Flickable."""
        # mapToScene: item-local → window-local (scene) coordinates
        scene_pos: QPointF = flick_item.mapToScene(QPointF(cursor_vx, cursor_vy))
        # mapToGlobal: window-local → screen coordinates
        win: QQuickWindow = qml_window  # type: ignore[assignment]
        global_pos = QPointF(win.x() + scene_pos.x(), win.y() + scene_pos.y())

        event = QWheelEvent(
            scene_pos,              # position in window-local coords
            global_pos,             # global screen position
            QPoint(0, 0),           # pixelDelta  (high-DPI trackpad; 0 = not available)
            QPoint(0, 120),         # angleDelta  (positive Y = scroll up = zoom in)
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,                  # inverted
        )
        QCoreApplication.sendEvent(qml_window, event)
        QCoreApplication.processEvents()

    def test_zoom_anchors_to_cursor_when_unscrolled(
        self,
        qtbot: QtBot,
        zoom_engine: tuple[AppController, QQmlApplicationEngine, QObject],
    ) -> None:
        """
        Baseline: from contentX=0 both the viewport and content formulas agree.
        This test PASSES even with the wrong formula.
        Its purpose is to confirm the wheel event delivery mechanism works at all.
        """
        controller, engine, root = zoom_engine

        preview_host: QQuickItem = root.findChild(QQuickItem, "previewHost")  # type: ignore[assignment]
        preview_flick: QQuickItem = root.findChild(QQuickItem, "previewFlick")  # type: ignore[assignment]
        assert preview_host is not None, "Add objectName: 'previewHost' to Main.qml"
        assert preview_flick is not None, "Add objectName: 'previewFlick' to Main.qml"

        # Reset to zoom=1, contentX=0
        preview_host.setProperty("_zoom", 1.0)
        preview_flick.setProperty("contentX", 0.0)
        preview_flick.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        vp_w = float(preview_flick.property("width"))
        vp_h = float(preview_flick.property("height"))
        cursor_vx = vp_w / 2
        cursor_vy = vp_h / 2

        old_zoom = float(preview_host.property("_zoom"))
        old_cx = float(preview_flick.property("contentX"))
        old_cw = max(vp_w, vp_w * old_zoom)

        self._send_zoom_in(qtbot, root, preview_flick, cursor_vx, cursor_vy)

        actual_zoom = float(preview_host.property("_zoom"))
        actual_cx = float(preview_flick.property("contentX"))
        actual_cw = max(vp_w, vp_w * actual_zoom)

        factor = actual_zoom / old_zoom
        expected_cx = _expected_content_x_viewport_formula(old_cx, cursor_vx, factor, actual_cw, vp_w)

        fraction_before = _image_fraction_x(old_cx, cursor_vx, old_cw)
        fraction_after = _image_fraction_x(actual_cx, cursor_vx, actual_cw)

        assert actual_zoom == pytest.approx(old_zoom * _ZOOM_FACTOR, rel=1e-6), "zoom did not change"
        assert actual_cx == pytest.approx(expected_cx, abs=2.0), (
            f"contentX wrong even from unscrolled position — wheel delivery broken?\n"
            f"  expected={expected_cx:.1f}  actual={actual_cx:.1f}"
        )
        assert math.isclose(fraction_before, fraction_after, abs_tol=1e-4), (
            f"Image fraction changed even from unscrolled position\n"
            f"  before={fraction_before:.6f}  after={fraction_after:.6f}"
        )

    def test_zoom_anchors_to_cursor_after_pan(
        self,
        qtbot: QtBot,
        zoom_engine: tuple[AppController, QQmlApplicationEngine, QObject],
    ) -> None:
        """
        Main invariant test.  CURRENTLY EXPECTED TO FAIL.

        Setup
        ─────
        • zoom    = 2.0   → contentWidth = 2 × viewport_width
        • contentX = 200  → panned right; this is what reveals the bug
        • cursor at centre of viewport

        Expected after zoom-in × 1.2  (new zoom = 2.4)
        ─────────────────────────────
        image_fraction_before = (200 + centre) / (W × 2.0)
        new_contentX (correct) = (200 + centre) × 1.2 − centre   [formula VP]
                               = 200 × 0.2 + centre × 0.2

        With the CURRENT (broken) formula, if event.x arrives as content
        coordinates (200 + centre), the result is:
          new_contentX = (200 + [200+centre]) × 1.2 − [200+centre]
                       = correct + 200 × 0.2 = correct + 40 px   ← overcorrects

        The image appears to pan 40 px away from the cursor on each notch.
        """
        controller, engine, root = zoom_engine

        preview_host: QQuickItem = root.findChild(QQuickItem, "previewHost")  # type: ignore[assignment]
        preview_flick: QQuickItem = root.findChild(QQuickItem, "previewFlick")  # type: ignore[assignment]
        assert preview_host is not None
        assert preview_flick is not None

        # Set a known initial state: zoom=2, panned right 200 px
        preview_host.setProperty("_zoom", _INITIAL_ZOOM)
        preview_flick.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()
        preview_flick.setProperty("contentX", _INITIAL_CONTENT_X)
        QCoreApplication.processEvents()

        vp_w = float(preview_flick.property("width"))
        vp_h = float(preview_flick.property("height"))

        # Verify setup succeeded (contentX may be clamped if viewport is small)
        actual_initial_cx = float(preview_flick.property("contentX"))
        max_cx = max(0.0, vp_w * _INITIAL_ZOOM - vp_w)
        assumed_cx = min(_INITIAL_CONTENT_X, max_cx)
        assert actual_initial_cx == pytest.approx(assumed_cx, abs=2.0), (
            f"Initial contentX setup failed: expected≈{assumed_cx:.1f}, got {actual_initial_cx:.1f}\n"
            f"viewport_w={vp_w:.1f}, max_cx={max_cx:.1f}"
        )

        cursor_vx = vp_w / 2
        cursor_vy = vp_h / 2

        old_cx = actual_initial_cx
        old_zoom = float(preview_host.property("_zoom"))
        old_cw = max(vp_w, vp_w * old_zoom)

        # ── zoom in at cursor ──
        self._send_zoom_in(qtbot, root, preview_flick, cursor_vx, cursor_vy)

        actual_zoom = float(preview_host.property("_zoom"))
        actual_cx = float(preview_flick.property("contentX"))
        new_cw = max(vp_w, vp_w * actual_zoom)
        factor = actual_zoom / old_zoom

        # What contentX SHOULD be (anchor formula)
        expected_cx = _expected_content_x_viewport_formula(old_cx, cursor_vx, factor, new_cw, vp_w)

        # What the CURRENT formula gives if event.x is in content coords
        cx_if_content_coords = _expected_content_x_content_formula(old_cx, cursor_vx, factor, new_cw, vp_w)

        fraction_before = _image_fraction_x(old_cx, cursor_vx, old_cw)
        fraction_after = _image_fraction_x(actual_cx, cursor_vx, new_cw)

        # ── assertion ─────────────────────────────────────────────────────────
        # This FAILS with the current formula because event.x is in content
        # coordinates inside a Flickable-hosted WheelHandler, so the formula
        # (oldContentX + event.x) * factor − event.x overcorrects.
        assert math.isclose(fraction_before, fraction_after, abs_tol=1e-3), (
            f"\n"
            f"CURSOR-ANCHOR BROKEN — image fraction changed after zoom:\n"
            f"  fraction before = {fraction_before:.6f}\n"
            f"  fraction after  = {fraction_after:.6f}\n"
            f"  delta           = {abs(fraction_after - fraction_before):.6f}\n"
            f"\n"
            f"contentX  expected = {expected_cx:.2f}  (viewport-coord formula)\n"
            f"contentX  actual   = {actual_cx:.2f}\n"
            f"contentX  if content-coord formula = {cx_if_content_coords:.2f}\n"
            f"\n"
            f"  actual ≈ expected?             {abs(actual_cx - expected_cx):.2f} px off\n"
            f"  actual ≈ content-coord result? {abs(actual_cx - cx_if_content_coords):.2f} px off\n"
            f"\n"
            f"If 'actual ≈ content-coord result', event.x is in content coordinates\n"
            f"and the fix is to use: event.x*(factor−1) + oldContentX\n"
            f"instead of: (oldContentX + event.x)*factor − event.x\n"
        )

    def test_zoom_anchors_to_cursor_after_large_pan(
        self,
        qtbot: QtBot,
        zoom_engine: tuple[AppController, QQmlApplicationEngine, QObject],
    ) -> None:
        """
        Same invariant with a larger pan (contentX = 40 % of contentWidth).
        A bigger initial contentX means a larger error if the formula is wrong.

        With initial_zoom=3, contentWidth=3W; pan to cx=0.4*(3W-W)=0.8W.
        Error if formula uses content coords: cx*(factor-1) = 0.8W*0.2 = 0.16W px.
        On a 500 px wide viewport that is 80 px — very visible.
        """
        controller, engine, root = zoom_engine

        preview_host: QQuickItem = root.findChild(QQuickItem, "previewHost")  # type: ignore[assignment]
        preview_flick: QQuickItem = root.findChild(QQuickItem, "previewFlick")  # type: ignore[assignment]

        initial_zoom = 3.0
        preview_host.setProperty("_zoom", initial_zoom)
        QCoreApplication.processEvents()

        vp_w = float(preview_flick.property("width"))
        vp_h = float(preview_flick.property("height"))
        max_cx = max(0.0, vp_w * initial_zoom - vp_w)
        initial_cx = max_cx * 0.4   # pan to 40 % of scroll range

        preview_flick.setProperty("contentX", initial_cx)
        QCoreApplication.processEvents()

        actual_initial_cx = float(preview_flick.property("contentX"))
        cursor_vx = vp_w / 2
        cursor_vy = vp_h / 2

        old_zoom = float(preview_host.property("_zoom"))
        old_cx = actual_initial_cx
        old_cw = max(vp_w, vp_w * old_zoom)

        self._send_zoom_in(qtbot, root, preview_flick, cursor_vx, cursor_vy)

        actual_zoom = float(preview_host.property("_zoom"))
        actual_cx = float(preview_flick.property("contentX"))
        new_cw = max(vp_w, vp_w * actual_zoom)
        factor = actual_zoom / old_zoom

        expected_cx = _expected_content_x_viewport_formula(old_cx, cursor_vx, factor, new_cw, vp_w)
        cx_if_content_coords = _expected_content_x_content_formula(old_cx, cursor_vx, factor, new_cw, vp_w)

        fraction_before = _image_fraction_x(old_cx, cursor_vx, old_cw)
        fraction_after = _image_fraction_x(actual_cx, cursor_vx, new_cw)

        assert math.isclose(fraction_before, fraction_after, abs_tol=1e-3), (
            f"\n"
            f"CURSOR-ANCHOR BROKEN — large-pan scenario:\n"
            f"  initial_zoom={initial_zoom}  initial_cx={old_cx:.2f}\n"
            f"  fraction before = {fraction_before:.6f}\n"
            f"  fraction after  = {fraction_after:.6f}\n"
            f"\n"
            f"  expected_cx (correct)             = {expected_cx:.2f}\n"
            f"  actual_cx                         = {actual_cx:.2f}\n"
            f"  cx if event.x=content-coords      = {cx_if_content_coords:.2f}\n"
            f"\n"
            f"  error vs expected:                {actual_cx - expected_cx:+.2f} px\n"
            f"  error vs content-coord result:    {actual_cx - cx_if_content_coords:+.2f} px\n"
            f"\n"
            f"Expected per-notch error if content-coord: {old_cx * (factor - 1):.2f} px\n"
        )
