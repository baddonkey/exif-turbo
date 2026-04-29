from __future__ import annotations

import io
import urllib.parse
from pathlib import Path

try:
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:
    _RAWPY_AVAILABLE = False

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError
from PySide6.QtCore import QSize, QThread
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from ...indexing.image_utils import RAW_EXTENSIONS, orient_raw_thumb

# Cap preview decoding at this size — avoids allocating 200 MB for a 50 MP image
# while still looking sharp on any monitor up to 4K.
_MAX_PREVIEW_PX = 2048


class PreviewImageProvider(QQuickImageProvider):
    """
    Async QML image provider for all image types (JPEG, PNG, TIFF, RAW, …).

    Unlike Qt's built-in ``file://`` loading:
    - Runs on a dedicated background thread controlled by Qt's async image pool.
    - Boosts that thread to HighPriority so the OS scheduler prefers it over
      the background indexing and thumbnail workers.
    - Uses PIL's ``draft()`` mode for JPEG files: libjpeg decodes at the
      smallest subsampled resolution that still fits the display panel, giving
      up to 8× faster decode for large camera JPEGs.
    - Downsamples all formats to ``_MAX_PREVIEW_PX`` before building a QImage,
      so we never allocate a 200 MB RGBA buffer for a 50 MP full-res image.

    QML usage::

        Image { source: "image://preview/" + encodeURIComponent(filePath) }

    The provider ID is ``"preview"``.
    """

    def __init__(self) -> None:
        super().__init__(
            QQuickImageProvider.ImageType.Image,
            QQuickImageProvider.Flag.ForceAsynchronousImageLoading,
        )

    def requestImage(  # type: ignore[override]
        self, id: str, size: QSize, requestedSize: QSize
    ) -> QImage:
        # Boost the calling thread so the OS prefers it over background workers.
        QThread.currentThread().setPriority(QThread.Priority.HighPriority)

        path = urllib.parse.unquote(id)
        target = _effective_target(requestedSize)
        try:
            img = _load_image(path, target)
        except Exception:
            img = QImage()

        size.setWidth(img.width())
        size.setHeight(img.height())
        return img


# ── helpers ──────────────────────────────────────────────────────────────────


def _effective_target(requested: QSize) -> tuple[int, int]:
    """Return the decode target size, capped at _MAX_PREVIEW_PX."""
    if requested.isValid() and not requested.isEmpty():
        return (
            min(requested.width(), _MAX_PREVIEW_PX),
            min(requested.height(), _MAX_PREVIEW_PX),
        )
    return (_MAX_PREVIEW_PX, _MAX_PREVIEW_PX)


def _load_image(path: str, target: tuple[int, int]) -> QImage:
    ext = Path(path).suffix.lower()
    if ext in RAW_EXTENSIONS and _RAWPY_AVAILABLE:
        pil_img = _load_raw(path, target)
    else:
        pil_img = _load_standard(path, target)
    pil_img = pil_img.convert("RGBA")
    data = bytes(pil_img.tobytes("raw", "RGBA"))
    # .copy() detaches the QImage from the Python-owned buffer.
    return QImage(
        data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888
    ).copy()


def _load_standard(path: str, target: tuple[int, int]) -> Image.Image:
    """Load any PIL-supported format. Uses draft() for JPEG for faster decode.

    We read the raw bytes first via Python's open() so that the network I/O
    happens while the GIL is *released* (CPython's ReadFile() syscall path
    calls Py_BEGIN_ALLOW_THREADS before entering the kernel).  If we instead
    passed the path directly to PIL, its C decoders would call fp.read() via
    the Python C API without ever releasing the GIL — holding it for the full
    NAS transfer duration and freezing Qt's event loop completely.
    """
    with open(path, "rb") as f:
        data = f.read()  # GIL released during ReadFile() → Qt events flow freely
    buf = io.BytesIO(data)
    try:
        img = Image.open(buf)
    except UnidentifiedImageError:
        # Pillow 12 treats some valid-but-unusual files (e.g. 16-bit RGBA PNGs
        # with large metadata chunks) as truncated.  Retry with the flag set.
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            buf.seek(0)
            img = Image.open(buf)
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
    # draft() instructs libjpeg to decode at a subsampled resolution
    # (1/2, 1/4 or 1/8) — only effective for JPEG, no-op for other formats.
    img.draft("RGB", target)
    img.load()  # decodes from in-memory BytesIO — fast, GIL held only briefly
    img = ImageOps.exif_transpose(img)
    img.thumbnail(target, Image.LANCZOS)
    return img


def _load_raw(path: str, target: tuple[int, int]) -> Image.Image:
    """Load a RAW file via rawpy, preferring the embedded JPEG thumbnail."""
    with rawpy.imread(path) as raw:
        raw_flip = raw.sizes.flip  # orientation from the RAW file's IFD
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                img: Image.Image = Image.open(io.BytesIO(thumb.data))
                img.draft("RGB", target)
                img.load()
            else:
                img = Image.fromarray(thumb.data)
        except rawpy.LibRawNoThumbnailError:
            # No embedded preview — fall back to half-size demosaic.
            # rawpy.postprocess() applies orientation automatically.
            rgb = raw.postprocess(use_camera_wb=True, half_size=True)
            img = Image.fromarray(rgb)
            img.thumbnail(target, Image.LANCZOS)
            return img
    img = orient_raw_thumb(img, raw_flip)
    img.thumbnail(target, Image.LANCZOS)
    return img
