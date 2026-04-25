from __future__ import annotations

from pathlib import Path

import pytest

from exif_turbo.indexing.image_utils import IMAGE_EXTENSIONS, RAW_EXTENSIONS, is_image_file


def test_is_image_file_jpg_returns_true(tmp_path: Path) -> None:
    assert is_image_file(tmp_path / "photo.jpg") is True


def test_is_image_file_jpeg_returns_true(tmp_path: Path) -> None:
    assert is_image_file(tmp_path / "photo.jpeg") is True


def test_is_image_file_png_returns_true(tmp_path: Path) -> None:
    assert is_image_file(tmp_path / "image.png") is True


def test_is_image_file_txt_returns_false(tmp_path: Path) -> None:
    assert is_image_file(tmp_path / "readme.txt") is False


def test_is_image_file_no_extension_returns_false(tmp_path: Path) -> None:
    assert is_image_file(tmp_path / "noext") is False


def test_is_image_file_case_insensitive_jpg(tmp_path: Path) -> None:
    assert is_image_file(tmp_path / "PHOTO.JPG") is True


def test_is_image_file_raw_cr2_returns_true(tmp_path: Path) -> None:
    assert is_image_file(tmp_path / "shot.cr2") is True


def test_is_image_file_raw_nef_returns_true(tmp_path: Path) -> None:
    assert is_image_file(tmp_path / "shot.nef") is True


def test_raw_extensions_is_subset_of_image_extensions() -> None:
    assert RAW_EXTENSIONS.issubset(IMAGE_EXTENSIONS)


def test_raw_extensions_does_not_include_jpeg() -> None:
    assert ".jpg" not in RAW_EXTENSIONS
    assert ".jpeg" not in RAW_EXTENSIONS
    assert ".png" not in RAW_EXTENSIONS
