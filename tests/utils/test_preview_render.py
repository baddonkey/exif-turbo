from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from exif_turbo.utils.decode_process import DecodeTimeoutError, run_decode_process
from exif_turbo.utils.preview_render import (
    DEFAULT_VIPS_ALLOWED_EXTENSIONS,
    MAX_PREVIEW_PX,
    MAX_PREVIEW_SOURCE_PX,
    configure_vips_allowed_extensions,
    render_preview,
)


def test_run_decode_process_image_roundtrip_preserves_pixels() -> None:
    # Act
    image = run_decode_process(
        "PIL.Image", "new", ("RGB", (4, 3), (10, 20, 30)), timeout_s=10
    )

    # Assert
    assert image.size == (4, 3)
    assert image.getpixel((0, 0)) == (10, 20, 30)


def test_run_decode_process_timeout_terminates_child() -> None:
    # Act / Assert
    with pytest.raises(DecodeTimeoutError) as exc_info:
        run_decode_process("time", "sleep", (30,), timeout_s=0.2)

    assert not exc_info.value.process_is_alive


def test_run_decode_process_preserves_filesystem_error_type(tmp_path: Path) -> None:
    # Arrange
    missing_path = str(tmp_path / "missing.bin")

    # Act / Assert
    with pytest.raises(FileNotFoundError):
        run_decode_process(
            "builtins", "open", (missing_path, "rb"), timeout_s=10
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


def test_render_preview_video_uses_decode_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    import exif_turbo.utils.preview_render as preview_render

    path = tmp_path / "video.mp4"
    expected = Image.new("RGB", (20, 10))
    calls: list[tuple[object, ...]] = []

    def fake_decode(*args: object, **kwargs: object) -> Image.Image:
        calls.append(args + (kwargs["timeout_s"],))
        return expected

    monkeypatch.setattr(preview_render, "run_decode_process", fake_decode)

    # Act
    result = render_preview(str(path), 128)

    # Assert
    assert result is expected
    assert calls == [
        (
            "exif_turbo.utils.video_frame",
            "extract_video_frame",
            (str(path), 128),
            300.0,
        )
    ]


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



def test_render_preview_mid_size_allowed_extension_uses_vips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    import exif_turbo.utils.preview_render as preview_render

    src = tmp_path / "pano.tif"
    src.write_bytes(b"not-a-real-image")
    expected = Image.new("RGB", (128, 64))
    vips_calls: list[str] = []

    def fake_load_vips(path: str, _target: tuple[int, int]) -> Image.Image:
        vips_calls.append(path)
        return expected

    monkeypatch.setattr(preview_render, "_PYVIPS_AVAILABLE", True)
    monkeypatch.setattr(preview_render, "_load_vips", fake_load_vips)

    # Act
    result = render_preview(
        str(src), 128, known_pixel_count=preview_render.VIPS_ROUTE_SOURCE_PX + 1
    )

    # Assert
    assert vips_calls == [str(src)]
    assert result is expected


def test_render_preview_mid_size_disallowed_extension_uses_pillow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    import exif_turbo.utils.preview_render as preview_render

    src = tmp_path / "scan.bmp"
    Image.new("RGB", (40, 20), "blue").save(src, "BMP")

    def fail_load_vips(*_args: object) -> Image.Image:
        raise AssertionError("libvips must not be used for disallowed extensions")

    monkeypatch.setattr(preview_render, "_PYVIPS_AVAILABLE", True)
    monkeypatch.setattr(preview_render, "_load_vips", fail_load_vips)

    # Act
    result = render_preview(
        str(src), 128, known_pixel_count=preview_render.VIPS_ROUTE_SOURCE_PX + 1
    )

    # Assert
    assert result.size == (40, 20)


def test_render_preview_mid_size_vips_failure_falls_back_to_pillow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    import exif_turbo.utils.preview_render as preview_render

    src = tmp_path / "photo.png"
    Image.new("RGB", (40, 20), "green").save(src, "PNG")

    def broken_load_vips(*_args: object) -> Image.Image:
        raise RuntimeError("libvips loader blocked")

    monkeypatch.setattr(preview_render, "_PYVIPS_AVAILABLE", True)
    monkeypatch.setattr(preview_render, "_load_vips", broken_load_vips)

    # Act
    result = render_preview(
        str(src), 128, known_pixel_count=preview_render.VIPS_ROUTE_SOURCE_PX + 1
    )

    # Assert
    assert result.size == (40, 20)
    assert result.getpixel((0, 0)) == (0, 128, 0)


def test_render_preview_small_image_decodes_with_pillow_and_closes_file(
    tmp_path: Path,
) -> None:
    # Arrange
    src = tmp_path / "small.png"
    Image.new("RGB", (300, 150), "red").save(src, "PNG")

    # Act
    result = render_preview(str(src), 100)
    src.unlink()  # fails on Windows if the handle leaked; harmless elsewhere

    # Assert
    assert result.size == (100, 50)
    assert result.getpixel((0, 0)) == (255, 0, 0)
