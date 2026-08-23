"""Audit an assembled release payload for required compliance materials."""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path
from typing import Iterable


class ArtifactAuditError(RuntimeError):
    """Raised when a release payload fails a compliance check."""


def _files(root: Path) -> tuple[Path, ...]:
    return tuple(path for path in root.rglob("*") if path.is_file())


def _require_file(files: Iterable[Path], relative_suffix: str) -> None:
    normalized = relative_suffix.replace("\\", "/").casefold()
    if not any(path.as_posix().casefold().endswith(normalized) for path in files):
        raise ArtifactAuditError(f"required compliance file is missing: {relative_suffix}")


def _is_shared_library(path: Path) -> bool:
    name = path.name.casefold()
    return name.endswith((".dll", ".dylib", ".pyd", ".so")) or ".so." in name


def _manifest_version(manifest: str, distribution: str) -> str:
    match = re.search(
        rf"^{re.escape(distribution)}\s+([^\s]+)\s+\[",
        manifest,
        re.IGNORECASE | re.MULTILINE,
    )
    if match is None:
        raise ArtifactAuditError(
            f"runtime license manifest omits required distribution: {distribution}"
        )
    return match.group(1)


def audit_release_payload(
    root: Path,
    *,
    expect_exiftool: bool = False,
    verify_native_hashes: bool = True,
) -> None:
    """Validate an extracted installer root or PyInstaller onedir payload."""
    if not root.is_dir():
        raise ArtifactAuditError(f"release payload is not a directory: {root}")
    files = _files(root)
    if not files:
        raise ArtifactAuditError(f"release payload is empty: {root}")

    completion_markers = [path for path in files if path.name == "STAGING-COMPLETE"]
    if not completion_markers:
        raise ArtifactAuditError("generated license tree is missing or incomplete")
    license_root = completion_markers[0].parent
    license_files = _files(license_root)
    for required in (
        "PROJECT-LICENSE.txt",
        "CPYTHON-LICENSE.txt",
        "THIRD-PARTY-LICENSES.md",
        "PYTHON-RUNTIME-LICENSES.txt",
    ):
        if not (license_root / required).is_file():
            raise ArtifactAuditError(f"required compliance file is missing: {required}")
    manifest = (license_root / "PYTHON-RUNTIME-LICENSES.txt").read_text(
        encoding="utf-8"
    )
    libvips_version = _manifest_version(manifest, "pyvips-binary")
    qt_version = _manifest_version(manifest, "PySide6")
    libvips_license_dir = license_root / "libvips" / libvips_version
    qt_license_dir = license_root / "qt" / qt_version
    for filename in (
        "LIBVIPS-LGPL-2.1.txt",
        "LGPL-3.0-only.txt",
        "THIRD-PARTY-NOTICES.md",
        "VERSIONS.properties",
        "SOURCE-AND-REPLACEMENT.txt",
        "NATIVE-FILES.sha256",
    ):
        if not (libvips_license_dir / filename).is_file():
            raise ArtifactAuditError(
                f"required compliance file is missing: libvips/{libvips_version}/{filename}"
            )
    if not (qt_license_dir / "LGPL-3.0-only.txt").is_file():
        raise ArtifactAuditError(
            f"required compliance file is missing: qt/{qt_version}/LGPL-3.0-only.txt"
        )
    versions = (libvips_license_dir / "VERSIONS.properties").read_text(
        encoding="utf-8"
    )
    source_notice = (libvips_license_dir / "SOURCE-AND-REPLACEMENT.txt").read_text(
        encoding="utf-8"
    )
    version_values = {
        line.split("=", 1)[1]
        for line in versions.splitlines()
        if line.startswith("VERSION_VIPS=")
    }
    if version_values != {libvips_version}:
        raise ArtifactAuditError("libvips version manifest does not match pyvips-binary")
    source_lines = set(source_notice.splitlines())
    expected_source_urls = {
        f"https://github.com/kleisauke/libvips-packaging/tree/v{libvips_version}",
        f"https://github.com/libvips/libvips/tree/v{libvips_version}",
    }
    if not expected_source_urls <= source_lines:
        raise ArtifactAuditError("libvips source notice does not match pyvips-binary")

    runtime_files = [
        path
        for path in files
        if not path.is_relative_to(license_root) and path.stat().st_size > 0
    ]
    _require_file(runtime_files, "open_clip/bpe_simple_vocab_16e6.txt.gz")

    runtime_by_name = {path.name.casefold(): path for path in runtime_files}
    native_hash_entries = (libvips_license_dir / "NATIVE-FILES.sha256").read_text(
        encoding="ascii"
    ).splitlines()
    if not native_hash_entries:
        raise ArtifactAuditError("libvips native hash manifest is empty")
    for line in native_hash_entries:
        try:
            expected_digest, filename = line.split(None, 1)
        except ValueError as exc:
            raise ArtifactAuditError("invalid libvips native hash manifest") from exc
        native = runtime_by_name.get(filename.strip().casefold())
        if native is None:
            raise ArtifactAuditError(f"replaceable libvips shared library is missing: {filename}")
        if (
            verify_native_hashes
            and hashlib.sha256(native.read_bytes()).hexdigest() != expected_digest
        ):
            raise ArtifactAuditError(f"libvips shared library hash mismatch: {filename}")
    if not any(
        (
            path.name.casefold().startswith(("qt6", "libqt6"))
            and _is_shared_library(path)
        )
        or any(
            part.casefold().endswith(".framework")
            and path.name.casefold() == part.removesuffix(".framework").casefold()
            for part in path.parts
        )
        for path in runtime_files
    ):
        raise ArtifactAuditError("replaceable Qt shared library is missing")

    tgm_payload_names = {
        "tgm-snapshot.json.gz",
        "tgm_terms.faiss",
        "tgm_concept_map.json",
        "tgm_vector_metadata.json",
    }
    tgm_payloads = [
        path
        for path in files
        if path.name.casefold() in tgm_payload_names
        or (
            path.stem.casefold().startswith("tgm")
            and path.suffix.casefold()
            in {".xml", ".rdf", ".mrc", ".marc", ".dat"}
        )
    ]
    if tgm_payloads:
        raise ArtifactAuditError(f"TGM data must not be bundled: {tgm_payloads[0]}")

    exiftool_executables = [
        path
        for path in files
        if path.name.casefold() in {"exiftool", "exiftool.exe"}
        and path.stat().st_size > 0
    ]
    if expect_exiftool and not exiftool_executables:
        raise ArtifactAuditError("expected bundled ExifTool executable is missing")
    if exiftool_executables:
        for required in (
            "exiftool/README.txt",
            "exiftool/exiftool_files/LICENSE",
            "exiftool/exiftool_files/Licenses_Strawberry_Perl.zip",
            "exiftool/exiftool_files/readme_windows.txt",
        ):
            _require_file(files, required)
        perl_archives = [
            path for path in files if path.name == "Licenses_Strawberry_Perl.zip"
        ]
        try:
            with zipfile.ZipFile(perl_archives[0]) as archive:
                if archive.testzip() is not None or not all(
                    archive.read(member).strip()
                    for member in ("perl/Artistic", "perl/Copying")
                ):
                    raise ArtifactAuditError("bundled ExifTool Perl terms are invalid")
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise ArtifactAuditError("bundled ExifTool Perl terms are invalid") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="Extracted installer or bundle root")
    parser.add_argument("--expect-exiftool", action="store_true")
    args = parser.parse_args()
    try:
        audit_release_payload(args.payload, expect_exiftool=args.expect_exiftool)
    except ArtifactAuditError as exc:
        parser.error(str(exc))
    print(f"Release compliance audit passed: {args.payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())