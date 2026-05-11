"""Build self-contained Linux distributions for exif-turbo.

Produces:
    dist/exif-turbo/                               — onedir bundle (GUI + CLI)
    dist/exif-turbo-<version>-linux.deb            — Debian/Ubuntu package
    dist/exif-turbo-<version>-linux.rpm            — Fedora/RHEL package

Package layout:
    /opt/exif-turbo/          — PyInstaller bundle
    /usr/bin/exif-turbo       — wrapper script → /opt/exif-turbo/exif-turbo
    /usr/bin/exif-turbo-index — wrapper script → /opt/exif-turbo/exif-turbo-index
    /usr/share/applications/exif-turbo.desktop
    /usr/share/icons/hicolor/256x256/apps/exif-turbo.png

Requirements:
    pip install pyinstaller babel pillow
    gem install fpm              (https://fpm.readthedocs.io)
    rpmbuild                     (rpm-build on Fedora, rpm on Debian/Ubuntu)

Usage:
    python scripts/build_linux.py
    python scripts/build_linux.py --deb-only
    python scripts/build_linux.py --rpm-only
"""

from __future__ import annotations

import argparse
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

INSTALL_PREFIX = Path("/opt/exif-turbo")
DESKTOP_FILE = """\
[Desktop Entry]
Version=1.0
Name=exif-turbo
GenericName=Image EXIF Browser
Comment=Search and browse image EXIF metadata
Exec=/opt/exif-turbo/exif-turbo
Icon=exif-turbo
Terminal=false
Type=Application
Categories=Graphics;Viewer;
StartupNotify=true
"""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], **kwargs: object) -> None:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, **kwargs)  # type: ignore[call-overload]
    if result.returncode != 0:
        fail(f"Command failed ({result.returncode}): {' '.join(str(c) for c in cmd)}")


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
    pybabel = find_tool("pybabel", venv_subpath=".venv/bin/pybabel")
    locales_dir = REPO_ROOT / "src" / "exif_turbo" / "i18n" / "locales"
    for po in locales_dir.rglob("*.po"):
        mo = po.with_suffix(".mo")
        run([pybabel, "compile", "-i", str(po), "-o", str(mo)])
        print(f"    {mo}")
    print("  Translation catalogs compiled.")


def ensure_icon() -> Path | None:
    """Return the path to a 256×256 PNG icon, generating it from logo.png if needed."""
    icon_png = REPO_ROOT / "assets" / "icon.png"
    if icon_png.exists():
        return icon_png

    logo_png = REPO_ROOT / "src" / "exif_turbo" / "assets" / "logo.png"
    if not logo_png.exists():
        print("  WARNING: No logo.png found — package will be built without an icon.")
        return None

    print("  Generating assets/icon.png from logo.png ...")
    icon_png.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image  # local import — only needed when generating

    img = Image.open(logo_png).convert("RGBA")
    img.resize((256, 256), Image.LANCZOS).save(icon_png, "PNG")
    print("    icon.png generated.")
    return icon_png


def build_staging(bundle_dir: Path, icon_png: Path | None) -> Path:
    """Assemble the staging tree that fpm will package.

    Returns the path to the staging root directory.
    """
    with tempfile.TemporaryDirectory(prefix="exif-turbo-pkg-", delete=False) as tmp:
        staging = Path(tmp)

    opt_dir = staging / "opt" / "exif-turbo"
    opt_dir.mkdir(parents=True)
    print(f"  Copying bundle → {opt_dir} ...")
    shutil.copytree(bundle_dir, opt_dir, dirs_exist_ok=True)

    # ── wrapper scripts ────────────────────────────────────────────────────────
    bin_dir = staging / "usr" / "bin"
    bin_dir.mkdir(parents=True)
    for exe_name in ("exif-turbo", "exif-turbo-index"):
        wrapper = bin_dir / exe_name
        wrapper.write_text(
            f"#!/bin/sh\nexec /opt/exif-turbo/{exe_name} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # ── .desktop file ─────────────────────────────────────────────────────────
    apps_dir = staging / "usr" / "share" / "applications"
    apps_dir.mkdir(parents=True)
    (apps_dir / "exif-turbo.desktop").write_text(DESKTOP_FILE, encoding="utf-8")

    # ── icon ──────────────────────────────────────────────────────────────────
    if icon_png:
        icons_dir = staging / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icons_dir.mkdir(parents=True)
        shutil.copy2(icon_png, icons_dir / "exif-turbo.png")

    return staging


def build_fpm_package(
    fmt: str,
    staging: Path,
    version: str,
    fpm: str,
    output_path: Path,
) -> None:
    """Invoke fpm to produce a DEB or RPM from the staging tree."""
    cmd = [
        fpm,
        "--input-type", "dir",
        "--output-type", fmt,
        "--name", "exif-turbo",
        "--version", version,
        "--architecture", "amd64" if fmt == "deb" else "x86_64",
        "--maintainer", "exif-turbo contributors",
        "--description", "Image EXIF metadata search and indexing tool",
        "--url", "https://github.com/baddonkey/exif-turbo",
        "--license", "MIT",
        "--category", "graphics",
        "--package", str(output_path),
        "--chdir", str(staging),
    ]
    if fmt == "deb":
        cmd += ["--deb-no-default-config-files"]
    cmd += ["."]
    run(cmd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--deb-only", action="store_true", help="Build only the DEB package.")
    group.add_argument("--rpm-only", action="store_true", help="Build only the RPM package.")
    args = parser.parse_args()

    build_deb = not args.rpm_only
    build_rpm = not args.deb_only

    find_tool("pyinstaller")
    fpm = find_tool("fpm")

    version = read_version()
    print(f"Building exif-turbo {version} for Linux ...")

    compile_translations()

    run(["pyinstaller", "exif-turbo-linux.spec", "--noconfirm", "--clean"])
    print("  PyInstaller build complete.")

    bundle_dir = REPO_ROOT / "dist" / "exif-turbo"
    if not bundle_dir.is_dir():
        fail(f"Expected bundle directory not found: {bundle_dir}")

    icon_png = ensure_icon()
    staging = build_staging(bundle_dir, icon_png)

    dist_dir = REPO_ROOT / "dist"
    artifacts: list[Path] = []

    try:
        if build_deb:
            deb_out = dist_dir / f"exif-turbo-{version}-linux.deb"
            deb_out.unlink(missing_ok=True)
            print(f"\n  Building DEB → {deb_out.name} ...")
            build_fpm_package("deb", staging, version, fpm, deb_out)
            artifacts.append(deb_out)

        if build_rpm:
            rpm_out = dist_dir / f"exif-turbo-{version}-linux.rpm"
            rpm_out.unlink(missing_ok=True)
            print(f"\n  Building RPM → {rpm_out.name} ...")
            build_fpm_package("rpm", staging, version, fpm, rpm_out)
            artifacts.append(rpm_out)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print()
    print("Done! Artifacts:")
    print(f"  dist/exif-turbo/")
    for path in artifacts:
        print(f"  {path}")


if __name__ == "__main__":
    main()
