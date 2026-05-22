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
import logging
import threading
import warnings
from pathlib import Path

# Pillow emits UserWarning for malformed EXIF fields in TIFF files
# (e.g. "Corrupt EXIF data. Expecting to read 12 bytes but only got 6").
# The image still decodes correctly — suppress the noise.
warnings.filterwarnings(
    "ignore",
    message="Corrupt EXIF data",
    category=UserWarning,
    module=r"PIL\.TiffImagePlugin",
)

try:  # pragma: no cover - optional dep, tested separately
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RAWPY_AVAILABLE = False

# pyvips is initialised lazily — only when a >100 MP image is first encountered.
# Eager initialisation at module-import time starts libvips's internal thread pool
# before Qt's event loop is established, which triggers a GLib/Qt conflict on
# macOS: a libvips thread calls abort() during Qt event processing (observed in
# the test runner and in practice on macOS arm64 with pyvips-binary).
_pyvips_mod = None  # type: ignore[assignment]  — set by _ensure_pyvips()
_PYVIPS_AVAILABLE: bool | None = None  # None = not yet probed
_pyvips_lock = threading.Lock()


def _ensure_pyvips() -> bool:  # pragma: no cover — tested via integration path
    """Initialise pyvips on first use; return True if available."""
    global _pyvips_mod, _PYVIPS_AVAILABLE
    if _PYVIPS_AVAILABLE is not None:
        return _PYVIPS_AVAILABLE
    with _pyvips_lock:
        if _PYVIPS_AVAILABLE is not None:  # re-check under lock
            return _PYVIPS_AVAILABLE
        try:
            import os as _os
            # Cap libvips's internal thread-pool to 1 so concurrent _load_vips
            # calls don't each spawn cpu_count() threads, exhausting memory on
            # large TIFFs.  setdefault preserves any explicit user override.
            _os.environ.setdefault("VIPS_CONCURRENCY", "1")
            import pyvips as _mod
            # Disable the operation cache.  We process unique images (never the
            # same path twice in a session) so the cache buys nothing, and
            # leaving it enabled causes processed image data to accumulate
            # across sequential large-TIFF calls until the process is OOM-killed.
            _mod.cache_set_max(0)
            _mod.cache_set_max_mem(0)
            # Register a shutdown hook so libvips cleans up its worker threads
            # before the process exits.  Without this, libvips threads can still
            # be running during Python's interpreter shutdown, causing a segfault
            # (SIGSEGV) in the process teardown path.
            import atexit as _atexit
            _atexit.register(_mod.shutdown)
            _pyvips_mod = _mod
            _PYVIPS_AVAILABLE = True
        except (ImportError, OSError):
            _PYVIPS_AVAILABLE = False
    return bool(_PYVIPS_AVAILABLE)

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from ..indexing.image_utils import RAW_EXTENSIONS, VIDEO_EXTENSIONS, orient_raw_thumb
from .video_frame import extract_video_frame

_log = logging.getLogger(__name__)

# Hard cap on any preview decode \u2014 prevents allocating a 200 MB RGBA buffer
# for a 50 MP image even if the caller passes a huge target size.
MAX_PREVIEW_PX = 4096
# Per-file timeout for native-library decode calls (rawpy / PyAV).  These are
# C-level blocking calls that cannot be interrupted by Python.  Running them in
# a daemon thread lets the worker abandon a stuck file and move on; the leaked
# thread is a daemon and will not prevent process exit.
# 300 s is generous enough for a 2 GB RAW file on a slow NAS (~20 MB/s) while
# still releasing the worker if libraw / FFmpeg loops forever on corrupt data.
_DECODE_TIMEOUT_S = 300.0

# Lock for the LOAD_TRUNCATED_IMAGES global so concurrent workers don't race
# on the set → reset sequence in _load_standard().
_TRUNCATED_LOCK = threading.Lock()


def _call_with_timeout(fn, *args, timeout_s: float = _DECODE_TIMEOUT_S):  # type: ignore[no-untyped-def]
    """Run *fn*(*args*) in a daemon thread; raise ``TimeoutError`` if it does
    not finish within *timeout_s* seconds.

    The stuck thread is leaked on timeout.  It is a daemon thread so it will
    not prevent the process from exiting.
    """
    result: list = []
    error: list[BaseException] = []

    def _run() -> None:
        try:
            result.append(fn(*args))
        except Exception as exc:  # noqa: BLE001
            error.append(exc)

    t = threading.Thread(target=_run, daemon=True, name=f"decode-timeout-{fn.__name__}")
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError(
            f"Decode of {args[0]!r} timed out after {timeout_s:.0f} s"
        )
    if error:
        raise error[0]
    return result[0]

# Hard cap on source images we are willing to decode for previews with Pillow.
# Large panoramas and giant RAW-derived bitmaps can explode memory before the
# thumbnail step has a chance to shrink them down.  Above this threshold we
# route through libvips, which streams the source and only decodes the tiles
# needed to produce the target size.
MAX_PREVIEW_SOURCE_PX = 100_000_000


def render_preview(
    path: str,
    target_long_edge: int,
    *,
    known_pixel_count: int | None = None,
) -> Image.Image:
    """Decode *path* into a Pillow image sized to ``target_long_edge``.

    Caller passes the raw long-edge target (e.g. 2048).  The result will
    have ``max(width, height) <= target_long_edge`` after thumbnailing.

    *known_pixel_count* — when provided (e.g. from the DB-stored exiftool
    metadata), the file-header probe is skipped so no extra I/O is needed
    to decide whether to route through libvips.
    """
    target_long_edge = max(1, min(target_long_edge, MAX_PREVIEW_PX))
    target = (target_long_edge, target_long_edge)
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return _call_with_timeout(extract_video_frame, path, target_long_edge)
    if ext in RAW_EXTENSIONS and _RAWPY_AVAILABLE:
        return _call_with_timeout(_load_raw, path, target)
    return _load_standard(path, target, known_pixel_count=known_pixel_count)


def _load_standard(
    path: str,
    target: tuple[int, int],
    *,
    known_pixel_count: int | None = None,
) -> Image.Image:
    # Use the DB-stored exiftool pixel count when available so the file
    # header does not need to be read twice (once here and once by the
    # calling worker's own probe).  Fall back to the live Image.open probe
    # when no metadata is available (e.g. on-demand provider calls).
    _probe_failed = False
    if known_pixel_count is not None:
        pixel_count = known_pixel_count
    else:
        # Probe dimensions from the file header before reading pixel data.
        # For large TIFFs on a NAS this avoids pulling hundreds of MB across
        # the network just to discover the file must be routed through libvips.
        _w = _h = 0
        try:
            with Image.open(path) as _probe:
                _w, _h = _probe.width, _probe.height
        except Exception:  # noqa: BLE001 — probe failure → try pyvips below
            _probe_failed = True
        pixel_count = _w * _h
    if pixel_count > MAX_PREVIEW_SOURCE_PX or _probe_failed:
        if _ensure_pyvips():
            return _load_vips(path, target)
        if pixel_count > MAX_PREVIEW_SOURCE_PX:
            raise RuntimeError(
                f"preview source too large: {path!r} ({pixel_count} px)"
            )
        # probe failed and pyvips unavailable — fall through to PIL attempt

    # Normal path: read into BytesIO so the codec decodes from memory
    # (CPython releases the GIL during ReadFile(), keeping Qt's event loop alive).
    with open(path, "rb") as f:
        data = f.read()
    buf = io.BytesIO(data)
    try:
        img = Image.open(buf)
    except UnidentifiedImageError:
        with _TRUNCATED_LOCK:
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
    vips = _pyvips_mod.Image.thumbnail(path, target[0], height=target[1], size="down")
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
