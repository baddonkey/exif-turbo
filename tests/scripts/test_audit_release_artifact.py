from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from scripts.audit_release_artifact import ArtifactAuditError, audit_release_payload


def _write_compliant_payload(root: Path) -> None:
    licenses = root / "_internal" / "licenses"
    for relative in (
        "PROJECT-LICENSE.txt",
        "CPYTHON-LICENSE.txt",
        "THIRD-PARTY-LICENSES.md",
        "PYTHON-RUNTIME-LICENSES.txt",
        "libvips/8.18.4/LIBVIPS-LGPL-2.1.txt",
        "libvips/8.18.4/LGPL-3.0-only.txt",
        "libvips/8.18.4/THIRD-PARTY-NOTICES.md",
        "libvips/8.18.4/VERSIONS.properties",
        "libvips/8.18.4/SOURCE-AND-REPLACEMENT.txt",
        "libvips/8.18.4/NATIVE-FILES.sha256",
        "qt/6.10.2/LGPL-3.0-only.txt",
    ):
        target = licenses / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        contents = "terms"
        if relative == "PYTHON-RUNTIME-LICENSES.txt":
            contents = "pyvips-binary 8.18.4 [LGPL]\nPySide6 6.10.2 [LGPL]\n"
        elif relative.endswith("VERSIONS.properties"):
            contents = "VERSION_VIPS=8.18.4\n"
        elif relative.endswith("SOURCE-AND-REPLACEMENT.txt"):
            contents = (
                "https://github.com/kleisauke/libvips-packaging/tree/v8.18.4\n"
                "https://github.com/libvips/libvips/tree/v8.18.4\n"
            )
        elif relative.endswith("NATIVE-FILES.sha256"):
            digest = hashlib.sha256(b"binary").hexdigest()
            contents = f"{digest}  libvips-42.dll\n"
        target.write_text(contents, encoding="utf-8")
    (licenses / "STAGING-COMPLETE").write_text("complete\n", encoding="ascii")
    (root / "_internal" / "libvips-42.dll").write_bytes(b"binary")
    (root / "_internal" / "Qt6Core.dll").write_bytes(b"binary")
    bpe_vocab = root / "_internal" / "open_clip" / "bpe_simple_vocab_16e6.txt.gz"
    bpe_vocab.parent.mkdir(parents=True)
    bpe_vocab.write_bytes(b"vocabulary")


def _write_media_tool_payload(root: Path) -> None:
    files = {
        "media-tools/imagemagick/magick.exe": b"magick",
        "media-tools/ffmpeg/bin/ffmpeg.exe": b"ffmpeg",
        "media-tools/ffmpeg/bin/ffprobe.exe": b"ffprobe",
        "media-tools/ffmpeg/bin/avcodec-63.dll": b"avcodec",
        "media-tools/licenses/ImageMagick-LICENSE.txt": b"ImageMagick terms",
        "media-tools/licenses/ImageMagick-SBOM.cdx.json": b"ImageMagick SBOM",
        "media-tools/licenses/ImageMagick-VERSION.txt": b"ImageMagick version",
        "media-tools/licenses/FFmpeg-BUILD-CHECKSUMS.sha256": b"archive checksums",
        "media-tools/licenses/FFmpeg-LGPL-2.1.txt": b"FFmpeg LGPL terms",
        "media-tools/licenses/FFmpeg-BUILDS-LICENSE.txt": b"BtbN MIT terms",
        "media-tools/licenses/FFmpeg-BUILDS-README.md": b"Build notes",
        "media-tools/licenses/FFmpeg-BUILDS-SOURCE.zip": b"BtbN build source",
        "media-tools/licenses/FFmpeg-VERSION.txt": b"FFmpeg version/build config",
        "media-tools/licenses/FFmpeg-SOURCE.tar.gz": b"source archive",
        "media-tools/licenses/FFmpeg-SOURCE-MANIFEST.txt": b"source manifest",
        "media-tools/MEDIA-TOOLS.json": b"manifest",
    }
    for relative, contents in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)


def test_audit_release_payload_complete_payload_succeeds(tmp_path: Path) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)

    # Act / Assert
    audit_release_payload(tmp_path)


def test_audit_release_payload_bundled_media_tools_succeed(tmp_path: Path) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)
    _write_media_tool_payload(tmp_path)

    # Act / Assert
    audit_release_payload(tmp_path, expect_media_tools=True)


def test_audit_release_payload_missing_bundled_ffprobe_raises_error(
    tmp_path: Path,
) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)
    _write_media_tool_payload(tmp_path)
    (tmp_path / "media-tools" / "ffmpeg" / "bin" / "ffprobe.exe").unlink()

    # Act / Assert
    with pytest.raises(ArtifactAuditError, match="ffprobe.exe"):
        audit_release_payload(tmp_path, expect_media_tools=True)


def test_audit_release_payload_missing_open_clip_bpe_vocab_raises_error(
    tmp_path: Path,
) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)
    (
        tmp_path
        / "_internal"
        / "open_clip"
        / "bpe_simple_vocab_16e6.txt.gz"
    ).unlink()

    # Act / Assert
    with pytest.raises(
        ArtifactAuditError,
        match="open_clip/bpe_simple_vocab_16e6.txt.gz",
    ):
        audit_release_payload(tmp_path)


def test_audit_release_payload_bundled_tgm_data_raises_error(tmp_path: Path) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)
    (tmp_path / "tgm-snapshot.json.gz").write_text(
        "controlled vocabulary", encoding="utf-8"
    )

    # Act / Assert
    with pytest.raises(ArtifactAuditError, match="TGM data must not be bundled"):
        audit_release_payload(tmp_path)


def test_audit_release_payload_missing_native_notices_raises_error(
    tmp_path: Path,
) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)
    (tmp_path / "_internal" / "licenses" / "libvips" / "8.18.4" / "THIRD-PARTY-NOTICES.md").unlink()

    # Act / Assert
    with pytest.raises(ArtifactAuditError, match="THIRD-PARTY-NOTICES.md"):
        audit_release_payload(tmp_path)


def test_audit_release_payload_linux_sonames_succeeds(tmp_path: Path) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)
    (tmp_path / "_internal" / "libvips-42.dll").unlink()
    (tmp_path / "_internal" / "Qt6Core.dll").unlink()
    (tmp_path / "_internal" / "libvips.so.42").write_bytes(b"binary")
    (tmp_path / "_internal" / "libQt6Core.so.6").write_bytes(b"binary")
    digest = hashlib.sha256(b"binary").hexdigest()
    (
        tmp_path
        / "_internal"
        / "licenses"
        / "libvips"
        / "8.18.4"
        / "NATIVE-FILES.sha256"
    ).write_text(f"{digest}  libvips.so.42\n", encoding="ascii")

    # Act / Assert
    audit_release_payload(tmp_path)


def test_audit_release_payload_mismatched_libvips_version_raises_error(
    tmp_path: Path,
) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)
    versions = (
        tmp_path
        / "_internal"
        / "licenses"
        / "libvips"
        / "8.18.4"
        / "VERSIONS.properties"
    )
    versions.write_text("VERSION_VIPS=8.17.0\n", encoding="utf-8")

    # Act / Assert
    with pytest.raises(ArtifactAuditError, match="does not match pyvips-binary"):
        audit_release_payload(tmp_path)


def test_audit_release_payload_empty_native_hash_manifest_raises_error(
    tmp_path: Path,
) -> None:
    # Arrange
    _write_compliant_payload(tmp_path)
    manifest = (
        tmp_path
        / "_internal"
        / "licenses"
        / "libvips"
        / "8.18.4"
        / "NATIVE-FILES.sha256"
    )
    manifest.write_text("", encoding="ascii")

    # Act / Assert
    with pytest.raises(ArtifactAuditError, match="hash manifest is empty"):
        audit_release_payload(tmp_path)