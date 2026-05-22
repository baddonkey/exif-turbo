from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Any


def _decode_in_child(path: str, target: int, conn: Any) -> None:
    """Run the actual PyAV decode in a fresh interpreter.

    PyAV pulls in libavformat / libavcodec which conflict with the FFmpeg
    bundled inside QtWebEngine.  When both end up in the same process (as
    happens when UI tests have already initialised WebEngine in this pytest
    session) the duplicate libav state causes non-deterministic ``abort()``
    crashes.  Running the decode in a spawn-context subprocess avoids the
    shared-state collision.
    """
    try:
        from exif_turbo.utils.video_frame import extract_video_frame

        image = extract_video_frame(path, target_long_edge=target)
        conn.send(("ok", image.mode, image.size))
    except BaseException as exc:  # noqa: BLE001
        conn.send(("error", type(exc).__name__, str(exc)))
    finally:
        conn.close()


def test_extract_video_frame_webm_sample_returns_thumbnail_sized_image() -> None:
    # Arrange
    video_path = Path("tests/sample-data/Swiss_silk_Manufaktur_Bolligen_Video.webm")
    assert video_path.exists(), f"Missing test asset: {video_path}"

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_decode_in_child,
        args=(str(video_path), 256, child_conn),
    )

    # Act
    proc.start()
    child_conn.close()  # parent doesn't write
    result = parent_conn.recv()
    proc.join(timeout=60)

    # Assert
    assert result[0] == "ok", f"Child process failed: {result}"
    _, mode, size = result
    assert mode == "RGB"
    assert max(size) == 256
