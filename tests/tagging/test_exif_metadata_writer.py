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
    read_count = 0

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal read_count
        calls.append(arguments)
        if "-json" in arguments:
            read_count += 1
            stdout = (
                "[{}]"
                if read_count == 1
                else json.dumps(
                    [{"XMP-dc:Subject": ["Deer", "Forests"], "IPTC:Keywords": ["Deer", "Forests"]}]
                )
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
            "-json",
            "-G1",
            "-XMP-dc:Subject",
            "-IPTC:Keywords",
            str(target),
        ],
        [
            "C:/tools/exiftool.exe",
            "-m",
            "-overwrite_original",
            "-XMP-dc:Subject=",
            "-IPTC:Keywords=",
            str(target),
        ],
        [
            "C:/tools/exiftool.exe",
            "-m",
            "-overwrite_original",
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


def test_write_keywords_excluded_existing_labels_are_not_merged_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "derivative.jpg"
    target.write_bytes(b"image")
    written_arguments: list[str] = []
    read_count = 0

    def fake_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal read_count, written_arguments
        if "-json" in arguments:
            read_count += 1
            labels = ["Added", "Keep", "Private"] if read_count == 1 else ["Added", "Keep"]
            stdout = json.dumps(
                [{"XMP-dc:Subject": labels, "IPTC:Keywords": labels}]
            )
        else:
            if any(argument.startswith("-XMP-dc:Subject+=") for argument in arguments):
                written_arguments = arguments
            stdout = "1 image files updated"
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(
        "exif_turbo.tagging.exif_metadata_writer.find_exiftool",
        lambda: "C:/tools/exiftool.exe",
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act
    ExifMetadataWriter().write_keywords(
        target,
        ("Added",),
        excluded_labels=("private",),
    )

    # Assert
    assert "-XMP-dc:Subject+=Keep" in written_arguments
    assert "-XMP-dc:Subject+=Private" not in written_arguments


def test_write_keywords_mp4_writes_and_verifies_xmp_and_windows_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "derivative.mp4"
    target.write_bytes(b"video")
    calls: list[list[str]] = []

    def fake_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        stdout = (
            json.dumps(
                [
                    {
                        "XMP-dc:Subject": "Katzenpfote",
                        "Microsoft:Category": "Katzenpfote",
                    }
                ]
            )
            if "-json" in arguments
            else "1 image files updated"
        )
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(
        "exif_turbo.tagging.exif_metadata_writer.find_exiftool",
        lambda: "C:/tools/exiftool.exe",
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act
    ExifMetadataWriter().write_keywords(target, ("Katzenpfote",))

    # Assert
    assert calls == [
        [
            "C:/tools/exiftool.exe",
            "-json",
            "-G1",
            "-XMP-dc:Subject",
            "-Microsoft:Category",
            str(target),
        ],
        [
            "C:/tools/exiftool.exe",
            "-m",
            "-overwrite_original",
            "-XMP-dc:Subject=",
            "-Microsoft:Category=",
            str(target),
        ],
        [
            "C:/tools/exiftool.exe",
            "-m",
            "-overwrite_original",
            "-XMP-dc:Subject+=Katzenpfote",
            "-Microsoft:Category+=Katzenpfote",
            str(target),
        ],
        [
            "C:/tools/exiftool.exe",
            "-json",
            "-G1",
            "-XMP-dc:Subject",
            "-Microsoft:Category",
            str(target),
        ],
    ]


def test_write_keywords_merges_live_existing_keywords_case_insensitively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "derivative.jpg"
    target.write_bytes(b"image")
    calls: list[list[str]] = []
    read_count = 0

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal read_count
        calls.append(arguments)
        if "-json" not in arguments:
            return subprocess.CompletedProcess(arguments, 0, "updated", "")
        read_count += 1
        labels = ["Family", "New tag"] if read_count == 1 else ["family", "New tag"]
        return subprocess.CompletedProcess(
            arguments,
            0,
            json.dumps([{"XMP-dc:Subject": labels, "IPTC:Keywords": labels}]),
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act
    ExifMetadataWriter().write_keywords(target, ("family",))

    # Assert
    write_arguments = calls[2]
    assert "-XMP-dc:Subject+=family" in write_arguments
    assert "-XMP-dc:Subject+=New tag" in write_arguments
    assert "-XMP-dc:Subject+=Family" not in write_arguments


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