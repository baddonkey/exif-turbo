from __future__ import annotations

import subprocess
from pathlib import Path

from exif_turbo.models.derivative_export_flavour import (
    DerivativeFormat,
    MetadataMode,
    default_derivative_export_flavours,
)
from exif_turbo.tagging.media_conversion import DerivativeMediaConverter


class RecordingMediaConverter(DerivativeMediaConverter):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[list[str]] = []

    @staticmethod
    def _resolve_tool(explicit_path: str | None, names: tuple[str, ...]) -> str:
        return explicit_path or names[0]

    def _run_process(
        self,
        arguments: list[str],
        _cancel_check: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(arguments)
        if arguments[0] == "ffprobe":
            return subprocess.CompletedProcess(arguments, 0, "90\n", "")
        Path(arguments[-1]).write_bytes(b"converted")
        return subprocess.CompletedProcess(arguments, 0, "", "")


def test_media_converter_applies_jpeg_resize_quality_and_metadata_policy(
    tmp_path: Path,
) -> None:
    # Arrange
    source = tmp_path / "source.png"
    destination = tmp_path / "result.jpg"
    source.write_bytes(b"source")
    flavour = default_derivative_export_flavours()[1]
    converter = RecordingMediaConverter()

    # Act
    converter.convert(source, destination, flavour, MetadataMode.NONE)

    # Assert
    command = converter.commands[0]
    assert command[0] == "magick"
    assert "-auto-orient" in command
    assert command[command.index("-resize") + 1] == "2048x2048>"
    assert "-strip" in command
    assert command[command.index("-quality") + 1] == "85"
    assert destination.read_bytes() == b"converted"


def test_media_converter_applies_tiff_lzw_compression(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "source.jpg"
    destination = tmp_path / "archive.tif"
    source.write_bytes(b"source")
    flavour = default_derivative_export_flavours()[-1]
    converter = RecordingMediaConverter()

    # Act
    converter.convert(source, destination, flavour, MetadataMode.CUSTOM)

    # Assert
    command = converter.commands[0]
    assert flavour.output_format is DerivativeFormat.TIFF
    assert command[command.index("-compress") + 1] == "LZW"


def test_media_converter_extracts_one_frame_at_one_third_duration(
    tmp_path: Path,
) -> None:
    # Arrange
    source = tmp_path / "movie.mov"
    destination = tmp_path / "movie.png"
    source.write_bytes(b"video")
    flavour = default_derivative_export_flavours()[2]
    converter = RecordingMediaConverter()

    # Act
    converter.convert(source, destination, flavour, MetadataMode.NONE)

    # Assert
    assert [command[0] for command in converter.commands] == [
        "ffprobe",
        "ffmpeg",
        "magick",
    ]
    ffmpeg_command = converter.commands[1]
    assert ffmpeg_command[ffmpeg_command.index("-ss") + 1] == "30.000000"
    assert ffmpeg_command[ffmpeg_command.index("-frames:v") + 1] == "1"
    assert destination.read_bytes() == b"converted"