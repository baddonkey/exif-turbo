from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Sequence

from ..indexing.image_utils import VIDEO_EXTENSIONS
from ..models.derivative_export_flavour import (
    DerivativeExportFlavour,
    DerivativeFormat,
    MetadataMode,
    ResizeMode,
    TiffCompression,
)
from .media_tool_discovery import find_media_tool


class MediaConversionError(RuntimeError):
    pass


class MediaConversionCanceled(MediaConversionError):
    pass


CancelCheck = Callable[[], bool]


class DerivativeMediaConverter:
    def __init__(
        self,
        *,
        imagemagick_path: str | None = None,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        timeout_s: float = 300.0,
    ) -> None:
        self._imagemagick_path = imagemagick_path
        self._ffmpeg_path = ffmpeg_path
        self._ffprobe_path = ffprobe_path
        self._timeout_s = timeout_s

    def convert(
        self,
        source: Path,
        destination: Path,
        flavour: DerivativeExportFlavour,
        metadata_mode: MetadataMode,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> None:
        if flavour.output_format is DerivativeFormat.ORIGINAL:
            raise MediaConversionError("Original (as is) does not use a converter")
        if self._is_video(source):
            with tempfile.TemporaryDirectory(prefix="exif-turbo-frame-") as directory:
                frame = Path(directory) / "frame.png"
                self._extract_video_frame(source, frame, cancel_check)
                self._convert_image(frame, destination, flavour, metadata_mode, cancel_check)
            return
        self._convert_image(source, destination, flavour, metadata_mode, cancel_check)

    @staticmethod
    def _is_video(source: Path) -> bool:
        return source.suffix.lower() in VIDEO_EXTENSIONS

    def _extract_video_frame(
        self,
        source: Path,
        destination: Path,
        cancel_check: CancelCheck | None,
    ) -> None:
        ffprobe = self._resolve_tool(self._ffprobe_path, ("ffprobe", "ffprobe.exe"))
        ffmpeg = self._resolve_tool(self._ffmpeg_path, ("ffmpeg", "ffmpeg.exe"))
        probe = self._run_process(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            cancel_check,
        )
        try:
            duration = float(probe.stdout.strip())
        except ValueError:
            duration = 0.0
        seek = max(0.0, duration / 3.0)
        self._run_process(
            [
                ffmpeg,
                "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{seek:.6f}",
                "-i", str(source),
                "-map", "0:v:0",
                "-frames:v", "1",
                str(destination),
            ],
            cancel_check,
        )
        if not destination.is_file() or destination.stat().st_size == 0:
            raise MediaConversionError("FFmpeg did not produce a video frame")

    def _convert_image(
        self,
        source: Path,
        destination: Path,
        flavour: DerivativeExportFlavour,
        metadata_mode: MetadataMode,
        cancel_check: CancelCheck | None,
    ) -> None:
        imagemagick = self._resolve_tool(
            self._imagemagick_path, ("magick", "magick.exe")
        )
        arguments = [imagemagick, str(source), "-auto-orient"]
        if flavour.resize_mode is not ResizeMode.ORIGINAL_PIXELS:
            limit = flavour.pixel_limit
            if limit is None:
                raise MediaConversionError("resize mode requires a pixel limit")
            resize = {
                ResizeMode.LONGEST_EDGE: f"{limit}x{limit}",
                ResizeMode.WIDTH: f"{limit}x",
                ResizeMode.HEIGHT: f"x{limit}",
            }[flavour.resize_mode]
            if flavour.no_upscale:
                resize += ">"
            arguments.extend(("-resize", resize))
        if metadata_mode is MetadataMode.NONE:
            arguments.append("-strip")
        if flavour.dpi is not None and metadata_mode is not MetadataMode.NONE:
            arguments.extend(("-units", "PixelsPerInch", "-density", str(flavour.dpi)))
        if flavour.output_format is DerivativeFormat.JPEG:
            arguments.extend(("-background", "white", "-alpha", "remove", "-alpha", "off"))
            arguments.extend(("-quality", str(flavour.jpeg_quality)))
        elif flavour.output_format is DerivativeFormat.PNG:
            arguments.extend(("-define", f"png:compression-level={flavour.png_compression}"))
        elif flavour.output_format is DerivativeFormat.TIFF:
            compression = {
                TiffCompression.NONE: "None",
                TiffCompression.LZW: "LZW",
                TiffCompression.ZIP: "Zip",
            }[flavour.tiff_compression]
            arguments.extend(("-compress", compression))
        arguments.append(str(destination))
        self._run_process(arguments, cancel_check)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise MediaConversionError("ImageMagick did not produce an output image")

    @staticmethod
    def _resolve_tool(explicit_path: str | None, names: Sequence[str]) -> str:
        if explicit_path:
            return explicit_path
        key = names[0].removesuffix(".exe")
        if key == "magick":
            found = find_media_tool("imagemagick")
        elif key in {"ffmpeg", "ffprobe"}:
            found = find_media_tool(key)
        else:
            found = None
        if found:
            return found
        raise MediaConversionError(f"required media tool not found: {names[0]}")

    def _run_process(
        self,
        arguments: list[str],
        cancel_check: CancelCheck | None,
    ) -> subprocess.CompletedProcess[str]:
        creation_options: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            creation_options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            creation_options["start_new_session"] = True

        try:
            process = subprocess.Popen(arguments, **creation_options)  # type: ignore[arg-type]
        except OSError as exc:
            raise MediaConversionError(f"could not start {Path(arguments[0]).name}: {exc}") from exc

        started = time.monotonic()
        while True:
            if cancel_check is not None and cancel_check():
                process.kill()
                stdout, stderr = process.communicate()
                raise MediaConversionCanceled("media conversion canceled")
            if time.monotonic() - started > self._timeout_s:
                process.kill()
                _stdout, stderr = process.communicate()
                raise MediaConversionError(
                    f"{Path(arguments[0]).name} timed out after {self._timeout_s:g} seconds: "
                    f"{stderr.strip()}"
                )
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue

        result = subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise MediaConversionError(
                f"{Path(arguments[0]).name} failed ({result.returncode}): {detail}"
            )
        return result