from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..indexing.exif_metadata_extractor import find_exiftool
from ..indexing.image_utils import VIDEO_EXTENSIONS


class ExifMetadataWriteError(RuntimeError):
    """Raised when ExifTool cannot write or verify derivative keywords."""


class ExifMetadataWriter:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout_seconds = timeout_seconds

    def write_keywords(
        self,
        target: Path,
        labels: Sequence[str],
        *,
        forbidden_sources: Iterable[Path] = (),
    ) -> None:
        resolved_target = target.resolve()
        forbidden = {source.resolve() for source in forbidden_sources}
        if resolved_target in forbidden:
            raise ExifMetadataWriteError(
                f"refusing to write metadata to source image: {target}"
            )

        fields = self._keyword_fields(target)
        labels = self._merge_labels(labels, self._read_keywords(target, fields))
        clear_arguments = [
            find_exiftool(),
            "-m",
            "-overwrite_original",
        ]
        clear_arguments.extend(f"-{field}=" for field in fields)
        clear_arguments.append(str(target))
        clear_result = self._run(clear_arguments)
        if clear_result.returncode != 0:
            detail = (
                clear_result.stderr.strip()
                or clear_result.stdout.strip()
                or "unknown error"
            )
            raise ExifMetadataWriteError(f"ExifTool metadata clear failed: {detail}")

        arguments = [find_exiftool(), "-m", "-overwrite_original"]
        for label in labels:
            arguments.extend(f"-{field}+={label}" for field in fields)
        arguments.append(str(target))
        result = self._run(arguments)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise ExifMetadataWriteError(f"ExifTool metadata write failed: {detail}")
        self._verify_keywords(target, labels, fields)

    def _read_keywords(
        self, target: Path, fields: tuple[str, ...]
    ) -> tuple[str, ...]:
        result = self._run(
            [
                find_exiftool(),
                "-json",
                "-G1",
                *(f"-{field}" for field in fields),
                str(target),
            ]
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise ExifMetadataWriteError(f"ExifTool metadata read failed: {detail}")
        try:
            record = json.loads(result.stdout)[0]
            return self._merge_labels(
                *(self._as_labels(record.get(field)) for field in fields)
            )
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExifMetadataWriteError(
                "ExifTool returned invalid metadata"
            ) from exc

    def _verify_keywords(
        self, target: Path, labels: Sequence[str], fields: tuple[str, ...]
    ) -> None:
        result = self._run(
            [
                find_exiftool(),
                "-json",
                "-G1",
                *(f"-{field}" for field in fields),
                str(target),
            ]
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise ExifMetadataWriteError(f"ExifTool metadata readback failed: {detail}")
        try:
            records = json.loads(result.stdout)
            record = records[0]
            actual = tuple(self._as_labels(record.get(field)) for field in fields)
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExifMetadataWriteError(
                "ExifTool returned invalid metadata readback"
            ) from exc
        expected = tuple(labels)
        if any(values != expected for values in actual):
            raise ExifMetadataWriteError(
                "ExifTool metadata readback did not match requested labels"
            )

    @staticmethod
    def _keyword_fields(target: Path) -> tuple[str, ...]:
        if target.suffix.lower() in VIDEO_EXTENSIONS:
            return ("XMP-dc:Subject", "Microsoft:Category")
        return ("XMP-dc:Subject", "IPTC:Keywords")

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        platform_arguments: dict[str, Any] = (
            {"creationflags": 0x08000000}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        try:
            return subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=self._timeout_seconds,
                **platform_arguments,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExifMetadataWriteError(f"unable to run ExifTool: {exc}") from exc

    @staticmethod
    def _as_labels(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return tuple(value)
        return ()

    @staticmethod
    def _merge_labels(*groups: Sequence[str]) -> tuple[str, ...]:
        labels_by_key: dict[str, str] = {}
        for group in groups:
            for value in group:
                label = value.strip()
                if label:
                    labels_by_key.setdefault(label.casefold(), label)
        return tuple(
            sorted(
                labels_by_key.values(),
                key=lambda label: (label.casefold(), label),
            )
        )