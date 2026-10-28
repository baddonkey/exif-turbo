from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from exif_turbo.tagging import media_tool_discovery


@pytest.mark.parametrize("tool", ["imagemagick", "ffmpeg", "ffprobe"])
@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_find_media_tool_missing_from_path_uses_homebrew_only_on_macos(
    tool: str,
    platform: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    tool_name = "magick" if tool == "imagemagick" else tool
    executable = tmp_path / tool_name
    executable.write_bytes(b"tool")
    executable.chmod(0o755)
    monkeypatch.setattr(media_tool_discovery.sys, "platform", platform)
    monkeypatch.setattr(media_tool_discovery.sys, "executable", str(tmp_path / "app"))
    monkeypatch.delattr(media_tool_discovery.sys, "_MEIPASS", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(
        media_tool_discovery,
        "_MACOS_MEDIA_TOOL_DIRECTORIES",
        (str(tmp_path),),
        raising=False,
    )

    # Act
    result = media_tool_discovery.find_media_tool(tool)

    # Assert
    assert result == (str(executable) if platform == "darwin" else None)


def test_find_media_tool_prefers_path_then_checks_bundle_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    bundled_directory = tmp_path / "app" / "media-tools"
    bundled_directory.mkdir(parents=True)
    bundled_magick = bundled_directory / "magick.exe"
    bundled_magick.write_bytes(b"tool")
    imagemagick_directory = bundled_directory / "imagemagick"
    imagemagick_directory.mkdir()
    nested_magick = imagemagick_directory / "magick.exe"
    nested_magick.write_bytes(b"nested tool")
    ffmpeg_directory = bundled_directory / "ffmpeg" / "bin"
    ffmpeg_directory.mkdir(parents=True)
    bundled_ffmpeg = ffmpeg_directory / "ffmpeg.exe"
    bundled_ffprobe = ffmpeg_directory / "ffprobe.exe"
    bundled_ffmpeg.write_bytes(b"tool")
    bundled_ffprobe.write_bytes(b"tool")
    monkeypatch.setattr(
        media_tool_discovery.sys,
        "executable",
        str(tmp_path / "app" / "exif-turbo.exe"),
    )
    monkeypatch.setattr(media_tool_discovery.shutil, "which", lambda _name: None)

    # Act
    bundled_result = media_tool_discovery.find_media_tool("imagemagick")
    bundled_magick.unlink()
    nested_imagemagick_result = media_tool_discovery.find_media_tool("imagemagick")
    ffmpeg_result = media_tool_discovery.find_media_tool("ffmpeg")
    ffprobe_result = media_tool_discovery.find_media_tool("ffprobe")
    monkeypatch.setattr(
        media_tool_discovery.shutil,
        "which",
        lambda name: "C:/tools/magick.exe" if name == "magick" else None,
    )
    path_result = media_tool_discovery.find_media_tool("imagemagick")

    # Assert
    assert bundled_result == str(bundled_magick)
    assert nested_imagemagick_result == str(nested_magick)
    assert ffmpeg_result == str(bundled_ffmpeg)
    assert ffprobe_result == str(bundled_ffprobe)
    assert path_result == "C:/tools/magick.exe"


def test_check_media_tools_requires_ffprobe_and_reports_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    paths = {
        "imagemagick": "magick",
        "ffmpeg": "ffmpeg",
        "ffprobe": None,
    }
    monkeypatch.setattr(
        media_tool_discovery, "find_media_tool", lambda name: paths[name]
    )

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        name = arguments[0]
        version = "ImageMagick 7" if name == "magick" else "ffmpeg version 9"
        return subprocess.CompletedProcess(arguments, 0, version, "")

    monkeypatch.setattr(media_tool_discovery.subprocess, "run", fake_run)

    # Act
    statuses = media_tool_discovery.check_media_tools()

    # Assert
    assert statuses[0]["available"] is True
    assert statuses[0]["version"] == "ImageMagick 7"
    assert statuses[1]["available"] is False
    assert statuses[1]["version"] == "ffmpeg version 9"
    assert "ffprobe" in str(statuses[1]["detail"])