from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from exif_turbo.tagging.exif_metadata_writer import (
    ExifMetadataWriteError,
    ExifMetadataWriter,
)


def test_write_keywords_builds_exact_arguments_with_target_last_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "derivative.jpg"
    target.write_bytes(b"image")
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if "-json" in arguments:
            stdout = json.dumps(
                [{"XMP-dc:Subject": ["Deer", "Forests"], "IPTC:Keywords": ["Deer", "Forests"]}]
            )
        else:
            stdout = "1 image files updated"
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(
        "exif_turbo.tagging.exif_metadata_writer.find_exiftool",
        lambda: "C:/tools/exiftool.exe",
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act
    ExifMetadataWriter().write_keywords(target, ("Deer", "Forests"))

    # Assert
    assert calls == [
        [
            "C:/tools/exiftool.exe",
            "-overwrite_original",
            "-XMP-dc:Subject=",
            "-IPTC:Keywords=",
            "-XMP-dc:Subject+=Deer",
            "-IPTC:Keywords+=Deer",
            "-XMP-dc:Subject+=Forests",
            "-IPTC:Keywords+=Forests",
            str(target),
        ],
        [
            "C:/tools/exiftool.exe",
            "-json",
            "-G1",
            "-XMP-dc:Subject",
            "-IPTC:Keywords",
            str(target),
        ],
    ]


def test_write_keywords_rejects_forbidden_source_without_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    source = tmp_path / "source.jpg"
    source.write_bytes(b"original")

    def unexpected_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(subprocess, "run", unexpected_run)

    # Act / Assert
    with pytest.raises(ExifMetadataWriteError, match="source image"):
        ExifMetadataWriter().write_keywords(
            source, ("Deer",), forbidden_sources=(source,)
        )


def test_write_keywords_nonzero_exit_includes_exiftool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "derivative.jpg"
    target.write_bytes(b"image")

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 1, "", "Error: unsupported file")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act / Assert
    with pytest.raises(ExifMetadataWriteError, match="unsupported file"):
        ExifMetadataWriter().write_keywords(target, ("Deer",))