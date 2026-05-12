"""Build a self-contained Windows distribution for exif-turbo.

Produces:
    dist/exif-turbo/                         — unified onedir bundle (GUI + CLI)
    dist/exif-turbo-<version>-windows.msi    — distributable MSI installer

Requirements:
    pip install pyinstaller babel pillow
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
    found = shutil.which(name)
    if found:
        return found
    if venv_subpath:
        candidate = REPO_ROOT / venv_subpath
        if candidate.exists():
            return str(candidate)
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


def commit_version_info(version: str) -> None:
    """Stage and commit auto-generated version_info.py if it changed."""
    status = subprocess.run(
        ["git", "status", "--short", "version_info.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        run(["git", "add", "version_info.py"])
        run(["git", "commit", "-m", f"chore: update version_info.py to {version}"])
        print(f"  Committed version_info.py ({version}).")


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
    exe = staged / "exiftool.exe"
    if exe.exists():
        print(f"  ExifTool already staged: {staged}")
        return staged

    print("  Staging ExifTool for MSI ...")
    ver_url = "https://exiftool.org/ver.txt"
    with urllib.request.urlopen(ver_url, timeout=30) as resp:  # noqa: S310
        version = resp.read().decode().strip()
    print(f"    Latest ExifTool version: {version}")

    zip_url = (
        f"https://sourceforge.net/projects/exiftool/files/"
        f"exiftool-{version}_64.zip/download"
    )
    print(f"    Downloading {zip_url} ...")
    with urllib.request.urlopen(zip_url, timeout=300) as resp:  # noqa: S310
        data = resp.read()

    # Extract into a temporary directory, then move contents up so that
    # exiftool.exe and exiftool_files/ are at the staged root (they must
    # be co-located or ExifTool will not function).
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp_path)

        # The zip contains a single versioned subfolder (e.g. exiftool-13.58_64/)
        subdirs = [d for d in tmp_path.iterdir() if d.is_dir()]
        inner = subdirs[0] if len(subdirs) == 1 else tmp_path

        staged.mkdir(parents=True, exist_ok=True)
        for item in inner.iterdir():
            dest = staged / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))

    # Rename the GUI-drag-drop exe to a plain CLI name
    kexe = next(staged.glob("exiftool(-k).exe"), None)
    if kexe:
        kexe.rename(staged / "exiftool.exe")
        print(f"    Renamed '{kexe.name}' → 'exiftool.exe'")
    elif not exe.exists():
        fail("exiftool(-k).exe not found in downloaded zip — check the ExifTool download URL.")

    print(f"    ExifTool staged at: {staged}")
    return staged


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
    find_tool("pyinstaller")
    wix = find_tool("wix")

    version = read_version()
    print(f"Building exif-turbo {version} for Windows ...")

    compile_translations()

    run(["pyinstaller", "exif-turbo.spec", "--noconfirm", "--clean"])
    print("  PyInstaller build complete.")

    commit_version_info(version)

    app_dir = (REPO_ROOT / "dist" / "exif-turbo").resolve()
    msi_out = REPO_ROOT / "dist" / f"exif-turbo-{version}-windows.msi"
    icon_file = generate_icon()
    exiftool_dir = stage_exiftool()

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

    print()
    print("Done! Artifacts:")
    print(r"  dist\exif-turbo\\")
    print(f"  {msi_out}")


if __name__ == "__main__":
    main()
