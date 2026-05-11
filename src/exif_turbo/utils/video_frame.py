"""Extract a representative frame from a video file using PyAV (FFmpeg).

Strategy (in priority order):
1. Use the highest-resolution embedded thumbnail / cover-art stream
   (disposition attached_pic) when one exists — this is the camera's own
   processed image and is available instantly without seeking.
2. Fall back to decoding a frame at 1/3 of the video duration.

Returns a Pillow RGB Image.  Raises ``RuntimeError`` if extraction fails or
PyAV is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

from PIL import Image

_log = logging.getLogger(__name__)

try:
    import av as _av
    _AV_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AV_AVAILABLE = False


def _get_video_rotation(container: Any, stream: Any) -> int:
    """Return the clockwise rotation in degrees needed to display *stream* upright.

    Checks, in order:
    1. Stream metadata ``rotate`` tag (most containers from cameras/phones).
    2. Codec-context metadata ``rotate`` tag (some encoders put it here).
    3. Container (format) metadata.
    4. Display matrix side data (PyAV ≥†12 on streams that carry one).
    """
    for meta in (
        getattr(stream, "metadata", None),
        getattr(getattr(stream, "codec_context", None), "metadata", None),
        getattr(container, "metadata", None),
    ):
        if not meta:
            continue
        raw = meta.get("rotate")
        if raw is not None:
            try:
                deg = int(float(raw)) % 360
                if deg:
                    return deg
            except (TypeError, ValueError):
                pass

    # Try display matrix side data (PyAV ≥ 12)
    side_data = getattr(stream, "side_data", None)
    if side_data is not None:
        dm = side_data.get("DISPLAYMATRIX") if hasattr(side_data, "get") else None
        if dm is not None:
            rot = getattr(dm, "rotation", None)
            if rot is not None:
                try:
                    # Display matrix rotation is CCW; negate to get CW convention.
                    cw = (-int(rot)) % 360
                    if cw:
                        return cw
                except (TypeError, ValueError):
                    pass

    return 0


def _apply_rotation(img: Image.Image, rotation: int) -> Image.Image:
    """Rotate *img* clockwise by *rotation* degrees (0/90/180/270)."""
    rotation = rotation % 360
    if rotation == 90:
        return img.transpose(Image.Transpose.ROTATE_270)
    if rotation == 180:
        return img.transpose(Image.Transpose.ROTATE_180)
    if rotation == 270:
        return img.transpose(Image.Transpose.ROTATE_90)
    return img


def _is_attached_pic(stream: Any) -> bool:
    """Return True if *stream* carries an embedded thumbnail / cover art.

    PyAV exposes ``stream.disposition`` as a ``Disposition`` flags object —
    attribute access is the portable way to test individual flags.
    """
    disp = getattr(stream, "disposition", None)
    if disp is None:
        return False
    # PyAV ≥ 12 exposes individual flags as boolean attributes.
    attached = getattr(disp, "attached_pic", None)
    if attached is not None:
        return bool(attached)
    # Older builds may expose it as a plain int; fall back to bitwise test.
    try:
        return bool(int(disp) & 0x0400)
    except (TypeError, ValueError):
        return False


def is_av_available() -> bool:
    """Return True if PyAV (FFmpeg) is importable."""
    return _AV_AVAILABLE


def extract_video_frame(
    path: str,
    target_long_edge: int | None = None,
) -> Image.Image:
    """Return a Pillow RGB image representing *path*.

    Tries embedded thumbnail streams first (e.g. cover art in MP4/MOV files
    from cameras).  Falls back to decoding a frame at 1/3 of the video
    duration when no embedded thumbnail is present.

    Parameters
    ----------
    path:
        Absolute path to the video file.
    target_long_edge:
        When given, the returned image is thumbnailed to fit within a square
        of this size.  Pass ``None`` to get full resolution.

    Raises
    ------
    RuntimeError
        If PyAV is not installed or no image can be produced.
    """
    if not _AV_AVAILABLE:
        raise RuntimeError("PyAV is not installed; cannot decode video frames")

    with _av.open(path) as container:
        img = _try_embedded_thumbnail(container, target_long_edge)
        if img is not None:
            return img
        img = _extract_frame_at_third(container, target_long_edge)
        if img is not None:
            return img

    raise RuntimeError(f"No image could be extracted from {path!r}")


# ── private helpers ───────────────────────────────────────────────────────────


def _try_embedded_thumbnail(
    container: Any,
    target_long_edge: int | None,
) -> Image.Image | None:
    """Return the highest-resolution embedded thumbnail, or ``None``.

    Cameras and editing tools often embed cover-art / thumbnail streams
    (disposition ATTACHED_PIC).  When multiple such streams exist we pick
    the one with the most pixels so the preview is as sharp as possible.
    """
    best_stream = None
    best_pixels = -1

    for stream in container.streams.video:
        if _is_attached_pic(stream):
            pixels = (stream.width or 0) * (stream.height or 0)
            if pixels > best_pixels:
                best_pixels = pixels
                best_stream = stream

    if best_stream is None:
        return None

    rotation = _get_video_rotation(container, best_stream)
    try:
        for packet in container.demux(best_stream):
            for frame in packet.decode():
                img: Image.Image = frame.to_image()
                img = _apply_rotation(img, rotation)
                if target_long_edge is not None:
                    img.thumbnail(
                        (target_long_edge, target_long_edge), Image.LANCZOS
                    )
                return img
    except _av.AVError as exc:
        _log.debug("Embedded thumbnail decode failed: %s", exc)

    return None


def _extract_frame_at_third(
    container: Any,
    target_long_edge: int | None,
) -> Image.Image | None:
    """Seek to 1/3 of the video duration and decode the nearest key frame.

    Only considers real video streams (not attached-picture streams).
    """
    # Real video streams only — skip any ATTACHED_PIC streams.
    real_streams = [
        s for s in container.streams.video
        if not _is_attached_pic(s)
    ]
    if not real_streams:
        return None

    stream = real_streams[0]
    stream.codec_context.skip_frame = "NONKEY"  # key frames only for fast seek

    # Determine total duration in seconds.
    if container.duration and container.duration > 0:
        duration_s = container.duration / _av.time_base
    elif stream.duration and stream.time_base:
        duration_s = float(stream.duration * stream.time_base)
    else:
        duration_s = 0.0

    seek_s = duration_s / 3.0 if duration_s > 0 else 0.0
    seek_ts = int(seek_s / _av.time_base)

    try:
        container.seek(seek_ts, any_frame=False, backward=True)
    except _av.AVError:
        try:
            container.seek(0)
        except _av.AVError:
            return None

    frame = None
    for packet in container.demux(stream):
        try:
            for decoded in packet.decode():
                frame = decoded
                break
        except _av.AVError as exc:
            _log.debug("Frame decode error: %s", exc)
            continue
        if frame is not None:
            break

    if frame is None:
        return None

    rotation = _get_video_rotation(container, stream)
    img: Image.Image = frame.to_image()
    img = _apply_rotation(img, rotation)
    if target_long_edge is not None:
        img.thumbnail((target_long_edge, target_long_edge), Image.LANCZOS)
    return img
