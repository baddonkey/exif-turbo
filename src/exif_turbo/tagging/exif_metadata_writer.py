from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..indexing.exif_metadata_extractor import find_exiftool
from ..indexing.image_utils import VIDEO_EXTENSIONS


class ExifMetadataWriteError(RuntimeError):
    """Raised when ExifTool cannot write or verify derivative keywords."""


class ExifMetadataWriter:
    _DESCRIPTION_FIELDS = (
        "XMP-dc:Description", "IPTC:Caption-Abstract", "EXIF:ImageDescription",
        "EXIF:UserComment", "XMP-exif:UserComment", "PNG:Description",
        "QuickTime:Description",
    )

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout_seconds = timeout_seconds

    def write_description(
        self, target: Path, description: str, *, forbidden_sources: Iterable[Path] = ()
    ) -> None:
        self.discard_embedded_description(target, forbidden_sources=forbidden_sources)
        with tempfile.TemporaryDirectory(prefix="exif-turbo-description-") as directory:
            text_path = Path(directory) / "description.txt"
            text_path.write_text(description, encoding="utf-8", newline="")
            result = self._run([
                find_exiftool(), "-overwrite_original",
                f"-XMP-dc:Description<={text_path}", str(target),
            ])
        if result.returncode != 0:
            raise ExifMetadataWriteError(
                f"ExifTool description write failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        readback = self._run([
            find_exiftool(), "-json", "-G1", "-XMP-dc:Description", str(target),
        ])
        if readback.returncode != 0:
            raise ExifMetadataWriteError(
                f"ExifTool description readback failed: {readback.stderr.strip() or readback.stdout.strip()}"
            )
        try:
            records = json.loads(readback.stdout)
            if records[0].get("XMP-dc:Description") != description:
                raise ExifMetadataWriteError("description readback did not match requested text")
        except (ValueError, TypeError, IndexError, AttributeError) as exc:
            raise ExifMetadataWriteError("ExifTool returned invalid description readback") from exc

    def discard_embedded_description(
        self, target: Path, *, forbidden_sources: Iterable[Path] = ()
    ) -> None:
        if target.resolve() in {source.resolve() for source in forbidden_sources}:
            raise ExifMetadataWriteError(f"refusing to write metadata to source image: {target}")
        result = self._run([
            find_exiftool(), "-overwrite_original",
            *(f"-{field}=" for field in self._DESCRIPTION_FIELDS), str(target),
        ])
        if result.returncode != 0:
            raise ExifMetadataWriteError(
                f"ExifTool description clear failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        readback = self._run([
            find_exiftool(), "-json", "-G1", "-a",
            *(f"-{field}*" if field == "XMP-dc:Description" else f"-{field}"
              for field in self._DESCRIPTION_FIELDS), str(target),
        ])
        if readback.returncode != 0:
            raise ExifMetadataWriteError(
                f"ExifTool description readback failed: {readback.stderr.strip() or readback.stdout.strip()}"
            )
        try:
            records = json.loads(readback.stdout)
            if not isinstance(records, list) or not records or not all(
                isinstance(record, dict) for record in records
            ):
                raise ValueError("expected metadata records")
            if any(
                value not in (None, "", [])
                for record in records
                for key, value in record.items()
                if key != "SourceFile"
            ):
                raise ExifMetadataWriteError("embedded description remains after clearing")
        except (ValueError, TypeError) as exc:
            raise ExifMetadataWriteError("ExifTool returned invalid description readback") from exc

    def write_keywords(
        self,
        target: Path,
        labels: Sequence[str],
        *,
        forbidden_sources: Iterable[Path] = (),
        excluded_labels: Iterable[str] = (),
        preserve_existing_keywords: bool = True,
    ) -> None:
        resolved_target = target.resolve()
        forbidden = {source.resolve() for source in forbidden_sources}
        if resolved_target in forbidden:
            raise ExifMetadataWriteError(
                f"refusing to write metadata to source image: {target}"
            )

        fields = self._keyword_fields(target)
        current_labels = (
            self._read_keywords(target, fields) if preserve_existing_keywords else ()
        )
        excluded_keys = {label.casefold() for label in excluded_labels}
        current_labels = tuple(
            label for label in current_labels if label.casefold() not in excluded_keys
        )
        labels = self._merge_labels(labels, current_labels)
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

        if not labels:
            self._verify_keywords(target, labels, fields)
            return

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