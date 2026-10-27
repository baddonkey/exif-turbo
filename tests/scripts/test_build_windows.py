from __future__ import annotations

import json
import zipfile
import hashlib
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import build_windows


def test_windows_installer_media_features_separate_tools_and_licenses() -> None:
    # Arrange
    source = Path(__file__).resolve().parents[2] / "installer/exif-turbo.wxs"
    namespace = {"wix": "http://wixtoolset.org/schemas/v4/wxs"}
    package = ET.parse(source).getroot().find("wix:Package", namespace)
    assert package is not None

    # Act
    features = {
        feature.attrib["Id"]: feature
        for feature in package.findall("wix:Feature", namespace)
    }

    # Assert
    assert "MediaToolsFeature" not in features
    for feature_id, title, folder in (
        ("FFmpegFeature", "FFmpeg", "ffmpeg"),
        ("ImageMagickFeature", "ImageMagick", "imagemagick"),
    ):
        feature = features[feature_id]
        assert feature.attrib["Title"] == title
        assert feature.attrib["Level"] == "1"
        assert feature.attrib["InstallDefault"] == "local"
        assert feature.attrib["AllowAdvertise"] == "no"
        assert {
            harvest.attrib["Include"]
            for harvest in feature.findall("wix:Files", namespace)
        } == {
            f"$(var.MediaToolsDir)\\{folder}\\**",
            f"$(var.MediaToolsDir)\\licenses\\{title}-*",
        }
    assert any(
        harvest.attrib["Include"] == "$(var.MediaToolsDir)\\MEDIA-TOOLS.json"
        for harvest in features["MainFeature"].findall("wix:Files", namespace)
    )


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


def _write_media_tools_payload(staged: Path, *, include_ffprobe: bool = True) -> None:
    (staged / "imagemagick").mkdir(parents=True)
    (staged / "imagemagick" / "magick.exe").write_bytes(b"magick")
    ffmpeg_bin = staged / "ffmpeg" / "bin"
    ffmpeg_bin.mkdir(parents=True)
    (ffmpeg_bin / "ffmpeg.exe").write_bytes(b"ffmpeg")
    if include_ffprobe:
        (ffmpeg_bin / "ffprobe.exe").write_bytes(b"ffprobe")
    (ffmpeg_bin / "avcodec-63.dll").write_bytes(b"avcodec")
    licenses = staged / "licenses"
    licenses.mkdir()
    for name in (
        "ImageMagick-LICENSE.txt",
        "ImageMagick-SBOM.cdx.json",
        "ImageMagick-VERSION.txt",
        "FFmpeg-BUILD-CHECKSUMS.sha256",
        "FFmpeg-LGPL-2.1.txt",
        "FFmpeg-BUILDS-LICENSE.txt",
        "FFmpeg-BUILDS-README.md",
        "FFmpeg-BUILDS-SOURCE.zip",
        "FFmpeg-VERSION.txt",
        "FFmpeg-SOURCE.tar.gz",
        "FFmpeg-SOURCE-MANIFEST.txt",
    ):
        (licenses / name).write_bytes(b"license or source")
    (licenses / "ImageMagick-LICENSE.txt").write_text(
        "ImageMagick License", encoding="utf-8"
    )
    (licenses / "ImageMagick-VERSION.txt").write_text(
        f"Version: ImageMagick {build_windows._IMAGEMAGICK_VERSION}\n",
        encoding="utf-8",
    )
    (licenses / "FFmpeg-BUILD-CHECKSUMS.sha256").write_text(
        build_windows._FFMPEG_ARCHIVE_SHA256, encoding="ascii"
    )
    (licenses / "FFmpeg-LGPL-2.1.txt").write_text(
        "GNU Lesser General Public License", encoding="utf-8"
    )
    (licenses / "FFmpeg-VERSION.txt").write_text(
        "ffmpeg version n9.0.2-gabcdef configuration: --enable-shared",
        encoding="utf-8",
    )
    (staged / "MEDIA-TOOLS.json").write_text(
        json.dumps(
            {
                "layout_version": build_windows._MEDIA_TOOLS_LAYOUT_VERSION,
                "imagemagick_version": build_windows._IMAGEMAGICK_VERSION,
                "imagemagick_archive_sha256": build_windows._IMAGEMAGICK_ARCHIVE_SHA256,
                "ffmpeg_archive_sha256": build_windows._FFMPEG_ARCHIVE_SHA256,
            }
        ),
        encoding="utf-8",
    )


def test_validate_media_tools_complete_payload_succeeds(tmp_path: Path) -> None:
    # Arrange
    staged = tmp_path / "media-tools"
    _write_media_tools_payload(staged)

    # Act / Assert
    build_windows.validate_media_tools(staged)


def test_validate_media_tools_missing_ffprobe_exits(tmp_path: Path) -> None:
    # Arrange
    staged = tmp_path / "media-tools"
    _write_media_tools_payload(staged, include_ffprobe=False)

    # Act / Assert
    with pytest.raises(SystemExit):
        build_windows.validate_media_tools(staged)


def test_download_verified_rejects_unexpected_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    data = b"pinned archive bytes"

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            if size == -1:
                return data
            chunk, remaining[:] = remaining[:size], remaining[size:]
            return chunk

    remaining = bytearray(data)
    monkeypatch.setattr(
        build_windows.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    destination = tmp_path / "archive.zip"

    # Act / Assert
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_windows._download_verified(
            "https://example.invalid/archive.zip",
            destination,
            hashlib.sha256(b"different archive").hexdigest(),
        )
    assert destination.read_bytes() == data


def test_extract_7z_archive_checks_members_before_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    archive_path = tmp_path / "imagemagick.7z"
    destination = tmp_path / "extracted"
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[1] == "l":
            output = (
                f"Path = {archive_path}\nType = 7z\n----------\n"
                "Path = root/magick.exe\nSize = 1\nAttributes = A\n"
            )
            return subprocess.CompletedProcess(arguments, 0, output, "")
        output_path = Path(next(argument[2:] for argument in arguments if argument.startswith("-o")))
        (output_path / "root").mkdir()
        (output_path / "root" / "magick.exe").write_bytes(b"magick")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(build_windows.subprocess, "run", fake_run)

    # Act
    build_windows._extract_7z_archive(archive_path, destination, seven_zip="7z.exe")

    # Assert
    assert len(calls) == 2
    assert (destination / "root" / "magick.exe").read_bytes() == b"magick"


def test_extract_7z_archive_rejects_traversal_before_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    archive_path = tmp_path / "imagemagick.7z"
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        output = (
            f"Path = {archive_path}\nType = 7z\n----------\n"
            "Path = ..\\escape.exe\nSize = 1\nAttributes = A\n"
        )
        return subprocess.CompletedProcess(arguments, 0, output, "")

    monkeypatch.setattr(build_windows.subprocess, "run", fake_run)

    # Act / Assert
    with pytest.raises(ValueError, match="unsafe archive member path"):
        build_windows._extract_7z_archive(
            archive_path, tmp_path / "extracted", seven_zip="7z.exe"
        )
    assert len(calls) == 1


def test_extract_ffmpeg_archive_copies_release_contents_to_expected_layout(
    tmp_path: Path,
) -> None:
    # Arrange
    archive_path = tmp_path / "ffmpeg.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("release/bin/ffmpeg.exe", b"ffmpeg")
        archive.writestr("release/bin/ffprobe.exe", b"ffprobe")
        archive.writestr("release/bin/avcodec-63.dll", b"codec")
        archive.writestr("release/LICENSE.txt", b"license")
    destination = tmp_path / "staged" / "ffmpeg"

    # Act
    build_windows._extract_ffmpeg_archive(archive_path, destination)

    # Assert
    assert (destination / "bin" / "ffmpeg.exe").read_bytes() == b"ffmpeg"
    assert (destination / "bin" / "ffprobe.exe").read_bytes() == b"ffprobe"
    assert (destination / "bin" / "avcodec-63.dll").read_bytes() == b"codec"
    assert (destination / "LICENSE.txt").read_bytes() == b"license"


def test_extract_ffmpeg_archive_rejects_path_traversal(tmp_path: Path) -> None:
    # Arrange
    archive_path = tmp_path / "ffmpeg.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("release/bin/ffmpeg.exe", b"ffmpeg")
        archive.writestr("release/bin/ffprobe.exe", b"ffprobe")
        archive.writestr("release/../../escape.txt", b"escape")

    # Act / Assert
    with pytest.raises(ValueError, match="unsafe archive member path"):
        build_windows._extract_ffmpeg_archive(archive_path, tmp_path / "staged")