from __future__ import annotations

import io
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
        path = urllib.parse.unquote(id)
        try:
            img = _decode_raw(path, requestedSize)
        except Exception:
            img = QImage()
        size.setWidth(img.width())
        size.setHeight(img.height())
        return img


def _decode_raw(path: str, requested_size: QSize) -> QImage:
    """Decode a RAW file to QImage via rawpy → Pillow."""
    if not _RAWPY_AVAILABLE:
        return QImage()

    with rawpy.imread(path) as raw:
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                img: Image.Image = Image.open(io.BytesIO(thumb.data))
                img.load()
            else:
                img = Image.fromarray(thumb.data)
        except rawpy.LibRawNoThumbnailError:
            # No embedded preview — fall back to half-size demosaic (faster)
            rgb = raw.postprocess(use_camera_wb=True, half_size=True)
            img = Image.fromarray(rgb)

    # Apply EXIF orientation (embedded JPEG thumbs often carry an Orientation tag)
    img = ImageOps.exif_transpose(img)

    # Resize to fit the requested size while preserving aspect ratio
    if requested_size.isValid() and not requested_size.isEmpty():
        img.thumbnail(
            (requested_size.width(), requested_size.height()),
            Image.LANCZOS,
        )

    # Convert to RGBA for a predictable QImage byte layout
    img = img.convert("RGBA")
    data = bytes(img.tobytes("raw", "RGBA"))
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    # Deep-copy so QImage owns its buffer (data goes out of scope after return)
    return qimg.copy()
