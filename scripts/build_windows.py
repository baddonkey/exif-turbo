"""Build a self-contained Windows distribution for exif-turbo.

Produces:
    dist/exif-turbo/                         — unified onedir bundle (GUI + CLI)
    dist/exif-turbo-<version>-windows.msi    — distributable MSI installer

Requirements:
    pip install pyinstaller babel packaging pillow
    dotnet tool install --global wix          (WiX Toolset v6)
    wix extension add WixToolset.UI.wixext    (run once to install the UI ext)

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
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

try:
    from audit_release_artifact import audit_release_payload
except ModuleNotFoundError:
    from scripts.audit_release_artifact import audit_release_payload

REPO_ROOT = Path(__file__).resolve().parent.parent


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
        candidate = REPO_ROOT / venv_subpath
        if candidate.exists():
            return str(candidate)
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
        audit_release_payload(executables[0].parent, expect_exiftool=True)


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
