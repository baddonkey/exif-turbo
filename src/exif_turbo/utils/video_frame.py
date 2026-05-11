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
import struct
from typing import Any

from PIL import Image

_log = logging.getLogger(__name__)

try:
    import av as _av
    _AV_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AV_AVAILABLE = False


def _get_video_rotation(container: Any, stream: Any, path: str = "") -> int:
    """Return the clockwise rotation in degrees needed to display *stream* upright.

    Checks, in order:
    1. Stream metadata ``rotate`` tag (most containers from cameras/phones).
    2. Codec-context metadata ``rotate`` tag (some encoders put it here).
    3. Container (format) metadata.
    4. Display matrix side data (PyAV when available).
    5. QuickTime / MPEG-4 ``tkhd`` transformation matrix (parsed directly from
       the file bytes) — required for iPhone/iOS videos where PyAV does not
       surface the display matrix as ``stream.side_data``.
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

    # Try display matrix side data (PyAV when it surfaces it)
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

    # Fallback: read the QuickTime / MPEG-4 tkhd transformation matrix directly.
    # PyAV 17 does not expose stream-level side data (stream.side_data is None)
    # for many MOV/MP4 files from cameras and phones, so we parse the atoms.
    if path:
        qt_rot = _get_rotation_from_qt_atoms(path)
        if qt_rot:
            return qt_rot

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
        img = _try_embedded_thumbnail(container, target_long_edge, path)
        if img is not None:
            return img
        img = _extract_frame_at_third(container, target_long_edge, path)
        if img is not None:
            return img

    raise RuntimeError(f"No image could be extracted from {path!r}")


# ── private helpers ───────────────────────────────────────────────────────────


def _try_embedded_thumbnail(
    container: Any,
    target_long_edge: int | None,
    path: str = "",
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

    rotation = _get_video_rotation(container, best_stream, path)
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
    path: str = "",
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

    rotation = _get_video_rotation(container, stream, path)
    img: Image.Image = frame.to_image()
    img = _apply_rotation(img, rotation)
    if target_long_edge is not None:
        img.thumbnail((target_long_edge, target_long_edge), Image.LANCZOS)
    return img


# ── QuickTime / MPEG-4 atom parser ───────────────────────────────────────────


def _get_rotation_from_qt_atoms(path: str) -> int:
    """Return the CW rotation in degrees read from the first video tkhd matrix.

    Parses QuickTime / MPEG-4 container atoms directly — required for files
    (e.g. iPhone MOV) where the rotation is stored only in the track-header
    transformation matrix and PyAV does not surface it as ``stream.side_data``.

    Returns 0 for non-QT/MP4 files or if no rotation is found.
    """
    try:
        with open(path, "rb") as f:
            return _parse_qt_tkhd_rotation(f)
    except Exception:
        return 0


def _parse_qt_tkhd_rotation(f: Any) -> int:
    """Scan a seekable binary file object for the first video tkhd matrix."""

    def _read_box(limit_end: int) -> tuple[str | None, int, int]:
        pos = f.tell()
        if pos >= limit_end:
            return None, pos, pos
        raw = f.read(8)
        if len(raw) < 8:
            return None, pos, limit_end
        size_raw: int
        box_type_b: bytes
        size_raw, box_type_b = struct.unpack(">I4s", raw)
        box_type = box_type_b.decode("latin-1", errors="replace")
        if size_raw == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return None, pos, limit_end
            (size,) = struct.unpack(">Q", ext)
            content_start = pos + 16
        elif size_raw == 0:
            size = limit_end - pos
            content_start = pos + 8
        else:
            size = size_raw
            content_start = pos + 8
        return box_type, content_start, pos + size

    def _find_box(target: str, limit_end: int) -> tuple[int, int] | tuple[None, None]:
        while f.tell() < limit_end:
            box_type, content_start, box_end = _read_box(limit_end)
            if box_type is None:
                return None, None
            if box_type == target:
                return content_start, box_end
            f.seek(box_end)
        return None, None

    # File size
    f.seek(0, 2)
    file_size = f.tell()
    f.seek(0)

    moov_content, moov_end = _find_box("moov", file_size)
    if moov_content is None or moov_end is None:
        return 0

    f.seek(moov_content)

    while True:
        trak_content, trak_end = _find_box("trak", moov_end)
        if trak_content is None or trak_end is None:
            break

        f.seek(trak_content)
        tkhd_content, _ = _find_box("tkhd", trak_end)
        if tkhd_content is None:
            f.seek(trak_end)
            continue

        f.seek(tkhd_content)
        version_flags = f.read(4)
        if len(version_flags) < 4:
            f.seek(trak_end)
            continue

        # Skip fields before the 36-byte matrix.
        # version 0: creation(4)+modification(4)+trackid(4)+reserved(4)+duration(4)
        #            +reserved(8)+layer(2)+altgroup(2)+volume(2)+reserved(2) = 36
        # version 1: creation(8)+modification(8)+trackid(4)+reserved(4)+duration(8)
        #            +reserved(8)+layer(2)+altgroup(2)+volume(2)+reserved(2) = 48
        skip = 48 if version_flags[0] == 1 else 36
        f.read(skip)

        matrix_data = f.read(36)
        if len(matrix_data) < 36:
            f.seek(trak_end)
            continue

        # Matrix layout: [a, b, u, c, d, v, tx, ty, w] — nine 32-bit big-endian ints.
        # a and b are 16.16 fixed-point; determine rotation from their signs.
        vals = struct.unpack(">9i", matrix_data)
        a = vals[0] / 65536.0
        b = vals[1] / 65536.0
        eps = 0.5
        if abs(a) < eps and b > eps:
            return 90   # 90° CW (portrait from landscape sensor)
        if a < -eps and abs(b) < eps:
            return 180
        if abs(a) < eps and b < -eps:
            return 270  # 270° CW
        # Identity matrix (a≈1, b≈0) or unrecognised — try next track.

        f.seek(trak_end)

    return 0
