"""Shared image-rendering helpers for the preview cache builder and the
on-demand QML preview provider.

Both call sites need the same logic:

- stream the file from disk (no full in-memory copy) and route large
  sources through libvips, which shrinks on load,
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
import re
import threading
import warnings
from collections.abc import Iterable
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

# pyvips is initialised lazily — only when a large image is first encountered.
# Eager initialisation at module-import time starts libvips's internal thread pool
# before Qt's event loop is established, which triggers a GLib/Qt conflict on
# macOS: a libvips thread calls abort() during Qt event processing (observed in
# the test runner and in practice on macOS arm64 with pyvips-binary).
_pyvips_mod = None  # type: ignore[assignment]  — set by _ensure_pyvips()
_PYVIPS_AVAILABLE: bool | None = None  # None = not yet probed
_pyvips_lock = threading.Lock()
# Holds the os.add_dll_directory cookie on Windows/PyInstaller so that the
# _internal/ directory stays in the DLL search path for the process lifetime.
_vips_dll_dir: object = None

DEFAULT_VIPS_ALLOWED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".gif",
)
_vips_allowed_extensions = frozenset(DEFAULT_VIPS_ALLOWED_EXTENSIONS)
_EXTENSION_RE = re.compile(r"^\.[a-z0-9][a-z0-9+-]*$")


def normalize_vips_extension(extension: str) -> str | None:
    """Return a normalized file extension, or ``None`` when invalid."""
    normalized = extension.strip().lower()
    if normalized and not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized if _EXTENSION_RE.fullmatch(normalized) else None


def configure_vips_allowed_extensions(extensions: Iterable[str]) -> None:
    """Replace the extensions permitted to reach the native libvips loader."""
    global _vips_allowed_extensions
    _vips_allowed_extensions = frozenset(
        normalized
        for extension in extensions
        if (normalized := normalize_vips_extension(extension)) is not None
    )


def _vips_extension_allowed(path: str) -> bool:
    return Path(path).suffix.lower() in _vips_allowed_extensions


def _ensure_pyvips() -> bool:  # pragma: no cover — tested via integration path
    """Initialise pyvips on first use; return True if available."""
    global _pyvips_mod, _PYVIPS_AVAILABLE, _vips_dll_dir
    if _PYVIPS_AVAILABLE is not None:
        return _PYVIPS_AVAILABLE
    with _pyvips_lock:
        if _PYVIPS_AVAILABLE is not None:  # re-check under lock
            return _PYVIPS_AVAILABLE
        try:
            import sys as _sys
            import os as _os
            # On Windows (Python 3.8+), SetDefaultDllDirectories restricts the
            # DLL search path.  When PyInstaller bundles the app the _internal/
            # directory is NOT automatically in the Windows DLL search path for
            # extension-module dependencies.  Explicitly add it so that loading
            # _libvips.pyd can find libvips-42-*.dll from _internal/.
            # We store the cookie in a module-level variable so that it is not
            # garbage-collected (GC would remove the directory from the path).
            if hasattr(_sys, "_MEIPASS") and hasattr(_os, "add_dll_directory"):
                _vips_dll_dir = _os.add_dll_directory(_sys._MEIPASS)
            # Cap libvips's internal thread-pool to 1 so concurrent _load_vips
            # calls don't each spawn cpu_count() threads, exhausting memory on
            # large TIFFs.  setdefault preserves any explicit user override.
            _os.environ.setdefault("VIPS_CONCURRENCY", "1")
            # libvips 8.13+ marks insufficiently fuzzed operations as untrusted.
            # This must be set before import because libvips reads it while
            # initialising. It is mandatory even when users expand the extension
            # allowlist below: extensions are not a reliable content-type check.
            _os.environ["VIPS_BLOCK_UNTRUSTED"] = "1"
            import pyvips as _mod
            if tuple(_mod.version(part) for part in range(2)) < (8, 13):
                raise ImportError("libvips 8.13 or newer is required")
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
from .decode_process import run_decode_process

_log = logging.getLogger(__name__)

# Hard cap on any preview decode \u2014 prevents allocating a 200 MB RGBA buffer
# for a 50 MP image even if the caller passes a huge target size.
MAX_PREVIEW_PX = 4096
# Per-file timeout for native-library decode calls (rawpy / PyAV).
_DECODE_TIMEOUT_S = 300.0

# Lock for the LOAD_TRUNCATED_IMAGES global so concurrent workers don't race
# on the set → reset sequence in _load_standard().
_TRUNCATED_LOCK = threading.Lock()


# Hard cap on source images we are willing to decode for previews with Pillow.
# Large panoramas and giant RAW-derived bitmaps can explode memory before the
# thumbnail step has a chance to shrink them down.  Above this threshold we
# route through libvips, which streams the source and only decodes the tiles
# needed to produce the target size.
MAX_PREVIEW_SOURCE_PX = 100_000_000
# Sources above this size are decoded with libvips (when the extension is
# allowed) instead of Pillow.  Pillow decodes every source pixel before
# downscaling — a 90 MP 16-bit TIFF needs ~0.5 GB per worker — whereas
# libvips shrinks on load.  Below MAX_PREVIEW_SOURCE_PX, Pillow remains the
# fallback when libvips is unavailable, not allowed, or fails.
VIPS_ROUTE_SOURCE_PX = 24_000_000


def _should_route_to_vips(path: str, pixel_count: int) -> bool:
    return (
        pixel_count > VIPS_ROUTE_SOURCE_PX
        and _vips_extension_allowed(path)
        and _ensure_pyvips()
    )


def _try_load_vips(path: str, target: tuple[int, int]) -> Image.Image | None:
    """Return a libvips thumbnail, or ``None`` so the caller can use Pillow."""
    try:
        return _load_vips(path, target)
    except Exception:  # noqa: BLE001 — Pillow fallback handles the file
        _log.debug("libvips decode failed for %r — falling back to Pillow", path, exc_info=True)
        return None


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
        return run_decode_process(
            "exif_turbo.utils.video_frame",
            "extract_video_frame",
            (path, target_long_edge),
            timeout_s=_DECODE_TIMEOUT_S,
        )
    if ext in RAW_EXTENSIONS and _RAWPY_AVAILABLE:
        return run_decode_process(
            "exif_turbo.utils.preview_render",
            "_load_raw",
            (path, target),
            timeout_s=_DECODE_TIMEOUT_S,
        )
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
    elif _should_route_to_vips(path, pixel_count):
        vips_img = _try_load_vips(path, target)
        if vips_img is not None:
            return vips_img

    # Stream from an open file handle rather than copying the whole file into
    # memory first.  A file object (not a path) also keeps Pillow from
    # memory-mapping the source, which would SIGBUS if a removable drive
    # disappears mid-decode.
    with open(path, "rb") as fh:
        try:
            img = Image.open(fh)
        except UnidentifiedImageError:
            with _TRUNCATED_LOCK:
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                try:
                    fh.seek(0)
                    img = Image.open(fh)
                finally:
                    ImageFile.LOAD_TRUNCATED_IMAGES = False
        # Check mode before draft/load: draft("RGB") silently corrupts I;16 and
        # similar non-standard modes, making them appear as "RGB" after load()
        # with incorrect pixel values.  Route to pyvips while we still know the
        # real mode.
        if img.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
            _log.debug("Non-standard Pillow mode %r for %r — retrying with pyvips", img.mode, path)
            if _ensure_pyvips():
                return _load_vips(path, target)
            img = img.convert("RGB")  # pyvips unavailable — best-effort fallback
        img.draft("RGB", target)
        with warnings.catch_warnings(record=True) as _decode_warnings:
            warnings.simplefilter("always")
            img.load()
        if any("code not yet in table" in str(w.message) for w in _decode_warnings):
            # Pillow encountered a TIFF compression codec it doesn't support
            # (e.g. old-style JPEG-in-TIFF, codec 6).  It returns blank/white
            # pixel data instead of raising — fall back to pyvips (libtiff).
            _log.debug("Pillow TIFF unsupported codec (%r) — retrying with pyvips", path)
            if _ensure_pyvips():
                return _load_vips(path, target)
    img = ImageOps.exif_transpose(img)
    img.thumbnail(target, Image.LANCZOS)
    return img


def _load_vips(path: str, target: tuple[int, int]) -> Image.Image:
    """Thumbnail *path* with libvips — memory-efficient for very large images.

    libvips streams the source, decoding only the tiles needed to produce the
    output size, so peak RAM scales with the *output* rather than the source.
    EXIF rotation is applied automatically.
    """
    if not _vips_extension_allowed(path):
        raise RuntimeError(
            f"libvips loading is not allowed for extension {Path(path).suffix!r}"
        )
    vips = _pyvips_mod.Image.thumbnail(path, target[0], height=target[1], size="down")
    if vips.hasalpha():
        vips = vips.flatten(background=[255, 255, 255])
    if vips.interpretation != "srgb":
        try:
            vips = vips.colourspace("srgb")
        except Exception:  # noqa: BLE001 — some ICC profiles are not convertible
            pass
    # HDR and wide-gamut sources may produce float/16-bit output even after
    # colourspace("srgb").  Cast to uint8 so Image.frombytes() gets the right
    # byte width per pixel (float32 would be misinterpreted as uint8 otherwise).
    if vips.format != "uchar":
        vips = vips.cast("uchar")
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
