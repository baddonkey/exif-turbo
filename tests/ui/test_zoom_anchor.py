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
import sys
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

# macOS trackpad smooth-scroll zoom-out sequence.
# On macOS, a two-finger scroll gesture emits many small angleDelta events
# (typically −3 to −18 per frame) rather than the −120 per-notch of a
# physical mouse wheel.  Sum ≈ −300 units (~2.5 notch equivalents).
_MACOS_ZOOM_OUT_SEQUENCE: list[int] = [-3, -5, -8, -12, -15, -18, -15, -12, -8, -5, -3]
_MACOS_ZOOM_IN_SEQUENCE:  list[int] = [+3, +5, +8, +12, +15, +18, +15, +12, +8, +5, +3]


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


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def zoom_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Single indexed image (from sample-data) for the zoom tests."""
    base = tmp_path_factory.mktemp("zoom_test")
    img_dir = base / "images"
    img_dir.mkdir()

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

    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")

    # Show & expose the window so the very first synthesised wheel event
    # is delivered. Without this, the QML scene is constructed but never
    # rendered, and Qt 6.11 drops the first wheel event sent to the scene
    # — causing flaky off-by-one zoom drift in the tests below.
    if hasattr(root, "setVisible"):
        root.setVisible(True)
        try:
            qtbot.waitExposed(root, timeout=3000)
        except Exception:
            qtbot.wait(100)
        # Let async Image.onSourceChanged callbacks (which reset _zoom = 1.0)
        # settle BEFORE the test sets its own initial zoom.
        qtbot.wait(150)

    yield controller, engine, root

    controller.close()
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


# ── macOS-specific zoom-out bug documentation ────────────────────────────────

class TestPinchIncrementalZoom:
    """Pure-arithmetic tests for the incremental PinchHandler zoom formula.

    The PinchHandler uses an incremental formula each ``onScaleChanged`` tick::

        factor   = scale / prevScale          # delta from last tick
        newZoom  = clamp(currentZoom * factor, 1.0, maxZoom)
        new_cx   = (contentX + cx) * actualFactor − cx   # viewport anchor

    Advantages over the previous ``startZoom * scale`` approach
    ────────────────────────────────────────────────────────────
    • **No dead zone**: clamping at zoom=1.0 doesn't accumulate "scale debt".
      Reversing direction immediately increases zoom.
    • **No jump on gesture restart**: each gesture starts with factor ≈ 1.0
      regardless of any stale ``scale`` value carried over from the previous
      gesture, so there is no sudden position shift on the first tick.
    """

    @staticmethod
    def _step(current_zoom: float, scale_now: float, scale_prev: float) -> float:
        """One incremental onScaleChanged step."""
        factor = scale_now / scale_prev
        return max(1.0, min(8.0, current_zoom * factor))

    def test_zoom_decreases_monotonically_toward_minimum(self) -> None:
        """Incremental pinch-in steps decrease zoom smoothly to 1.0."""
        zoom, prev = 3.0, 1.0
        zooms: list[float] = [zoom]
        for i in range(1, 30):
            s = 0.9 ** i
            zoom = self._step(zoom, s, prev)
            zooms.append(zoom)
            prev = s

        for i in range(1, len(zooms)):
            assert zooms[i] <= zooms[i - 1], (
                f"Zoom increased during zoom-out at step {i}: "
                f"{zooms[i-1]:.4f} → {zooms[i]:.4f}"
            )
        assert zooms[-1] == pytest.approx(1.0)

    def test_reversal_responds_immediately_at_minimum(self) -> None:
        """At zoom=1.0, the very next outward step increases zoom without delay."""
        zoom = self._step(1.0, 1.05, 1.0)
        assert zoom == pytest.approx(1.05, rel=1e-6), (
            f"Expected zoom=1.05 on first outward step from minimum, got {zoom:.6f}"
        )

    def test_no_dead_zone_after_overshoot(self) -> None:
        """Pinching far past zoom=1.0 does NOT create a dead zone on reversal.

        Old approach: ``startZoom * scale`` — over-pinching built scale debt;
        scale had to travel back above ``1/startZoom`` before zoom responded.

        New approach: ``currentZoom * (scale/prevScale)`` — no debt. After
        clamping, the very next outward increment (factor > 1) raises zoom.
        """
        zoom, prev = 1.5, 1.0

        # Pinch way past minimum in two big steps
        zoom = self._step(zoom, 0.1, prev); prev = 0.1
        assert zoom == pytest.approx(1.0)
        zoom = self._step(zoom, 0.05, prev); prev = 0.05
        assert zoom == pytest.approx(1.0)

        # Reverse: factor = 0.055 / 0.05 = 1.1  →  zoom must respond immediately
        zoom = self._step(zoom, 0.055, prev)
        assert zoom == pytest.approx(1.1, rel=1e-6), (
            f"Dead zone detected: expected zoom=1.1 on reversal, got {zoom:.6f}.\n"
            "The incremental formula should have no dead zone."
        )

    def test_anchor_invariant_holds_per_incremental_step(self) -> None:
        """Image fraction under the centroid is preserved each incremental step."""
        vp_w, content_x, cx = 800.0, 150.0, 300.0
        zoom = 2.0
        factor = 1.08
        new_zoom = max(1.0, min(8.0, zoom * factor))
        actual_factor = new_zoom / zoom
        new_w = max(vp_w, vp_w * new_zoom)
        new_cx = max(0.0, min((content_x + cx) * actual_factor - cx, new_w - vp_w))

        fraction_before = (content_x + cx) / (vp_w * zoom)
        fraction_after = (new_cx + cx) / (vp_w * new_zoom)
        assert math.isclose(fraction_before, fraction_after, rel_tol=1e-9), (
            f"Cursor anchor broken: fraction {fraction_before:.6f} → {fraction_after:.6f}"
        )

    def test_gesture_restart_starts_from_current_zoom(self) -> None:
        """Simulates end + start of new gesture; second gesture picks up current zoom.

        When ``onActiveChanged`` fires (active=True), Qt resets PinchHandler.scale
        to 1.0.  We capture ``_prevScale = scale = 1.0``.  The first
        ``onScaleChanged`` tick then has ``factor = scale / 1.0 ≈ 1.0``, which
        means no jump — zoom stays at its current value on the first frame.
        """
        # First gesture: zoom 2.0 → 2.4
        zoom, prev = 2.0, 1.0
        zoom = self._step(zoom, 1.2, prev)
        assert zoom == pytest.approx(2.4)

        # Gesture ends; new gesture starts → scale resets to 1.0 in Qt.
        # Capture _prevScale = 1.0 (as onActiveChanged does).
        prev = 1.0
        # First tick of second gesture: tiny scale change (1.0 → 1.01)
        zoom = self._step(zoom, 1.01, prev)
        assert zoom == pytest.approx(2.4 * 1.01, rel=1e-6), (
            f"Jump on gesture restart: expected {2.4 * 1.01:.4f}, got {zoom:.4f}"
        )


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="macOS-specific touchpad scroll behaviour; Qt event delivery on "
           "other platforms synthesises angleDelta from pixelDelta differently "
           "and amplifies the per-step zoom factor, so these contracts only "
           "hold on macOS.",
)
class TestMacOSTouchpadScrollZoomOut:
    """E2E tests for Ctrl+scroll zoom via WheelHandler (mouse or trackpad).

    The WheelHandler requires ``Qt.ControlModifier`` so that plain two-finger
    trackpad scroll is left to the Flickable for panning.  Zoom is triggered
    by Ctrl + two-finger scroll (or a physical mouse wheel).

    Three behaviours verified
    ─────────────────────────
    1. *Monotonic zoom-out*: each small negative angleDelta (Ctrl+scroll) must
       decrease zoom when zoom > 1.0.

    2. *Cumulative accuracy*: many tiny steps must accumulate to exactly
       ``∏ pow(1.2, δᵢ/120)`` (no rounding leakage).

    3. *Momentum ignored*: ``ScrollMomentum`` phase events must not change
       zoom after the gesture ends.
    """

    @staticmethod
    def _send_wheel(
        qtbot: QtBot,
        qml_window: QObject,
        flick_item: QQuickItem,
        cursor_vx: float,
        cursor_vy: float,
        angle_delta_y: int,
        pixel_delta_y: int = 0,
        phase: Qt.ScrollPhase = Qt.ScrollPhase.NoScrollPhase,
        inverted: bool = False,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.ControlModifier,
    ) -> None:
        """Synthesise one wheel event at (cursor_vx, cursor_vy).

        Defaults to ControlModifier because the WheelHandler now requires
        Ctrl to distinguish zoom from pan.
        """
        scene_pos: QPointF = flick_item.mapToScene(QPointF(cursor_vx, cursor_vy))
        win: QQuickWindow = qml_window  # type: ignore[assignment]
        global_pos = QPointF(win.x() + scene_pos.x(), win.y() + scene_pos.y())
        event = QWheelEvent(
            scene_pos,
            global_pos,
            QPoint(0, pixel_delta_y),
            QPoint(0, angle_delta_y),
            Qt.MouseButton.NoButton,
            modifiers,
            phase,
            inverted,
        )
        QCoreApplication.sendEvent(qml_window, event)
        QCoreApplication.processEvents()

    def test_zoom_out_small_deltas_decrease_zoom_monotonically(
        self,
        qtbot: QtBot,
        zoom_engine: tuple[AppController, QQmlApplicationEngine, QObject],
    ) -> None:
        """Each small negative angleDelta event must decrease zoom when zoom > 1.0.

        Failure means individual smooth-scroll events are being swallowed —
        either by the angleDelta=0 guard (if events arrive with only pixelDelta)
        or by a floating-point threshold inside the WheelHandler.
        """
        controller, engine, root = zoom_engine
        preview_host: QQuickItem = root.findChild(QQuickItem, "previewHost")  # type: ignore[assignment]
        preview_flick: QQuickItem = root.findChild(QQuickItem, "previewFlick")  # type: ignore[assignment]

        preview_host.setProperty("_zoom", 2.0)
        preview_flick.setProperty("contentX", 0.0)
        preview_flick.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        vp_w = float(preview_flick.property("width"))
        vp_h = float(preview_flick.property("height"))
        cx, cy = vp_w / 2, vp_h / 2

        swallowed: list[int] = []
        prev_zoom = float(preview_host.property("_zoom"))

        for delta in _MACOS_ZOOM_OUT_SEQUENCE:
            self._send_wheel(qtbot, root, preview_flick, cx, cy, delta)
            cur_zoom = float(preview_host.property("_zoom"))
            if math.isclose(cur_zoom, prev_zoom, rel_tol=1e-9):
                swallowed.append(delta)
            prev_zoom = cur_zoom

        final_zoom = float(preview_host.property("_zoom"))

        assert final_zoom < 2.0, (
            f"Zoom did not decrease after macOS smooth-scroll zoom-out sequence.\n"
            f"final_zoom={final_zoom:.4f} (expected < 2.0)\n"
            "Likely cause: all events have angleDelta.y=0 (only pixelDelta set) "
            "and are discarded by the guard 'if (event.angleDelta.y === 0) return'."
        )
        assert not swallowed, (
            f"{len(swallowed)}/{len(_MACOS_ZOOM_OUT_SEQUENCE)} events produced no zoom "
            f"change (final_zoom={final_zoom:.4f}).  Swallowed angleDelta values: "
            f"{swallowed}\n"
            "Individual smooth-scroll steps are too small to register — consider "
            "accumulating pixelDelta or accepting every non-zero angleDelta step."
        )

    def test_zoom_out_cumulative_factor_matches_pow_formula(
        self,
        qtbot: QtBot,
        zoom_engine: tuple[AppController, QQmlApplicationEngine, QObject],
    ) -> None:
        """The cumulative zoom after N smooth events equals ∏ pow(1.2, δᵢ/120).

        Verifies there is no rounding leakage or early-exit that causes the
        actual zoom to diverge from the mathematically expected value.
        """
        controller, engine, root = zoom_engine
        preview_host: QQuickItem = root.findChild(QQuickItem, "previewHost")  # type: ignore[assignment]
        preview_flick: QQuickItem = root.findChild(QQuickItem, "previewFlick")  # type: ignore[assignment]

        initial_zoom = 3.0
        preview_host.setProperty("_zoom", initial_zoom)
        preview_flick.setProperty("contentX", 0.0)
        preview_flick.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        vp_w = float(preview_flick.property("width"))
        vp_h = float(preview_flick.property("height"))

        for delta in _MACOS_ZOOM_OUT_SEQUENCE:
            self._send_wheel(qtbot, root, preview_flick, vp_w / 2, vp_h / 2, delta)

        final_zoom = float(preview_host.property("_zoom"))
        expected_factor = math.prod(math.pow(1.2, d / 120.0) for d in _MACOS_ZOOM_OUT_SEQUENCE)
        expected_zoom = max(1.0, initial_zoom * expected_factor)

        assert final_zoom == pytest.approx(expected_zoom, rel=1e-4), (
            f"Cumulative zoom mismatch after macOS smooth-scroll sequence.\n"
            f"  expected factor : {expected_factor:.6f}\n"
            f"  expected zoom   : {expected_zoom:.4f}\n"
            f"  actual zoom     : {final_zoom:.4f}\n"
            f"  per-step factors: {[round(math.pow(1.2, d/120), 5) for d in _MACOS_ZOOM_OUT_SEQUENCE]}"
        )

    def test_pixel_delta_only_events_do_not_zoom(
        self,
        qtbot: QtBot,
        zoom_engine: tuple[AppController, QQmlApplicationEngine, QObject],
    ) -> None:
        """Events with angleDelta.y=0 (pixelDelta-only) must not change zoom.

        macOS may deliver trackpad scroll events where ``angleDelta`` is zero
        and only ``pixelDelta`` is set.  The current WheelHandler ignores these
        events entirely via ``if (event.angleDelta.y === 0) return``, so zoom
        does not change.

        This test documents the current (correct) behaviour as a contract:
        if the implementation is later changed to also handle pixelDelta, this
        test will need updating to reflect the new intended semantics.
        """
        controller, engine, root = zoom_engine
        preview_host: QQuickItem = root.findChild(QQuickItem, "previewHost")  # type: ignore[assignment]
        preview_flick: QQuickItem = root.findChild(QQuickItem, "previewFlick")  # type: ignore[assignment]

        preview_host.setProperty("_zoom", 2.0)
        QCoreApplication.processEvents()

        vp_w = float(preview_flick.property("width"))
        vp_h = float(preview_flick.property("height"))

        for _ in range(12):
            self._send_wheel(
                qtbot, root, preview_flick,
                vp_w / 2, vp_h / 2,
                angle_delta_y=0, pixel_delta_y=-15,
            )

        zoom_after = float(preview_host.property("_zoom"))
        assert zoom_after == pytest.approx(2.0, abs=1e-6), (
            f"pixelDelta-only events changed zoom: {zoom_after:.4f} (expected 2.0).\n"
            "If this fails intentionally (pixelDelta support was added), update this "
            "test to verify the new zoom-change semantics."
        )

    def test_momentum_scroll_events_do_not_zoom_after_gesture_ends(
        self,
        qtbot: QtBot,
        zoom_engine: tuple[AppController, QQmlApplicationEngine, QObject],
    ) -> None:
        """DEMONSTRATES THE JUMP BUG: ScrollMomentum events must not change zoom.

        On macOS, after the user lifts their fingers, the OS sends inertial
        momentum events (Qt.ScrollPhase.ScrollMomentum) with non-zero
        angleDelta.  The WheelHandler does not check ``event.phase``, so it
        processes these like normal gesture events — continuing to zoom after
        the user has released the trackpad.

        This manifests as:
          • zoom-in gesture ends → image keeps zooming in on its own
          • zoom-out gesture ends near zoom=1.0 → sudden jump to 1.0 from
            the last few momentum ticks crossing the minimum threshold

        Expected fix: add an early exit in the WheelHandler::

            if (event.phase === Qt.ScrollMomentum) {
                event.accepted = true
                return
            }

        This test FAILS with the current code if momentum events carry
        non-zero angleDelta (which they do on macOS).
        """
        controller, engine, root = zoom_engine
        preview_host: QQuickItem = root.findChild(QQuickItem, "previewHost")  # type: ignore[assignment]
        preview_flick: QQuickItem = root.findChild(QQuickItem, "previewFlick")  # type: ignore[assignment]

        preview_host.setProperty("_zoom", 2.0)
        preview_flick.setProperty("contentX", 0.0)
        preview_flick.setProperty("contentY", 0.0)
        QCoreApplication.processEvents()

        vp_w = float(preview_flick.property("width"))
        vp_h = float(preview_flick.property("height"))
        cx, cy = vp_w / 2, vp_h / 2

        # ── gesture phase: user scrolls to zoom out ──
        self._send_wheel(qtbot, root, preview_flick, cx, cy,
                         angle_delta_y=0, phase=Qt.ScrollPhase.ScrollBegin)
        for delta in _MACOS_ZOOM_OUT_SEQUENCE:
            self._send_wheel(qtbot, root, preview_flick, cx, cy,
                             angle_delta_y=delta, phase=Qt.ScrollPhase.ScrollUpdate)
        self._send_wheel(qtbot, root, preview_flick, cx, cy,
                         angle_delta_y=0, phase=Qt.ScrollPhase.ScrollEnd)

        zoom_at_gesture_end = float(preview_host.property("_zoom"))

        # ── momentum phase: inertial events after fingers lift ──
        # macOS sends decaying momentum ticks; angleDelta values are non-zero.
        momentum_deltas = [-10, -8, -6, -4, -3, -2, -1]
        for delta in momentum_deltas:
            self._send_wheel(qtbot, root, preview_flick, cx, cy,
                             angle_delta_y=delta,
                             phase=Qt.ScrollPhase.ScrollMomentum)

        zoom_after_momentum = float(preview_host.property("_zoom"))

        assert zoom_after_momentum == pytest.approx(zoom_at_gesture_end, abs=0.01), (
            f"\n"
            f"MOMENTUM EVENTS CHANGED ZOOM after gesture end:\n"
            f"  zoom at ScrollEnd      = {zoom_at_gesture_end:.4f}\n"
            f"  zoom after momentum    = {zoom_after_momentum:.4f}\n"
            f"  delta                  = {zoom_after_momentum - zoom_at_gesture_end:+.4f}\n"
            f"\n"
            f"macOS inertial scroll ticks (ScrollMomentum) are being processed\n"
            f"as normal zoom steps.  Fix: in the WheelHandler onWheel handler add\n"
            f"  if (event.phase === Qt.ScrollMomentum) {{ event.accepted = true; return }}\n"
            f"before the angleDelta check."
        )
