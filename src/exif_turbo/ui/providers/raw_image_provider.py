from __future__ import annotations

import io
import logging
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

from ...indexing.image_utils import VIDEO_EXTENSIONS
from ...utils.preview_render import MAX_PREVIEW_PX, MAX_PREVIEW_SOURCE_PX, render_preview
from ...utils.video_frame import extract_video_frame

_log = logging.getLogger(__name__)


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
        path, pixel_count = _parse_id(id)
        try:
            img = _decode_raw(path, requestedSize, pixel_count)
        except Exception:
            img = QImage()
        size.setWidth(img.width())
        size.setHeight(img.height())
        return img


def _decode_raw(path: str, requested_size: QSize, known_pixel_count: int | None = None) -> QImage:
    """Decode the source image at full resolution for the "Raw" toggle.

    The toggle's job is to escape the cached preview and show the actual
    pixels of the source file when the user zooms in. For RAW formats we
    run a full demosaic via ``rawpy.postprocess``; for everything else
    (JPEG, TIFF, PNG, HEIC, …) we just decode the original file with
    Pillow. Either way the returned image is at full source resolution —
    QML scales it down to fit, and zooming past 100 % then reveals real
    pixels instead of the upscaled thumb.

    ``requested_size`` is intentionally ignored.
    """
    del requested_size  # full-resolution by design — see docstring

    img = _load_full_resolution(path, known_pixel_count)
    if img is None:
        return QImage()

    # Orientation is already applied inside _load_full_resolution:
    # RAW files use orient_raw_thumb (raw_flip + EXIF fallback),
    # non-RAW files use ImageOps.exif_transpose.

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


def _parse_id(raw_id: str) -> tuple[str, int | None]:
    """Split a provider id into ``(path, pixel_count)``.

    The id format is ``<encoded-path>[?m=<mtime>&s=<size>[&px=<pixel_count>]]``.
    The optional ``px`` parameter carries the DB-stored pixel count (width *
    height from exiftool metadata) so the provider can route large images to
    pyvips without probing the source file.
    """
    qpos = raw_id.find("?")
    path = urllib.parse.unquote(raw_id[:qpos] if qpos >= 0 else raw_id)
    if qpos < 0:
        return path, None
    params = urllib.parse.parse_qs(raw_id[qpos + 1:])
    try:
        px = int(params["px"][0])
    except (KeyError, IndexError, ValueError):
        px = None
    return path, px


def _load_full_resolution(path: str, known_pixel_count: int | None = None) -> Image.Image | None:
    """Return the source image at full resolution, or ``None`` on failure."""
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTENSIONS:
        try:
            # Full-resolution frame at 1/3 of video duration — no size cap
            return extract_video_frame(path)
        except Exception:
            return None
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
    # Use the indexed exiftool pixel count when available; otherwise probe the
    # file header.  If the probe fails (e.g. unsupported TIFF codec) treat the
    # image as potentially oversized so pyvips gets a chance to decode it.
    if known_pixel_count is not None:
        pixel_count: int | None = known_pixel_count
    else:
        try:
            with Image.open(path) as _probe:
                pixel_count = _probe.width * _probe.height
        except Exception:  # noqa: BLE001
            pixel_count = None  # probe failed — fall through to pyvips
    if pixel_count is None or pixel_count > MAX_PREVIEW_SOURCE_PX:
        try:
            return render_preview(path, MAX_PREVIEW_PX, known_pixel_count=known_pixel_count)
        except Exception as exc:  # noqa: BLE001
            _log.warning("pyvips render failed for %r: %s", path, exc)
            return None
    try:
        img = Image.open(path)
        img.load()
        return ImageOps.exif_transpose(img)
    except Exception:
        return None
