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

try:  # pragma: no cover - optional dep, tested separately
    import os as _os
    # Cap libvips's internal thread-pool to 1 before the first import so
    # concurrent _load_vips calls (preview provider async pool + build worker)
    # don't each spawn cpu_count() libvips threads, exhausting memory on large
    # TIFFs and causing a hard crash (SIGSEGV / OOM-kill) that bypasses Python
    # exception handling.  setdefault preserves any explicit user override.
    _os.environ.setdefault("VIPS_CONCURRENCY", "1")
    import pyvips as _pyvips
    # Disable the libvips operation cache entirely.  We process unique images
    # (never the same path twice in a session) so the cache buys nothing, and
    # leaving it enabled causes processed image data to accumulate across
    # sequential large-TIFF calls until the process is OOM-killed.
    _pyvips.cache_set_max(0)
    _pyvips.cache_set_max_mem(0)
    _PYVIPS_AVAILABLE = True
except (ImportError, OSError):  # pragma: no cover
    _PYVIPS_AVAILABLE = False

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from ..indexing.image_utils import RAW_EXTENSIONS, VIDEO_EXTENSIONS, orient_raw_thumb
from .video_frame import extract_video_frame

# Hard cap on any preview decode \u2014 prevents allocating a 200 MB RGBA buffer
# for a 50 MP image even if the caller passes a huge target size.
MAX_PREVIEW_PX = 4096

# Hard cap on source images we are willing to decode for previews with Pillow.
# Large panoramas and giant RAW-derived bitmaps can explode memory before the
# thumbnail step has a chance to shrink them down.  Above this threshold we
# route through libvips, which streams the source and only decodes the tiles
# needed to produce the target size.
MAX_PREVIEW_SOURCE_PX = 100_000_000


def render_preview(path: str, target_long_edge: int) -> Image.Image:
    """Decode *path* into a Pillow image sized to ``target_long_edge``.

    Caller passes the raw long-edge target (e.g. 2048).  The result will
    have ``max(width, height) <= target_long_edge`` after thumbnailing.
    """
    target_long_edge = max(1, min(target_long_edge, MAX_PREVIEW_PX))
    target = (target_long_edge, target_long_edge)
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return extract_video_frame(path, target_long_edge)
    if ext in RAW_EXTENSIONS and _RAWPY_AVAILABLE:
        return _load_raw(path, target)
    return _load_standard(path, target)


def _load_standard(path: str, target: tuple[int, int]) -> Image.Image:
    # Probe dimensions from the file header before reading pixel data.
    # For large TIFFs on a NAS this avoids pulling hundreds of MB across the
    # network just to discover the file must be routed through libvips.
    _w = _h = 0
    try:
        with Image.open(path) as _probe:
            _w, _h = _probe.width, _probe.height
    except Exception:  # noqa: BLE001 — any probe failure falls through to PIL
        pass
    if _w * _h > MAX_PREVIEW_SOURCE_PX:
        if _PYVIPS_AVAILABLE:
            return _load_vips(path, target)
        raise RuntimeError(
            f"preview source too large: {path!r} ({_w}x{_h})"
        )

    # Normal path: read into BytesIO so the codec decodes from memory
    # (CPython releases the GIL during ReadFile(), keeping Qt's event loop alive).
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


def _load_vips(path: str, target: tuple[int, int]) -> Image.Image:
    """Thumbnail *path* with libvips — memory-efficient for very large images.

    libvips streams the source, decoding only the tiles needed to produce the
    output size, so peak RAM scales with the *output* rather than the source.
    EXIF rotation is applied automatically.
    """
    vips = _pyvips.Image.thumbnail(path, target[0], height=target[1], size="down")
    if vips.hasalpha():
        vips = vips.flatten(background=[255, 255, 255])
    if vips.interpretation != "srgb":
        try:
            vips = vips.colourspace("srgb")
        except Exception:  # noqa: BLE001 — some ICC profiles are not convertible
            pass
    mode = "RGB" if vips.bands == 3 else "L"
    result = Image.frombytes(mode, (vips.width, vips.height), vips.write_to_memory())
    del vips  # release libvips image memory promptly
    return result


def _load_raw(path: str, target: tuple[int, int]) -> Image.Image:
    with rawpy.imread(path) as raw:
        raw_flip = raw.sizes.flip
        raw_pixels = int(raw.sizes.width) * int(raw.sizes.height)
        if raw_pixels > MAX_PREVIEW_SOURCE_PX:
            raise RuntimeError(
                f"preview source too large: {path!r} ({raw.sizes.width}x{raw.sizes.height})"
            )
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
