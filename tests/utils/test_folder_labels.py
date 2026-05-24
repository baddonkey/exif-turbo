"""Tests for friendly folder labels (drive roots, POSIX root, normal dirs)."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from exif_turbo.utils.folder_labels import friendly_folder_label


class TestFriendlyFolderLabel:
    def test_empty_path_returns_empty_string(self) -> None:
        assert friendly_folder_label("") == ""

    def test_normal_folder_returns_basename(self) -> None:
        if sys.platform == "win32":
            assert friendly_folder_label(r"C:\Users\stefan\Pictures") == "Pictures"
        else:
            assert friendly_folder_label("/home/stefan/Pictures") == "Pictures"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
    def test_posix_root_returns_slash(self) -> None:
        assert friendly_folder_label("/") == "/"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_windows_drive_root_with_label_returns_label_and_letter(self) -> None:
        with patch(
            "exif_turbo.utils.folder_labels._windows_volume_label",
            return_value="OS",
        ):
            assert friendly_folder_label("C:\\") == "OS (C:)"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_windows_drive_root_without_label_returns_drive_root(self) -> None:
        with patch(
            "exif_turbo.utils.folder_labels._windows_volume_label",
            return_value="",
        ):
            assert friendly_folder_label("D:\\") == "D:\\"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_windows_drive_root_forward_slash_normalises(self) -> None:
        with patch(
            "exif_turbo.utils.folder_labels._windows_volume_label",
            return_value="",
        ):
            assert friendly_folder_label("E:/") == "E:\\"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_windows_drive_root_no_separator_treated_as_root(self) -> None:
        with patch(
            "exif_turbo.utils.folder_labels._windows_volume_label",
            return_value="Data",
        ):
            assert friendly_folder_label("F:") == "Data (F:)"
