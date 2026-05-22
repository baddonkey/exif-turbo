from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from exif_turbo.utils.preview_render import MAX_PREVIEW_PX, MAX_PREVIEW_SOURCE_PX, render_preview


def test_render_preview_clamps_requested_target_to_max_preview_px(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (32, 24), "red").save(src, "JPEG")
    seen_sizes: list[tuple[int, int]] = []
    original_thumbnail = Image.Image.thumbnail

    def spy_thumbnail(self: Image.Image, size: tuple[int, int], *args: object, **kwargs: object) -> None:
        seen_sizes.append(size)
        original_thumbnail(self, size, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "thumbnail", spy_thumbnail, raising=True)

    # Act
    image = render_preview(str(src), MAX_PREVIEW_PX * 4)

    # Assert
    assert image.size == (32, 24)
    assert seen_sizes == [(MAX_PREVIEW_PX, MAX_PREVIEW_PX)]


def test_render_preview_rejects_oversized_source_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    src = tmp_path / "huge.jpg"
    src.write_bytes(b"not-a-real-image")

    class FakeImage:
        width = MAX_PREVIEW_SOURCE_PX + 1
        height = 1
        mode = "RGB"

        def __enter__(self) -> FakeImage:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def draft(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("draft() should not be called for oversized images")

        def load(self) -> None:
            raise AssertionError("load() should not be called for oversized images")

        def convert(self, _mode: str) -> FakeImage:
            return self

        def thumbnail(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("thumbnail() should not be called for oversized images")

    monkeypatch.setattr("exif_turbo.utils.preview_render._PYVIPS_AVAILABLE", False)
    monkeypatch.setattr("exif_turbo.utils.preview_render.Image.open", lambda _buf: FakeImage())

    # Act / Assert
    with pytest.raises(RuntimeError, match="preview source too large"):
        render_preview(str(src), 128)


def test_render_preview_uses_vips_for_oversized_source_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    src = tmp_path / "huge.tiff"
    src.write_bytes(b"not-a-real-image")

    class _FakeImg:
        width = MAX_PREVIEW_SOURCE_PX + 1
        height = 1
        mode = "RGB"

        def __enter__(self) -> _FakeImg:
            return self

        def __exit__(self, *_: object) -> None:
            pass

    vips_calls: list[str] = []
    expected = Image.new("RGB", (128, 96))

    def _fake_load_vips(path: str, target: tuple[int, int]) -> Image.Image:
        vips_calls.append(path)
        return expected

    import exif_turbo.utils.preview_render as _mod

    monkeypatch.setattr(_mod, "_PYVIPS_AVAILABLE", True)
    monkeypatch.setattr(_mod, "_load_vips", _fake_load_vips)
    monkeypatch.setattr("exif_turbo.utils.preview_render.Image.open", lambda _buf: _FakeImg())

    # Act
    result = render_preview(str(src), 128)

    # Assert
    assert vips_calls == [str(src)]
    assert result is expected

