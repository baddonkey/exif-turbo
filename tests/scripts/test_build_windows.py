from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts import build_windows


def _write_exiftool_payload(staged: Path, *, include_artistic: bool = True) -> None:
    files_dir = staged / "exiftool_files"
    files_dir.mkdir(parents=True)
    (staged / "README.txt").write_text("ExifTool package", encoding="utf-8")
    (files_dir / "LICENSE").write_text("GPL terms", encoding="utf-8")
    (files_dir / "readme_windows.txt").write_text(
        "Windows package notice", encoding="utf-8"
    )
    with zipfile.ZipFile(files_dir / "Licenses_Strawberry_Perl.zip", "w") as archive:
        archive.writestr("perl/Copying", "GPL terms")
        if include_artistic:
            archive.writestr("perl/Artistic", "Artistic terms")


def test_validate_exiftool_licenses_complete_payload_succeeds(tmp_path: Path) -> None:
    # Arrange
    staged = tmp_path / "exiftool"
    _write_exiftool_payload(staged)

    # Act / Assert
    build_windows.validate_exiftool_licenses(staged)


def test_validate_exiftool_licenses_missing_artistic_terms_exits(
    tmp_path: Path,
) -> None:
    # Arrange
    staged = tmp_path / "exiftool"
    _write_exiftool_payload(staged, include_artistic=False)

    # Act / Assert
    with pytest.raises(SystemExit):
        build_windows.validate_exiftool_licenses(staged)