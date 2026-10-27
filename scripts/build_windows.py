"""Build a self-contained Windows distribution for exif-turbo.

Produces:
    dist/exif-turbo/                         — unified onedir bundle (GUI + CLI)
    dist/exif-turbo-<version>-windows.msi    — distributable MSI installer

Requirements:
    pip install uv==0.13.0
    dotnet tool install --global wix          (WiX Toolset v6)
    wix extension add WixToolset.UI.wixext    (run once to install the UI ext)
    7-Zip command-line tool (7z.exe), https://www.7-zip.org/

The script automatically downloads the latest 64-bit ExifTool Windows binary
from exiftool.org, stages it in build/exiftool-staged/, and bundles it into
the MSI as an optional feature (pre-selected by default).  Internet access is
required at build time.  The staged directory is reused on subsequent runs to
avoid repeated downloads.

Usage:
    python scripts/build_windows.py
"""

from __future__ import annotations

import io
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

try:
    from audit_release_artifact import audit_release_payload
    from release_environment import ensure_release_environment
except ModuleNotFoundError:
    from scripts.audit_release_artifact import audit_release_payload
    from scripts.release_environment import ensure_release_environment

REPO_ROOT = Path(__file__).resolve().parent.parent

_IMAGEMAGICK_VERSION = "7.1.2-34"
_IMAGEMAGICK_ARCHIVE = f"ImageMagick-{_IMAGEMAGICK_VERSION}-portable-Q16-x64.7z"
_IMAGEMAGICK_ARCHIVE_URL = (
    "https://github.com/ImageMagick/ImageMagick/releases/download/"
    f"{_IMAGEMAGICK_VERSION}/{_IMAGEMAGICK_ARCHIVE}"
)
_IMAGEMAGICK_ARCHIVE_SHA256 = (
    "52cc6a441c7884f5ff4274b410c9b90c4b7d54245dcdf4d32988bb4e4df4e5d1"
)
_IMAGEMAGICK_SBOM_URL = (
    "https://github.com/ImageMagick/ImageMagick/releases/download/"
    f"{_IMAGEMAGICK_VERSION}/ImageMagick-{_IMAGEMAGICK_VERSION}-portable-Q16-x64.cdx.json"
)
_IMAGEMAGICK_SBOM_SHA256 = (
    "fddfaa608e57215897e83d7e9933f5e692ce07883510a00310605a540382390f"
)
_FFMPEG_ARCHIVE = "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip"
_FFMPEG_ARCHIVE_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    f"{_FFMPEG_ARCHIVE}"
)
_FFMPEG_ARCHIVE_SHA256 = (
    "ce7c09bf3897333bff873edc5873f31425a429f9da99fba9add844da5fa0b64b"
)
_FFMPEG_CHECKSUMS_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256"
)
_FFMPEG_CHECKSUMS_SHA256 = (
    "48f9147a98a35319f265119cecce5f2221018df80b3be0448b7a0e952955a502"
)
_FFMPEG_BUILDS_COMMIT = "b4a2b1d7cc241786eb8e2b588a7ade40cad48bbd"
_FFMPEG_BUILDS_SOURCE_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/archive/"
    f"{_FFMPEG_BUILDS_COMMIT}.zip"
)
_MEDIA_TOOLS_LAYOUT_VERSION = 1


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], **kwargs: object) -> None:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, **kwargs)  # type: ignore[call-overload]
    if result.returncode != 0:
        fail(f"Command failed ({result.returncode}): {' '.join(cmd)}")


def find_tool(name: str, venv_subpath: str | None = None) -> str:
    # Prefer the venv-local binary so that venv-installed packages (e.g. av,
    # Pillow) are visible to PyInstaller instead of a globally installed copy.
    if venv_subpath:
        candidate = Path(sys.executable).parent / Path(venv_subpath).name
        if candidate.exists():
            return str(candidate)
        fail(f"Required locked-environment tool '{name}' not found: {candidate}")
    found = shutil.which(name)
    if found:
        return found
    fail(f"Required tool '{name}' not found. See script header for install instructions.")
    return ""  # unreachable


def read_version() -> str:
    init_file = REPO_ROOT / "src" / "exif_turbo" / "__init__.py"
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", init_file.read_text())
    if not match:
        fail(f"Could not read __version__ from {init_file}")
    return match.group(1)


def compile_translations() -> None:
    print("  Compiling translation catalogs ...")
    pybabel = find_tool("pybabel", venv_subpath=".venv/Scripts/pybabel.exe")
    locales_dir = REPO_ROOT / "src" / "exif_turbo" / "i18n" / "locales"
    for po in locales_dir.rglob("*.po"):
        mo = po.with_suffix(".mo")
        run([pybabel, "compile", "-i", str(po), "-o", str(mo)])
        print(f"    {mo}")
    print("  Translation catalogs compiled.")


def validate_exiftool_licenses(staged: Path) -> None:
    """Require the complete upstream license payload before packaging ExifTool."""
    required_files = (
        staged / "README.txt",
        staged / "exiftool_files" / "LICENSE",
        staged / "exiftool_files" / "Licenses_Strawberry_Perl.zip",
        staged / "exiftool_files" / "readme_windows.txt",
    )
    missing = [
        str(path.relative_to(staged))
        for path in required_files
        if not path.is_file() or path.stat().st_size == 0
    ]
    if missing:
        fail(f"ExifTool license payload is incomplete: {', '.join(missing)}")

    perl_licenses = required_files[2]
    try:
        with zipfile.ZipFile(perl_licenses) as archive:
            corrupt_member = archive.testzip()
            members = set(archive.namelist())
            empty_terms = {
                member
                for member in ("perl/Artistic", "perl/Copying")
                if member in members and not archive.read(member).strip()
            }
    except (OSError, zipfile.BadZipFile) as exc:
        fail(f"ExifTool Perl license archive is unreadable: {exc}")
    if corrupt_member is not None:
        fail(f"ExifTool Perl license archive is corrupt: {corrupt_member}")
    missing_terms = {"perl/Artistic", "perl/Copying"} - members
    if missing_terms or empty_terms:
        fail(
            "ExifTool Perl license archive is incomplete: "
            + ", ".join(sorted(missing_terms | empty_terms))
        )


def stage_exiftool() -> Path:
    """Download and stage the ExifTool 64-bit Windows binary for the MSI.

    Downloads the latest exiftool-<ver>_64.zip from SourceForge, extracts it
    into build/exiftool-staged/ (flattening the versioned top-level folder in
    the zip), and renames 'exiftool(-k).exe' to 'exiftool.exe'.  The staged
    directory is returned and passed to the WiX build as $(var.ExifToolDir).

    If the directory already exists (i.e. was staged in a previous run) and
    contains exiftool.exe, the download is skipped.
    """
    staged = REPO_ROOT / "build" / "exiftool-staged"
    version_file = staged / "VERSION.txt"
    ver_url = "https://exiftool.org/ver.txt"
    with urllib.request.urlopen(ver_url, timeout=30) as resp:  # noqa: S310
        version = resp.read().decode().strip()
    print(f"    Latest ExifTool version: {version}")
    if (
        (staged / "exiftool.exe").is_file()
        and version_file.is_file()
        and version_file.read_text(encoding="ascii").strip() == version
    ):
        validate_exiftool_licenses(staged)
        print(f"  ExifTool {version} already staged: {staged}")
        return staged

    print("  Staging ExifTool for MSI ...")

    zip_url = (
        f"https://sourceforge.net/projects/exiftool/files/"
        f"exiftool-{version}_64.zip/download"
    )
    print(f"    Downloading {zip_url} ...")
    with urllib.request.urlopen(zip_url, timeout=300) as resp:  # noqa: S310
        data = resp.read()

    # Build and validate a complete replacement before publishing it.
    build_dir = REPO_ROOT / "build"
    build_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build_dir) as tmp:
        tmp_path = Path(tmp)
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(extracted)

        # The zip contains a single versioned subfolder (e.g. exiftool-13.58_64/)
        subdirs = [directory for directory in extracted.iterdir() if directory.is_dir()]
        inner = subdirs[0] if len(subdirs) == 1 else extracted
        candidate = tmp_path / "staged"
        candidate.mkdir()
        for item in inner.iterdir():
            shutil.move(str(item), str(candidate / item.name))

        kexe = next(candidate.glob("exiftool(-k).exe"), None)
        if kexe is None:
            fail("exiftool(-k).exe not found in downloaded zip — check the ExifTool download URL.")
        kexe.rename(candidate / "exiftool.exe")
        print(f"    Renamed '{kexe.name}' → 'exiftool.exe'")
        (candidate / "VERSION.txt").write_text(version + "\n", encoding="ascii")
        validate_exiftool_licenses(candidate)

        if staged.exists():
            shutil.rmtree(staged)
        shutil.move(str(candidate), staged)

    print(f"    ExifTool staged at: {staged}")
    return staged


def _download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch for {url}: expected {expected_sha256}, "
            f"received {actual_sha256}"
        )


def _download_to_path(url: str, destination: Path) -> str:
    digest = hashlib.sha256()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
    return digest.hexdigest()


def _safe_archive_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"unsafe archive member path: {name}")
    return path


def _find_7zip() -> str:
    for name in ("7z.exe", "7za.exe", "7z"):
        found = shutil.which(name)
        if found:
            return found
    for environment_name in ("ProgramFiles", "ProgramFiles(x86)"):
        program_files = os.environ.get(environment_name)
        if program_files:
            candidate = Path(program_files) / "7-Zip" / "7z.exe"
            if candidate.is_file():
                return str(candidate)
    fail("7-Zip command-line tool not found; install 7-Zip to stage ImageMagick")
    return ""


def _extract_7z_archive(
    archive_path: Path,
    destination: Path,
    *,
    seven_zip: str | None = None,
) -> None:
    executable = seven_zip or _find_7zip()
    listing = subprocess.run(
        [executable, "l", "-slt", str(archive_path)],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if listing.returncode != 0:
        raise ValueError(f"7-Zip could not list {archive_path.name}: {listing.stderr}")

    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in listing.stdout.splitlines():
        if line.strip() == "----------" or not line.strip():
            if current:
                records.append(current)
            current = {}
        elif " = " in line:
            key, value = line.split(" = ", 1)
            current[key] = value
    if current:
        records.append(current)

    for record in records:
        member = record.get("Path")
        if not member or member in {str(archive_path), archive_path.name}:
            continue
        _safe_archive_path(member)
        if record.get("Symbolic Link") or record.get("Hard Link"):
            raise ValueError(f"7z archive contains a link: {member}")

    destination.mkdir(parents=True, exist_ok=True)
    extraction = subprocess.run(
        [executable, "x", "-y", f"-o{destination}", str(archive_path)],
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if extraction.returncode != 0:
        raise ValueError(
            f"7-Zip could not extract {archive_path.name}: {extraction.stderr}"
        )


def _extract_ffmpeg_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        executable_members = [
            info.filename
            for info in members
            if (
                PurePosixPath(info.filename.replace("\\", "/")).as_posix().lower()
                == "bin/ffmpeg.exe"
                or PurePosixPath(info.filename.replace("\\", "/"))
                .as_posix()
                .lower()
                .endswith("/bin/ffmpeg.exe")
            )
        ]
        if len(executable_members) != 1:
            raise ValueError("FFmpeg archive must contain exactly one bin/ffmpeg.exe")
        executable_path = _safe_archive_path(executable_members[0])
        archive_root = executable_path.parent.parent

        for info in members:
            member_path = _safe_archive_path(info.filename)
            if info.is_dir() or not member_path.parts:
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError(f"FFmpeg archive contains a symbolic link: {info.filename}")
            try:
                relative_path = member_path.relative_to(archive_root)
            except ValueError:
                continue
            target = destination.joinpath(*relative_path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def validate_media_tools(staged: Path) -> None:
    required_files = (
        staged / "imagemagick" / "magick.exe",
        staged / "licenses" / "ImageMagick-LICENSE.txt",
        staged / "licenses" / "ImageMagick-SBOM.cdx.json",
        staged / "licenses" / "ImageMagick-VERSION.txt",
        staged / "ffmpeg" / "bin" / "ffmpeg.exe",
        staged / "ffmpeg" / "bin" / "ffprobe.exe",
        staged / "licenses" / "FFmpeg-BUILD-CHECKSUMS.sha256",
        staged / "licenses" / "FFmpeg-LGPL-2.1.txt",
        staged / "licenses" / "FFmpeg-BUILDS-LICENSE.txt",
        staged / "licenses" / "FFmpeg-BUILDS-README.md",
        staged / "licenses" / "FFmpeg-BUILDS-SOURCE.zip",
        staged / "licenses" / "FFmpeg-VERSION.txt",
        staged / "licenses" / "FFmpeg-SOURCE.tar.gz",
        staged / "licenses" / "FFmpeg-SOURCE-MANIFEST.txt",
        staged / "MEDIA-TOOLS.json",
    )
    missing = [str(path.relative_to(staged)) for path in required_files if not path.is_file()]
    if missing:
        fail(f"Media tool payload is incomplete: {', '.join(missing)}")
    for path in required_files:
        if path.stat().st_size == 0:
            fail(f"Media tool payload contains an empty file: {path.relative_to(staged)}")
    imagemagick_license = (staged / "licenses" / "ImageMagick-LICENSE.txt").read_text(
        encoding="utf-8"
    )
    if "IMAGEMAGICK LICENSE" not in imagemagick_license.upper():
        fail("Staged ImageMagick license text is invalid")
    ffmpeg_checksums = (staged / "licenses" / "FFmpeg-BUILD-CHECKSUMS.sha256").read_text(
        encoding="ascii"
    )
    if _FFMPEG_ARCHIVE_SHA256 not in ffmpeg_checksums:
        fail("FFmpeg checksum manifest does not contain the pinned Windows archive")
    ffmpeg_bin = staged / "ffmpeg" / "bin"
    if not any(ffmpeg_bin.glob("avcodec-*.dll")):
        fail("FFmpeg shared build is missing its avcodec DLL")
    imagemagick_version = (staged / "licenses" / "ImageMagick-VERSION.txt").read_text(
        encoding="utf-8"
    )
    if f"ImageMagick { _IMAGEMAGICK_VERSION }" not in imagemagick_version:
        fail("Staged ImageMagick version does not match the pinned release")
    ffmpeg_version = (staged / "licenses" / "FFmpeg-VERSION.txt").read_text(
        encoding="utf-8"
    )
    if "ffmpeg version n9.0" not in ffmpeg_version or "configuration:" not in ffmpeg_version:
        fail("Staged FFmpeg version/configuration notice is incomplete")
    ffmpeg_configuration = ffmpeg_version.split("configuration:", 1)[-1]
    if "--enable-gpl" in ffmpeg_configuration or "--enable-nonfree" in ffmpeg_configuration:
        fail("Staged FFmpeg build unexpectedly enables GPL or nonfree components")
    if "GNU LESSER GENERAL PUBLIC LICENSE" not in (
        staged / "licenses" / "FFmpeg-LGPL-2.1.txt"
    ).read_text(encoding="utf-8").upper():
        fail("Staged FFmpeg LGPL license text is invalid")
    manifest = json.loads((staged / "MEDIA-TOOLS.json").read_text(encoding="utf-8"))
    if (
        manifest.get("layout_version") != _MEDIA_TOOLS_LAYOUT_VERSION
        or manifest.get("imagemagick_version") != _IMAGEMAGICK_VERSION
        or manifest.get("imagemagick_archive_sha256") != _IMAGEMAGICK_ARCHIVE_SHA256
        or manifest.get("ffmpeg_archive_sha256") != _FFMPEG_ARCHIVE_SHA256
    ):
        fail("Staged media-tool manifest does not match pinned archive checksums")


def stage_media_tools() -> Path:
    """Download, verify, and stage the Windows media executables and notices."""
    seven_zip = _find_7zip()
    staged = REPO_ROOT / "build" / "media-tools-staged"
    manifest_path = staged / "MEDIA-TOOLS.json"
    if (
        manifest_path.is_file()
        and (staged / "imagemagick" / "magick.exe").is_file()
        and (staged / "ffmpeg" / "bin" / "ffmpeg.exe").is_file()
        and (staged / "ffmpeg" / "bin" / "ffprobe.exe").is_file()
    ):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("layout_version") == _MEDIA_TOOLS_LAYOUT_VERSION
                and manifest.get("imagemagick_archive_sha256")
                == _IMAGEMAGICK_ARCHIVE_SHA256
                and manifest.get("ffmpeg_archive_sha256") == _FFMPEG_ARCHIVE_SHA256
            ):
                validate_media_tools(staged)
                print(f"  Verified staged media tools: {staged}")
                return staged
        except (OSError, json.JSONDecodeError):
            pass

    build_dir = REPO_ROOT / "build"
    build_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build_dir) as temporary:
        temporary_path = Path(temporary)
        imagemagick_archive = temporary_path / _IMAGEMAGICK_ARCHIVE
        ffmpeg_archive = temporary_path / _FFMPEG_ARCHIVE
        _download_verified(
            _IMAGEMAGICK_ARCHIVE_URL,
            imagemagick_archive,
            _IMAGEMAGICK_ARCHIVE_SHA256,
        )
        _download_verified(
            _FFMPEG_ARCHIVE_URL,
            ffmpeg_archive,
            _FFMPEG_ARCHIVE_SHA256,
        )

        candidate = temporary_path / "staged"
        candidate.mkdir()
        image_extract = temporary_path / "imagemagick-extracted"
        _extract_7z_archive(imagemagick_archive, image_extract, seven_zip=seven_zip)

        magick_executables = tuple(image_extract.rglob("magick.exe"))
        if len(magick_executables) != 1:
            fail("ImageMagick archive must contain exactly one magick.exe")
        shutil.copytree(magick_executables[0].parent, candidate / "imagemagick")
        imagemagick_version_result = subprocess.run(
            [str(candidate / "imagemagick" / "magick.exe"), "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if (
            imagemagick_version_result.returncode != 0
            or f"ImageMagick {_IMAGEMAGICK_VERSION}"
            not in imagemagick_version_result.stdout
        ):
            fail("Staged ImageMagick executable failed its pinned version check")

        ffmpeg_root = candidate / "ffmpeg"
        _extract_ffmpeg_archive(ffmpeg_archive, ffmpeg_root)
        ffmpeg_executable = ffmpeg_root / "bin" / "ffmpeg.exe"
        version_result = subprocess.run(
            [str(ffmpeg_executable), "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if version_result.returncode != 0:
            fail("Staged FFmpeg executable failed its version check")
        version_output = version_result.stdout
        version_match = re.search(r"^ffmpeg version n9\.0[^\r\n]*-g([0-9a-f]{7,40})", version_output, re.MULTILINE)
        if version_match is None:
            fail("Staged FFmpeg does not identify an n9.0 source revision")
        assert version_match is not None
        ffmpeg_revision = version_match.group(1)
        build_configuration = version_output.split("configuration:", 1)[-1]
        if "--enable-gpl" in build_configuration or "--enable-nonfree" in build_configuration:
            fail("Staged FFmpeg build unexpectedly enables GPL or nonfree components")

        licenses = candidate / "licenses"
        licenses.mkdir(parents=True)
        (licenses / "ImageMagick-VERSION.txt").write_text(
            imagemagick_version_result.stdout, encoding="utf-8"
        )
        (licenses / "FFmpeg-VERSION.txt").write_text(
            version_output, encoding="utf-8"
        )
        (licenses / "FFmpeg-VERSION.txt").write_text(
            version_output, encoding="utf-8"
        )
        image_license_url = (
            "https://raw.githubusercontent.com/ImageMagick/ImageMagick/"
            f"{_IMAGEMAGICK_VERSION}/LICENSE"
        )
        ffmpeg_license_url = (
            f"https://raw.githubusercontent.com/FFmpeg/FFmpeg/{ffmpeg_revision}/"
            "COPYING.LGPLv2.1"
        )
        btb_license_url = (
            "https://raw.githubusercontent.com/BtbN/FFmpeg-Builds/"
            f"{_FFMPEG_BUILDS_COMMIT}/LICENSE"
        )
        btb_readme_url = (
            "https://raw.githubusercontent.com/BtbN/FFmpeg-Builds/"
            f"{_FFMPEG_BUILDS_COMMIT}/README.md"
        )
        btb_source_url = _FFMPEG_BUILDS_SOURCE_URL
        for url, target in (
            (image_license_url, licenses / "ImageMagick-LICENSE.txt"),
            (ffmpeg_license_url, licenses / "FFmpeg-LGPL-2.1.txt"),
            (btb_license_url, licenses / "FFmpeg-BUILDS-LICENSE.txt"),
            (btb_readme_url, licenses / "FFmpeg-BUILDS-README.md"),
        ):
            _download_to_path(url, target)
        _download_verified(
            _IMAGEMAGICK_SBOM_URL,
            licenses / "ImageMagick-SBOM.cdx.json",
            _IMAGEMAGICK_SBOM_SHA256,
        )
        _download_verified(
            _FFMPEG_CHECKSUMS_URL,
            licenses / "FFmpeg-BUILD-CHECKSUMS.sha256",
            _FFMPEG_CHECKSUMS_SHA256,
        )
        build_source_sha256 = _download_to_path(
            btb_source_url, licenses / "FFmpeg-BUILDS-SOURCE.zip"
        )

        ffmpeg_source_url = (
            f"https://github.com/FFmpeg/FFmpeg/archive/{ffmpeg_revision}.tar.gz"
        )
        source_sha256 = _download_to_path(
            ffmpeg_source_url, licenses / "FFmpeg-SOURCE.tar.gz"
        )
        (licenses / "FFmpeg-SOURCE-MANIFEST.txt").write_text(
            "FFmpeg source matching the bundled LGPL shared binaries.\n"
            f"FFmpeg revision: {ffmpeg_revision}\n"
            f"Source URL: {ffmpeg_source_url}\n"
            f"Source SHA-256: {source_sha256}\n"
            f"FFmpeg binary SHA-256: {_FFMPEG_ARCHIVE_SHA256}\n"
            f"BtbN build scripts revision: {_FFMPEG_BUILDS_COMMIT}\n"
            f"BtbN build scripts source: {btb_source_url}\n"
            f"BtbN build scripts SHA-256: {build_source_sha256}\n"
            f"BtbN build asset: {_FFMPEG_ARCHIVE}\n",
            encoding="utf-8",
        )
        (candidate / "MEDIA-TOOLS.json").write_text(
            json.dumps(
                {
                    "layout_version": _MEDIA_TOOLS_LAYOUT_VERSION,
                    "imagemagick_version": _IMAGEMAGICK_VERSION,
                    "imagemagick_archive_sha256": _IMAGEMAGICK_ARCHIVE_SHA256,
                    "ffmpeg_archive": _FFMPEG_ARCHIVE,
                    "ffmpeg_archive_sha256": _FFMPEG_ARCHIVE_SHA256,
                    "ffmpeg_revision": ffmpeg_revision,
                    "ffmpeg_source_sha256": source_sha256,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        validate_media_tools(candidate)

        if staged.exists():
            shutil.rmtree(staged)
        shutil.move(str(candidate), staged)

    print(f"  Media tools staged at: {staged}")
    return staged


def audit_msi(msi: Path) -> None:
    """Extract the completed MSI and audit the exact installed payload."""
    with tempfile.TemporaryDirectory() as temporary:
        extracted = Path(temporary) / "extracted"
        extracted.mkdir()
        result = subprocess.run(
            [
                "msiexec.exe",
                "/a",
                str(msi),
                "/qn",
                f"TARGETDIR={extracted}",
            ],
            cwd=REPO_ROOT,
            check=False,
        )
        if result.returncode != 0:
            fail(f"Could not extract MSI for compliance audit ({result.returncode})")
        executables = list(extracted.rglob("exif-turbo.exe"))
        if len(executables) != 1:
            fail("Extracted MSI does not contain exactly one exif-turbo.exe")
        audit_release_payload(
            executables[0].parent,
            expect_exiftool=True,
            expect_media_tools=True,
        )


def generate_icon() -> Path:
    icon_file = REPO_ROOT / "assets" / "icon.ico"
    logo_png = REPO_ROOT / "src" / "exif_turbo" / "assets" / "logo.png"
    if not icon_file.exists() and logo_png.exists():
        print("  Generating assets/icon.ico from logo.png ...")
        icon_file.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image  # local import — only needed when generating

        img = Image.open(logo_png).convert("RGBA")
        img.save(
            icon_file,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        print("    icon.ico generated.")
    if not icon_file.exists():
        print(f"WARNING: Icon file not found: {icon_file}", file=sys.stderr)
        print("WARNING: The MSI will be built without a custom icon.", file=sys.stderr)
        # WiX requires $(var.IconFile) to resolve — fall back to the EXE.
        return REPO_ROOT / "dist" / "exif-turbo" / "exif-turbo.exe"
    return icon_file


def main() -> None:
    ensure_release_environment(Path(__file__))
    pyinstaller = find_tool("pyinstaller", venv_subpath=".venv/Scripts/pyinstaller.exe")
    wix = find_tool("wix")

    version = read_version()
    print(f"Building exif-turbo {version} for Windows ...")

    compile_translations()

    run([pyinstaller, "exif-turbo.spec", "--noconfirm", "--clean"])
    print("  PyInstaller build complete.")

    app_dir = (REPO_ROOT / "dist" / "exif-turbo").resolve()
    msi_out = REPO_ROOT / "dist" / f"exif-turbo-{version}-windows.msi"
    icon_file = generate_icon()
    exiftool_dir = stage_exiftool()
    media_tools_dir = stage_media_tools()
    audit_release_payload(app_dir)

    run(
        [
            wix,
            "build",
            "installer/exif-turbo.wxs",
            "-d",
            f"Version={version}",
            "-d",
            f"AppDir={app_dir}",
            "-d",
            f"IconFile={icon_file}",
            "-d",
            f"ExifToolDir={exiftool_dir.resolve()}",
            "-d",
            f"MediaToolsDir={media_tools_dir.resolve()}",
            "-arch",
            "x64",
            "-ext",
            "WixToolset.UI.wixext",
            "-out",
            str(msi_out),
        ]
    )
    audit_msi(msi_out)

    print()
    print("Done! Artifacts:")
    print(r"  dist\exif-turbo\\")
    print(f"  {msi_out}")


if __name__ == "__main__":
    main()
