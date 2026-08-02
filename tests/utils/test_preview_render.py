from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from exif_turbo.utils.preview_render import (
    DEFAULT_VIPS_ALLOWED_EXTENSIONS,
    MAX_PREVIEW_PX,
    MAX_PREVIEW_SOURCE_PX,
    configure_vips_allowed_extensions,
    render_preview,
)


@pytest.fixture(autouse=True)
def default_vips_allowed_extensions() -> None:
    configure_vips_allowed_extensions(DEFAULT_VIPS_ALLOWED_EXTENSIONS)
    yield
    configure_vips_allowed_extensions(DEFAULT_VIPS_ALLOWED_EXTENSIONS)


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


def test_load_vips_disallowed_extension_rejects_before_native_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    import exif_turbo.utils.preview_render as preview_render

    src = tmp_path / "crafted.bmp"
    native_calls: list[str] = []

    class FakeVipsImage:
        @staticmethod
        def thumbnail(path: str, *_args: object, **_kwargs: object) -> None:
            native_calls.append(path)

    class FakePylibvips:
        Image = FakeVipsImage

    monkeypatch.setattr(preview_render, "_pyvips_mod", FakePylibvips())

    # Act / Assert
    with pytest.raises(RuntimeError, match="not allowed"):
        preview_render._load_vips(str(src), (128, 128))
    assert native_calls == []


def test_load_vips_user_added_extension_reaches_native_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    import exif_turbo.utils.preview_render as preview_render

    src = tmp_path / "scan.BMP"
    configure_vips_allowed_extensions(["bmp"])

    class FakeVipsResult:
        interpretation = "srgb"
        format = "uchar"
        bands = 3
        width = 1
        height = 1

        def hasalpha(self) -> bool:
            return False

        def write_to_memory(self) -> bytes:
            return b"\x10\x20\x30"

    native_calls: list[str] = []

    class FakeVipsImage:
        @staticmethod
        def thumbnail(path: str, *_args: object, **_kwargs: object) -> FakeVipsResult:
            native_calls.append(path)
            return FakeVipsResult()

    class FakePylibvips:
        Image = FakeVipsImage

    monkeypatch.setattr(preview_render, "_pyvips_mod", FakePylibvips())

    # Act
    result = preview_render._load_vips(str(src), (128, 128))

    # Assert
    assert native_calls == [str(src)]
    assert result.getpixel((0, 0)) == (16, 32, 48)


def test_ensure_pyvips_enables_untrusted_block_before_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import exif_turbo.utils.preview_render as preview_render

    class FakePylibvips:
        @staticmethod
        def version(part: int) -> int:
            return (8, 18, 4)[part]

        @staticmethod
        def cache_set_max(_value: int) -> None:
            pass

        @staticmethod
        def cache_set_max_mem(_value: int) -> None:
            pass

        @staticmethod
        def shutdown() -> None:
            pass

    fake_module = FakePylibvips()
    monkeypatch.setitem(sys.modules, "pyvips", fake_module)
    monkeypatch.setattr(preview_render, "_PYVIPS_AVAILABLE", None)
    monkeypatch.setattr(preview_render, "_pyvips_mod", None)
    monkeypatch.setattr(atexit, "register", lambda _callback: None)
    monkeypatch.setenv("VIPS_BLOCK_UNTRUSTED", "0")

    # Act
    available = preview_render._ensure_pyvips()

    # Assert
    assert available is True
    assert os.environ["VIPS_BLOCK_UNTRUSTED"] == "1"

