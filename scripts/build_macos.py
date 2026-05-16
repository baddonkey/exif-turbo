"""Build a self-contained macOS distribution for exif-turbo.

Produces:
    dist/exif-turbo.app                       — app bundle (GUI + CLI)
    dist/exif-turbo-<version>-macos.dmg       — distributable disk image

Requirements:
    pip install pyinstaller babel pillow
    Xcode Command Line Tools (for iconutil and hdiutil)

Usage:
    python scripts/build_macos.py
    python scripts/build_macos.py --sign "Developer ID Application: Your Name (TEAMID)"
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
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


def generate_icns() -> None:
    logo_png = REPO_ROOT / "src" / "exif_turbo" / "assets" / "logo.png"
    if not logo_png.exists():
        print("  No logo.png found — skipping .icns generation.")
        return

    from PIL import Image  # local import — only needed when generating

    sizes = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "exif-turbo.iconset"
        iconset.mkdir()
        img = Image.open(logo_png).convert("RGBA")
        for name, size in sizes:
            img.resize((size, size), Image.LANCZOS).save(iconset / name, "PNG")

        assets = REPO_ROOT / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        run(["iconutil", "--convert", "icns", "--output", str(assets / "icon.icns"), str(iconset)])

    print("  icon.icns generated from logo.png.")


def compile_translations() -> None:
    print("  Compiling translation catalogs ...")
    pybabel = find_tool("pybabel", venv_subpath=".venv/bin/pybabel")
    locales_dir = REPO_ROOT / "src" / "exif_turbo" / "i18n" / "locales"
    for po in locales_dir.rglob("*.po"):
        mo = po.with_suffix(".mo")
        run([pybabel, "compile", "-i", str(po), "-o", str(mo)])
        print(f"    {mo}")
    print("  Translation catalogs compiled.")


def sign_item(path: Path, identity: str | None) -> None:
    if identity:
        run(
            [
                "codesign",
                "--force",
                "--options",
                "runtime",
                "--sign",
                identity,
                "--timestamp",
                str(path),
            ]
        )
    else:
        run(["codesign", "--force", "--sign", "-", str(path)])


def sign_bundle(app: Path, identity: str | None) -> None:
    print("  Signing app bundle ...")
    for pattern in ("*.dylib", "*.so"):
        for lib in app.rglob(pattern):
            sign_item(lib, identity)
    sign_item(app / "Contents" / "MacOS" / "exif-turbo", identity)
    sign_item(app, identity)
    print("  Code signing complete.")


def build_dmg(app: Path, version: str, arch_suffix: str = "") -> Path:
    suffix = f"-{arch_suffix}" if arch_suffix else ""
    dmg_name = f"exif-turbo-{version}-macos{suffix}.dmg"
    dmg_out = REPO_ROOT / "dist" / dmg_name

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "dmg-staging"
        staging.mkdir()
        run(["cp", "-R", str(app), str(staging)])
        # Symlink to /Applications for drag-install
        (staging / "Applications").symlink_to("/Applications")

        readme = staging / "README.txt"
        readme.write_text(
            f"""exif-turbo {version}

Drag exif-turbo.app into the Applications folder to install.

Full documentation: https://github.com/baddonkey/exif-turbo
"""
        )

        run(
            [
                "hdiutil",
                "create",
                "-volname",
                f"exif-turbo {version}",
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                "-fs",
                "HFS+",
                str(dmg_out),
            ]
        )

    return dmg_out


ARCH_CONFIGS: dict[str, tuple[str, str]] = {
    "arm64": ("exif-turbo-macos-arm.spec", "arm64"),
    "intel": ("exif-turbo-macos-intel.spec", "intel"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sign",
        dest="sign_identity",
        default=None,
        help="Developer ID Application identity for codesign (omit for ad-hoc signing).",
    )
    parser.add_argument(
        "--arch",
        dest="arch",
        choices=list(ARCH_CONFIGS),
        default="arm64",
        help="Target architecture: arm64 (default, Apple Silicon) or intel (x86_64).",
    )
    args = parser.parse_args()

    spec_file, arch_suffix = ARCH_CONFIGS[args.arch]

    version = read_version()
    print(f"Building exif-turbo {version} for macOS ({args.arch}) ...")

    generate_icns()
    compile_translations()

    run(["pyinstaller", "--noconfirm", "--clean", spec_file])
    print("  PyInstaller build complete.")

    app = REPO_ROOT / "dist" / "exif-turbo.app"
    sign_bundle(app, args.sign_identity)
    dmg_out = build_dmg(app, version, arch_suffix)

    print()
    print("Done! Artifacts:")
    print("  dist/exif-turbo.app")
    print(f"  {dmg_out}")


if __name__ == "__main__":
    main()
