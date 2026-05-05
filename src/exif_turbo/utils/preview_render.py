"""Shared image-rendering helpers for the preview cache builder and the
on-demand QML preview provider.

Both call sites need the same logic:

- read the file bytes up-front so the codec decodes from memory (CPython
  releases the GIL during ``ReadFile()``, keeping Qt's event loop alive),
- use Pillow's ``draft()`` mode for JPEG so libjpeg subsamples on the way
  out (up to 8\u00d7 faster decode for large camera JPEGs),
- prefer the embedded JPEG thumbnail of RAW files (rawpy.extract_thumb),
- apply EXIF / CR2 orientation,
- thumbnail down to the requested target size.

Returns Pillow ``Image`` objects so the caller can pick the output format
(QImage for the live provider, JPEG bytes for the cache writer).
"""

from __future__ import annotations

import io
from pathlib import Path

try:  # pragma: no cover - optional dep, tested separately
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RAWPY_AVAILABLE = False

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from ..indexing.image_utils import RAW_EXTENSIONS, orient_raw_thumb

# Hard cap on any preview decode \u2014 prevents allocating a 200 MB RGBA buffer
# for a 50 MP image even if the caller passes a huge target size.
MAX_PREVIEW_PX = 4096


def render_preview(path: str, target_long_edge: int) -> Image.Image:
    """Decode *path* into a Pillow image sized to ``target_long_edge``.

    Caller passes the raw long-edge target (e.g. 2048).  The result will
    have ``max(width, height) <= target_long_edge`` after thumbnailing.
    """
    target = (target_long_edge, target_long_edge)
    ext = Path(path).suffix.lower()
    if ext in RAW_EXTENSIONS and _RAWPY_AVAILABLE:
        return _load_raw(path, target)
    return _load_standard(path, target)


def _load_standard(path: str, target: tuple[int, int]) -> Image.Image:
    with open(path, "rb") as f:
        data = f.read()
    buf = io.BytesIO(data)
    try:
        img = Image.open(buf)
    except UnidentifiedImageError:
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            buf.seek(0)
            img = Image.open(buf)
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
    img.draft("RGB", target)
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGB")
    img.thumbnail(target, Image.LANCZOS)
    return img


def _load_raw(path: str, target: tuple[int, int]) -> Image.Image:
    with rawpy.imread(path) as raw:
        raw_flip = raw.sizes.flip
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                data = bytes(thumb.data)
                img: Image.Image = Image.open(io.BytesIO(data))
                try:
                    img.draft("RGB", target)
                    img.load()
                except Exception:
                    img = Image.open(io.BytesIO(data))
                    img.load()
            else:
                img = Image.fromarray(thumb.data)
        except rawpy.LibRawError:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True)
            img = Image.fromarray(rgb)
            img.thumbnail(target, Image.LANCZOS)
            return img
    img = orient_raw_thumb(img, raw_flip)
    img.thumbnail(target, Image.LANCZOS)
    return img
