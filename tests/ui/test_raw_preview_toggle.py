"""End-to-end tests for the Preview / Raw source toggle.

The "Raw" toggle in the big preview is meant to escape the cached preview
and load the *full-resolution* raw decode so the user can zoom in and see
real sensor detail. These tests cover both halves of that contract:

1. The controller plumbing actually switches ``selectedImageSource`` to
   the ``image://raw/...`` scheme when the toggle flips.
2. The ``RawImageProvider`` returns a full-resolution image — i.e. it
   does NOT downscale to QML's ``requestedSize``, otherwise zooming in
   reveals no extra detail and the user just sees the same blurry thumb.

The second test reproduces the user-reported bug: clicking "Raw" still
appears to show the thumb because the provider downscales the QImage to
the on-screen Image element's size before returning it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QSize, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider, _decode_raw
from exif_turbo.ui.view_models.app_controller import AppController

_QML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "exif_turbo" / "ui" / "qml" / "Main.qml"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def indexed_db(tmp_path: Path) -> tuple[Path, Path]:
    """Tiny DB with a single JPEG so the controller has something to select."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img_path = img_dir / "sample.jpg"
    Image.new("RGB", (32, 32), color=(120, 80, 40)).save(str(img_path), "JPEG")

    repo = ImageIndexRepository(tmp_path / "demo.db", key="")
    stat = img_path.stat()
    repo.upsert_image(
        str(img_path),
        "sample.jpg",
        stat.st_mtime,
        stat.st_size,
        {"FileName": "sample.jpg"},
        "sample.jpg",
    )
    repo.commit()
    repo.close()
    return tmp_path / "demo.db", tmp_path


@pytest.fixture
def window(
    qtbot: QtBot,
    indexed_db: tuple[Path, Path],
) -> Generator[AppController, None, None]:
    db_path, base = indexed_db
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

    yield controller

    engine.deleteLater()
    qtbot.wait(100)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_raw_toggle_switches_selected_image_source_to_raw_scheme(
    qtbot: QtBot,
    window: AppController,
) -> None:
    """Toggling the Raw button must switch the QML Image source to image://raw/."""
    # Arrange — unlock and select the only image so a preview path is pending.
    controller = window
    with qtbot.waitSignal(controller.totalResultsChanged, timeout=3000):
        controller.unlock("")
    with qtbot.waitSignal(controller.selectedImageSourceChanged, timeout=3000):
        controller.selectResult(0)

    assert controller.selectedImageSource.startswith("image://preview/")
    assert controller.useRawPreview is False

    # Act — flip the toggle exactly the way the QML MouseArea does.
    with qtbot.waitSignal(controller.selectedImageSourceChanged, timeout=2000):
        controller.setUseRawPreview(True)

    # Assert — both the flag and the source URL must reflect "raw" mode.
    assert controller.useRawPreview is True
    assert controller.selectedImageSource.startswith("image://raw/"), (
        f"Expected image://raw/... but got {controller.selectedImageSource!r}"
    )


def test_raw_provider_returns_full_resolution_not_downscaled_to_requested_size(
    qtbot: QtBot,
) -> None:
    """The Raw provider must hand QML the full-resolution decode.

    Reproduces the user-reported bug: clicking "Raw" appears to show the
    same thumb because ``_decode_raw`` downscales the demosaiced image to
    QML's ``requestedSize`` (the on-screen Image element's pixel size).
    Once the image is shrunk to ~800x600 there is no extra sensor detail
    to reveal when the user zooms in, so visually it is indistinguishable
    from the cached preview / embedded thumb.
    """
    # Arrange — fake a 4000x3000 raw decode via rawpy.
    full_w, full_h = 4000, 3000
    fake_rgb = np.zeros((full_h, full_w, 3), dtype=np.uint8)

    class _FakeRaw:
        def __enter__(self) -> "_FakeRaw":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def postprocess(self, **_: object) -> np.ndarray:
            return fake_rgb

    # Act — request the raw at a typical on-screen preview size (800x600).
    requested = QSize(800, 600)
    with patch(
        "exif_turbo.ui.providers.raw_image_provider.rawpy.imread",
        return_value=_FakeRaw(),
    ):
        qimg = _decode_raw("/fake/path.cr2", requested)

    # Assert — the returned QImage must keep the full sensor resolution so
    # QML can show real detail when the user zooms in. If the provider
    # downscales here, the toggle is effectively a no-op (the bug).
    assert qimg.width() == full_w, (
        f"Raw decode was downscaled to {qimg.width()}x{qimg.height()} — "
        "the Raw toggle would just show the same blurry thumb."
    )
    assert qimg.height() == full_h


def test_raw_provider_falls_back_to_full_jpeg_for_non_raw_files(
    tmp_path: Path,
) -> None:
    """The "Raw" toggle on a JPEG must load the full-resolution JPEG.

    Reproduces a second bug: ``rawpy.imread`` raises on JPEG files, so
    the provider returned an empty QImage. QML then showed nothing on
    the full-preview layer and the cached thumb stayed visible — making
    the toggle look like a no-op for the (very common) non-raw case.
    """
    # Arrange — a real JPEG on disk at known resolution.
    full_w, full_h = 2400, 1600
    jpeg_path = tmp_path / "photo.jpg"
    Image.new("RGB", (full_w, full_h), color=(40, 80, 120)).save(
        str(jpeg_path), "JPEG"
    )

    # Act
    qimg = _decode_raw(str(jpeg_path), QSize(800, 600))

    # Assert — full JPEG must come back, not an empty image.
    assert not qimg.isNull(), "Provider returned empty QImage for a JPEG"
    assert qimg.width() == full_w
    assert qimg.height() == full_h
