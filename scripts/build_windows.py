"""Build a self-contained Windows distribution for exif-turbo.

Produces:
    dist/exif-turbo/                         — unified onedir bundle (GUI + CLI)
    dist/exif-turbo-<version>-windows.msi    — distributable MSI installer

Requirements:
    pip install pyinstaller babel pillow
    dotnet tool install --global wix          (WiX Toolset v4)

Usage:
    python scripts/build_windows.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
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
