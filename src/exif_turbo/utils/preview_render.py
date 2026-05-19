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
from pathlib import Path

try:  # pragma: no cover - optional dep, tested separately
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RAWPY_AVAILABLE = False

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


def render_preview(path: str, target_long_edge: int) -> Image.Image:
    """Decode *path* into a Pillow image sized to ``target_long_edge``.

    Caller passes the raw long-edge target (e.g. 2048).  The result will
    have ``max(width, height) <= target_long_edge`` after thumbnailing.
    """
    target = (target_long_edge, target_long_edge)
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return _call_with_timeout(extract_video_frame, path, target_long_edge)
    if ext in RAW_EXTENSIONS and _RAWPY_AVAILABLE:
        return _call_with_timeout(_load_raw, path, target)
    return _load_standard(path, target)


def _load_standard(path: str, target: tuple[int, int]) -> Image.Image:
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
