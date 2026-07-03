"""E2E unit tests for AppController preview clipboard/save actions.

Verifies that after calling the preview copy/save actions:
  - The clipboard QMimeData contains explicit ``image/png`` bytes (so macOS
    maps them to the ``public.png`` UTI that native apps like Messages require).
  - The clipboard also carries a QImage via ``setImageData`` (so legacy Win32
    apps that only read CF_DIB can still paste).
  - The emitted ``clipboardCopyDone`` signal carries a non-empty message.
  - When the path is empty the method is a no-op.
  - When the file cannot be decoded the fallback copies the path as text.
  - Save Preview As writes the cached preview even when the source file is gone.

Run with:
    pytest tests/ui/test_clipboard_copy.py -v -s
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from pytestqt.qtbot import QtBot

from exif_turbo.ui.view_models import app_controller as app_controller_module
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.view_models.app_controller import AppController


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_controller(tmp_path: Path) -> AppController:
    """Minimal AppController — DB file need not exist for clipboard tests."""
    return AppController(
        tmp_path / "dummy.db",
        SearchListModel(cache_dir=tmp_path / "thumbs"),
        ExifListModel(),
        FolderListModel(),
    )


def _make_jpeg(path: Path, color: tuple[int, int, int] = (200, 100, 50)) -> Path:
    Image.new("RGB", (64, 64), color=color).save(str(path), "JPEG")
    return path


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_copyPreviewToClipboard_with_valid_image_sets_png_mimedata(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange
    img_path = _make_jpeg(tmp_path / "photo.jpg")
    ctrl = _make_controller(tmp_path)
    ctrl._pending_preview_path = str(img_path)

    # Act
    with qtbot.waitSignal(ctrl.clipboardCopyDone, timeout=5_000) as blocker:
        ctrl.copyPreviewToClipboard()

    # Assert — signal carries a non-empty toast message
    assert blocker.args[0]

    # Assert — clipboard has explicit image/png MIME entry
    mime = QGuiApplication.clipboard().mimeData()
    assert mime.hasFormat("image/png"), "image/png MIME type must be present for macOS"

    # Assert — the PNG bytes decode to a valid image
    png_bytes = bytes(mime.data("image/png"))
    decoded = Image.open(io.BytesIO(png_bytes))
    assert decoded.format == "PNG"
    assert decoded.width > 0 and decoded.height > 0

    ctrl.close()


def test_copyPreviewToClipboard_with_valid_image_sets_image_data(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange
    img_path = _make_jpeg(tmp_path / "photo.jpg")
    ctrl = _make_controller(tmp_path)
    ctrl._pending_preview_path = str(img_path)

    # Act
    with qtbot.waitSignal(ctrl.clipboardCopyDone, timeout=5_000):
        ctrl.copyPreviewToClipboard()

    # Assert — QImage is present for legacy Win32 CF_DIB consumers
    mime = QGuiApplication.clipboard().mimeData()
    assert mime.hasImage(), "QImage must be present for legacy Win32 clipboard consumers"
    qimage = mime.imageData()
    assert not qimage.isNull()
    assert qimage.width() > 0 and qimage.height() > 0

    ctrl.close()


def test_copyPreviewToClipboard_with_empty_path_emits_no_signal(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange
    ctrl = _make_controller(tmp_path)
    ctrl._pending_preview_path = ""

    # Act / Assert — no signal must fire within the timeout
    with qtbot.assertNotEmitted(ctrl.clipboardCopyDone):
        ctrl.copyPreviewToClipboard()

    ctrl.close()


def test_copyPreviewToClipboard_with_missing_file_copies_path_as_text(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange
    missing = str(tmp_path / "does_not_exist.jpg")
    ctrl = _make_controller(tmp_path)
    ctrl._pending_preview_path = missing

    # Act
    with qtbot.waitSignal(ctrl.clipboardCopyDone, timeout=5_000) as blocker:
        ctrl.copyPreviewToClipboard()

    # Assert — fallback signal fires with a message
    assert blocker.args[0]

    # Assert — clipboard holds the file path as plain text
    assert QGuiApplication.clipboard().text() == missing

    ctrl.close()


def test_copyPreviewToClipboard_missing_source_with_cache_sets_png_mimedata(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    missing = str(tmp_path / "detached" / "photo.jpg")
    ctrl = _make_controller(tmp_path)
    ctrl._pending_preview_path = missing
    monkeypatch.setattr(
        ctrl,
        "_load_preview_for_clipboard",
        lambda path: Image.new("RGB", (16, 12), color=(12, 34, 56)),
    )

    # Act
    with qtbot.waitSignal(ctrl.clipboardCopyDone, timeout=5_000) as blocker:
        ctrl.copyPreviewToClipboard()

    # Assert
    assert blocker.args[0]
    assert QGuiApplication.clipboard().mimeData().hasFormat("image/png")

    ctrl.close()


def test_doSavePreview_missing_source_with_cache_writes_file(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    missing = str(tmp_path / "detached" / "photo.jpg")
    ctrl = _make_controller(tmp_path)
    ctrl._pending_preview_path = missing
    monkeypatch.setattr(
        ctrl,
        "_load_preview_for_clipboard",
        lambda path: Image.new("RGB", (16, 12), color=(12, 34, 56)),
    )
    dest = tmp_path / "saved_preview.png"

    # Act
    with qtbot.waitSignal(ctrl.clipboardCopyDone, timeout=5_000) as blocker:
        ctrl.doSavePreview(QUrl.fromLocalFile(str(dest)).toString())

    # Assert
    assert blocker.args[0]
    assert dest.exists()
    assert Image.open(dest).format == "PNG"

    ctrl.close()


def test_doSavePreview_raw_mode_missing_source_emits_file_not_accessible(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    missing = str(tmp_path / "detached" / "photo.jpg")
    ctrl = _make_controller(tmp_path)
    ctrl._pending_preview_path = missing
    ctrl._use_raw_preview = True

    def _raise_missing_source(
        path: str, max_px: int, known_pixel_count: int | None = None
    ) -> Image.Image:
        raise OSError("missing source")

    monkeypatch.setattr(app_controller_module, "render_preview", _raise_missing_source)
    dest = tmp_path / "saved_preview.png"

    # Act
    with qtbot.waitSignal(ctrl.clipboardCopyDone, timeout=5_000) as blocker:
        ctrl.doSavePreview(QUrl.fromLocalFile(str(dest)).toString())

    # Assert
    assert blocker.args[0]
    assert not dest.exists()

    ctrl.close()
