from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
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


def test_discard_description_clears_all_supported_fields_and_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    target = tmp_path / "copy.jpg"
    target.write_bytes(b"copy")
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, '[{"SourceFile":"copy.jpg"}]' if "-json" in arguments else "updated", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("exif_turbo.tagging.exif_metadata_writer.find_exiftool", lambda: "exiftool")

    # Act
    ExifMetadataWriter().discard_embedded_description(target)

    # Assert
    assert "-XMP-dc:Description=" in calls[0]
    assert "-IPTC:Caption-Abstract=" in calls[0]
    assert "-EXIF:ImageDescription=" in calls[0]
    assert calls[0][-1] == str(target)
    assert "-json" in calls[1]


def test_discard_description_refuses_source_and_reports_failed_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    target = tmp_path / "photo.jpg"
    target.write_bytes(b"image")

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, '[{"XMP-dc:Description":"Still present"}]', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("exif_turbo.tagging.exif_metadata_writer.find_exiftool", lambda: "exiftool")
    writer = ExifMetadataWriter()

    # Act / Assert
    with pytest.raises(ExifMetadataWriteError, match="source image"):
        writer.discard_embedded_description(target, forbidden_sources=[target])
    with pytest.raises(ExifMetadataWriteError, match="remains"):
        writer.discard_embedded_description(target)


def test_discard_description_real_exiftool_removes_multilingual_description(tmp_path: Path) -> None:
    # Arrange
    from PIL import Image
    from exif_turbo.indexing.exif_metadata_extractor import find_exiftool, is_exiftool_available

    if not is_exiftool_available():
        pytest.skip("ExifTool is required for the metadata integration test")
    target = tmp_path / "copy.jpg"
    Image.new("RGB", (8, 8)).save(target)
    executable = find_exiftool()
    subprocess.run([
        executable, "-overwrite_original", "-XMP-dc:Description=Default caption",
        "-XMP-dc:Description-de=German caption", "-IPTC:Caption-Abstract=Caption",
        "-EXIF:ImageDescription=Description", "-EXIF:UserComment=Comment",
        str(target),
    ], check=True, capture_output=True)

    # Act
    ExifMetadataWriter().discard_embedded_description(target)

    # Assert
    result = subprocess.run([
        executable, "-json", "-G1", "-XMP-dc:Description*", "-IPTC:Caption-Abstract",
        "-EXIF:ImageDescription", "-EXIF:UserComment", str(target),
    ], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [{"SourceFile": str(target).replace("\\", "/")}]


def test_write_description_real_exiftool_matches_multiline_unicode(tmp_path: Path) -> None:
    # Arrange
    from PIL import Image
    from exif_turbo.indexing.exif_metadata_extractor import find_exiftool, is_exiftool_available

    if not is_exiftool_available():
        pytest.skip("ExifTool is required for the metadata integration test")
    target = tmp_path / "copy.jpg"
    Image.new("RGB", (8, 8)).save(target)
    text = "Embedded caption\n\nCustom caf\u00e9 caption"

    # Act
    ExifMetadataWriter().write_description(target, text)

    # Assert
    result = subprocess.run([
        find_exiftool(), "-json", "-G1", "-XMP-dc:Description",
        "-IPTC:Caption-Abstract", "-IFD0:XPComment", str(target),
    ], check=True, capture_output=True, text=True, encoding="utf-8")
    record = json.loads(result.stdout)[0]
    assert record["XMP-dc:Description"] == text
    assert record["IPTC:Caption-Abstract"] == text
    assert record["IFD0:XPComment"] == text


def test_write_description_can_skip_xpcomment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "copy.jpg"
    target.write_bytes(b"image")
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if "-json" in arguments:
            if "-XMP-dc:Description" in arguments:
                stdout = json.dumps(
                    [{
                        "XMP-dc:Description": "Caption",
                        "IPTC:Caption-Abstract": "Caption",
                    }]
                )
            else:
                stdout = json.dumps([{"SourceFile": str(target)}])
            return subprocess.CompletedProcess(arguments, 0, stdout, "")
        return subprocess.CompletedProcess(arguments, 0, "updated", "")

    monkeypatch.setattr(
        "exif_turbo.tagging.exif_metadata_writer.find_exiftool", lambda: "exiftool"
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act
    ExifMetadataWriter(write_description_to_xpcomment=False).write_description(
        target, "Caption"
    )

    # Assert
    assert not any(
        argument.startswith("-IFD0:XPComment<=")
        for call in calls
        for argument in call
    )
    assert any("-IFD0:XPComment=" in call for call in calls)


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


@pytest.mark.parametrize("preserve_existing", [False, True])
def test_write_keywords_empty_labels_clears_and_verifies_without_empty_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preserve_existing: bool
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
            labels = ["Private"] if preserve_existing and read_count == 1 else []
            stdout = json.dumps([{"XMP-dc:Subject": labels, "IPTC:Keywords": labels}])
        else:
            assert "-XMP-dc:Subject=" in arguments
            assert "-IPTC:Keywords=" in arguments
            stdout = "1 image files updated"
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(
        "exif_turbo.tagging.exif_metadata_writer.find_exiftool", lambda: "exiftool"
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act
    ExifMetadataWriter().write_keywords(
        target, (), excluded_labels=("Private",),
        preserve_existing_keywords=preserve_existing,
    )

    # Assert
    assert len(calls) == (3 if preserve_existing else 2)
    assert "-json" in calls[-1]


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


def test_write_keywords_readback_mismatch_reports_field_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "derivative.jpg"
    target.write_bytes(b"image")
    read_count = 0

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal read_count
        if "-json" in arguments:
            read_count += 1
            metadata = (
                {"XMP-dc:Subject": [], "IPTC:Keywords": []}
                if read_count == 1
                else {"XMP-dc:Subject": "Deer", "IPTC:Keywords": []}
            )
            return subprocess.CompletedProcess(arguments, 0, json.dumps([metadata]), "")
        return subprocess.CompletedProcess(arguments, 0, "updated", "")

    monkeypatch.setattr(
        "exif_turbo.tagging.exif_metadata_writer.find_exiftool", lambda: "exiftool"
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act / Assert
    with pytest.raises(ExifMetadataWriteError) as error:
        ExifMetadataWriter().write_keywords(target, ("Deer",))

    assert "IPTC:Keywords: expected ('Deer',), got ()" in str(error.value)


def test_write_keywords_real_exiftool_stores_xmp_subject_as_rdf_bag(
    tmp_path: Path,
) -> None:
    # Arrange
    from PIL import Image
    from exif_turbo.indexing.exif_metadata_extractor import find_exiftool, is_exiftool_available

    if not is_exiftool_available():
        pytest.skip("ExifTool is required for the metadata integration test")
    target = tmp_path / "derivative.jpg"
    Image.new("RGB", (8, 8)).save(target)

    # Act
    ExifMetadataWriter().write_keywords(target, ("HTMC", "USGS"))
    ExifMetadataWriter().write_keywords(target, ("HTMC", "USGS"))

    # Assert
    result = subprocess.run(
        [find_exiftool(), "-json", "-G1", "-a", "-s", "-Keywords", str(target)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    record = json.loads(result.stdout)[0]
    assert record["IPTC:Keywords"] == ["HTMC", "USGS"]
    xmp_result = subprocess.run(
        [find_exiftool(), "-b", "-XMP", str(target)],
        check=True,
        capture_output=True,
    )
    root = ET.fromstring(xmp_result.stdout)
    namespaces = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    }
    bag = root.find(".//dc:subject/rdf:Bag", namespaces)
    assert bag is not None
    assert [item.text for item in bag.findall("rdf:li", namespaces)] == [
        "HTMC",
        "USGS",
    ]


def test_write_keywords_real_exiftool_preserves_unicode_labels(
    tmp_path: Path,
) -> None:
    # Arrange
    from PIL import Image
    from exif_turbo.indexing.exif_metadata_extractor import find_exiftool, is_exiftool_available

    if not is_exiftool_available():
        pytest.skip("ExifTool is required for the metadata integration test")
    target = tmp_path / "unicode-keywords.jpg"
    Image.new("RGB", (8, 8)).save(target)
    subprocess.run(
        [
            find_exiftool(), "-overwrite_original",
            "-IPTC:Caption-Abstract=Existing caption", str(target),
        ],
        check=True,
        capture_output=True,
    )
    labels = ("'Ōhi'a lehua", "Halemaʻumaʻu")

    # Act
    ExifMetadataWriter().write_keywords(target, labels)

    # Assert
    result = subprocess.run(
        [
            find_exiftool(), "-json", "-G1", "-a", "-s",
                "-Subject", "-Keywords", "-IPTC:Caption-Abstract",
                "-IPTC:CodedCharacterSet", str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    record = json.loads(result.stdout)[0]
    assert record["XMP-dc:Subject"] == ["'Ōhi'a lehua", "Halemaʻumaʻu"]
    assert record["IPTC:Keywords"] == ["'Ōhi'a lehua", "Halemaʻumaʻu"]
    assert record["IPTC:Caption-Abstract"] == "Existing caption"
    assert record["IPTC:CodedCharacterSet"] == "UTF8"


def test_write_description_real_exiftool_preserves_unicode_in_iptc_caption(
    tmp_path: Path,
) -> None:
    # Arrange
    from PIL import Image
    from exif_turbo.indexing.exif_metadata_extractor import find_exiftool, is_exiftool_available

    if not is_exiftool_available():
        pytest.skip("ExifTool is required for the metadata integration test")
    target = tmp_path / "unicode-caption.jpg"
    Image.new("RGB", (8, 8)).save(target)
    description = "Ōhi'a lehua; Halemaʻumaʻu"

    # Act
    ExifMetadataWriter().write_description(target, description)

    # Assert
    result = subprocess.run(
        [
            find_exiftool(), "-json", "-G1", "-XMP-dc:Description",
            "-IPTC:Caption-Abstract", "-IPTC:CodedCharacterSet", str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    record = json.loads(result.stdout)[0]
    assert record["XMP-dc:Description"] == description
    assert record["IPTC:Caption-Abstract"] == description
    assert record["IPTC:CodedCharacterSet"] == "UTF8"


def test_normalize_nonstandard_xmp_app1_header_replaces_only_header(
    tmp_path: Path,
) -> None:
    # Arrange
    target = tmp_path / "photo.jpg"
    payload = ExifMetadataWriter._NONSTANDARD_XMP_APP1_HEADER + b"<x:xmpmeta/>"
    segment_length = (len(payload) + 2).to_bytes(2, "big")
    target.write_bytes(b"\xff\xd8\xff\xe1" + segment_length + payload + b"\xff\xda")

    # Act
    ExifMetadataWriter._normalize_nonstandard_xmp_app1_header(target)

    # Assert
    expected_payload = ExifMetadataWriter._STANDARD_XMP_APP1_HEADER + b"<x:xmpmeta/>"
    assert target.read_bytes() == (
        b"\xff\xd8\xff\xe1"
        + segment_length
        + expected_payload
        + b"\xff\xda"
    )


def test_write_keywords_auto_repair_disabled_leaves_xmp_header_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "photo.jpg"
    payload = ExifMetadataWriter._NONSTANDARD_XMP_APP1_HEADER + b"<x:xmpmeta/>"
    segment_length = (len(payload) + 2).to_bytes(2, "big")
    original = b"\xff\xd8\xff\xe1" + segment_length + payload + b"\xff\xda"
    target.write_bytes(original)
    read_count = 0

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal read_count
        if "-json" in arguments:
            read_count += 1
            labels = [] if read_count == 1 else ["Deer"]
            record = {"XMP-dc:Subject": labels, "IPTC:Keywords": labels}
            return subprocess.CompletedProcess(arguments, 0, json.dumps([record]), "")
        return subprocess.CompletedProcess(arguments, 0, "updated", "")

    monkeypatch.setattr(
        "exif_turbo.tagging.exif_metadata_writer.find_exiftool", lambda: "exiftool"
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act
    ExifMetadataWriter(auto_repair_tags=False).write_keywords(target, ("Deer",))

    # Assert
    assert target.read_bytes() == original