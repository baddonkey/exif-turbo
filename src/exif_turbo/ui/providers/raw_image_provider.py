from __future__ import annotations

import io
import os
import urllib.parse

try:
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:
    _RAWPY_AVAILABLE = False

from PIL import Image, ImageOps
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class RawImageProvider(QQuickImageProvider):
    """
    Synchronous QML image provider for RAW camera files, forced async by Qt.

    Qt calls requestImage on a background thread when the flag
    ForceAsynchronousImageLoading is set, so the UI is never blocked.

    QML usage:
        Image { source: "image://raw/" + encodeURIComponent(filePath) }

    The provider ID is "raw".
    """

    def __init__(self) -> None:
        super().__init__(
            QQuickImageProvider.ImageType.Image,
            QQuickImageProvider.Flag.ForceAsynchronousImageLoading,
        )

    def requestImage(  # type: ignore[override]
        self, id: str, size: QSize, requestedSize: QSize
    ) -> QImage:
        # Strip the optional ``?m=<mtime>&s=<size>`` query (used by the preview
        # cache lookup) before unquoting — the raw provider only needs the
        # file path itself.
        raw_id = id.split("?", 1)[0]
        path = urllib.parse.unquote(raw_id)
        try:
            img = _decode_raw(path, requestedSize)
        except Exception:
            img = QImage()
        size.setWidth(img.width())
        size.setHeight(img.height())
        return img


def _decode_raw(path: str, requested_size: QSize) -> QImage:
    """Decode the source image at full resolution for the "Raw" toggle.

    The toggle's job is to escape the cached preview and show the actual
    pixels of the source file when the user zooms in. For RAW formats we
    run a full demosaic via ``rawpy.postprocess``; for everything else
    (JPEG, TIFF, PNG, HEIC, …) we just decode the original file with
    Pillow. Either way the returned image is at full source resolution —
    QML scales it down to fit, and zooming past 100 % then reveals real
    pixels instead of the upscaled thumb.

    ``requested_size`` is intentionally ignored.
    """
    del requested_size  # full-resolution by design — see docstring

    img = _load_full_resolution(path)
    if img is None:
        return QImage()

    # Apply EXIF orientation (embedded JPEG thumbs often carry an Orientation tag)
    img = ImageOps.exif_transpose(img)

    # Convert to RGBA for a predictable QImage byte layout
    img = img.convert("RGBA")
    data = bytes(img.tobytes("raw", "RGBA"))
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    # Deep-copy so QImage owns its buffer (data goes out of scope after return)
    return qimg.copy()


# File extensions that ``rawpy`` (LibRaw) can decode. Anything else is
# handed straight to Pillow as a regular image file.
_RAW_EXTS = frozenset({
    ".3fr", ".arw", ".cr2", ".cr3", ".crw", ".dcr", ".dng", ".erf",
    ".kdc", ".mef", ".mos", ".mrw", ".nef", ".nrw", ".orf", ".pef",
    ".raf", ".raw", ".rw2", ".rwl", ".sr2", ".srf", ".srw", ".x3f",
})


def _load_full_resolution(path: str) -> Image.Image | None:
    """Return the source image at full resolution, or ``None`` on failure."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _RAW_EXTS and _RAWPY_AVAILABLE:
        try:
            with rawpy.imread(path) as raw:
                raw_flip = raw.sizes.flip
                try:
                    thumb = raw.extract_thumb()
                except rawpy.LibRawError:
                    thumb = None
                if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
                    # Use the camera's embedded JPEG — it has in-camera processing
                    # (white balance, lens correction, vignetting) already applied.
                    img: Image.Image = Image.open(io.BytesIO(bytes(thumb.data)))
                    img.load()
                    from ...indexing.image_utils import orient_raw_thumb
                    img = orient_raw_thumb(img, raw_flip)
                    return img
                # No embedded JPEG — fall back to full demosaic.
                rgb = raw.postprocess(use_camera_wb=True)
            return Image.fromarray(rgb)
        except Exception:
            return None
    try:
        img = Image.open(path)
        img.load()
        return img
    except Exception:
        return None
