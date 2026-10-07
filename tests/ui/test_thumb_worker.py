from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import exif_turbo.ui.workers.thumb_worker as thumb_worker
from exif_turbo.utils.preview_render import VIPS_ROUTE_SOURCE_PX


def test_open_image_large_source_delegates_to_render_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    src = tmp_path / "pano.tif"
    src.write_bytes(b"not-a-real-image")
    expected = Image.new("RGB", (144, 72))
    calls: list[tuple[str, int, int | None]] = []

    def fake_render_preview(
        path: str, target: int, *, known_pixel_count: int | None = None
    ) -> Image.Image:
        calls.append((path, target, known_pixel_count))
        return expected

    monkeypatch.setattr(thumb_worker, "render_preview", fake_render_preview)

    # Act
    result = thumb_worker._open_image(str(src), VIPS_ROUTE_SOURCE_PX + 1)

    # Assert
    assert result is expected
    assert calls == [(str(src), 144, VIPS_ROUTE_SOURCE_PX + 1)]


def test_open_image_small_source_decodes_from_disk(tmp_path: Path) -> None:
    # Arrange
    src = tmp_path / "small.png"
    Image.new("RGB", (64, 32), "red").save(src, "PNG")

    # Act
    result = thumb_worker._open_image(str(src), 64 * 32)
    src.unlink()  # fails on Windows if the handle leaked; harmless elsewhere

    # Assert
    assert result.size == (64, 32)
    assert result.getpixel((0, 0)) == (255, 0, 0)


@pytest.mark.parametrize(
    ("filename", "module_name", "function_name", "args"),
    [
        (
            "clip.mp4",
            "exif_turbo.utils.video_frame",
            "extract_video_frame",
            lambda path: (path, 144),
        ),
        (
            "raw.cr2",
            "exif_turbo.utils.preview_render",
            "_load_raw",
            lambda path: (path, (144, 144)),
        ),
    ],
)
def test_decode_thumbnail_source_isolates_native_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    module_name: str,
    function_name: str,
    args: object,
) -> None:
    # Arrange
    path = str(tmp_path / filename)
    expected = Image.new("RGB", (20, 10))
    calls: list[tuple[object, ...]] = []

    def fake_decode(*values: object, **kwargs: object) -> Image.Image:
        calls.append(values + (kwargs["timeout_s"],))
        return expected

    monkeypatch.setattr(thumb_worker, "run_decode_process", fake_decode)
    monkeypatch.setattr(thumb_worker, "_RAWPY_AVAILABLE", True)

    # Act
    result = thumb_worker._decode_thumbnail_source(path)

    # Assert
    expected_args = args(path)  # type: ignore[operator]
    assert result is expected
    assert calls == [(module_name, function_name, expected_args, 300.0)]
