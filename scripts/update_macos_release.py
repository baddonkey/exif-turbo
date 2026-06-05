"""Build the macOS DMG and publish it to an existing GitHub release.

Usage:
    python scripts/update_macos_release.py
    python scripts/update_macos_release.py --arch intel
    python scripts/update_macos_release.py --tag v1.14.7
    python scripts/update_macos_release.py --skip-build
    python scripts/update_macos_release.py --sign "Developer ID Application: Your Name (TEAMID)"
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

ARCH_SUFFIX: dict[str, str] = {
    "arm64": "arm64",
    "intel": "intel",
}


class ShellError(RuntimeError):
    pass


def run(cmd: list[str], *, capture: bool = False) -> str:
    print(f"$ {' '.join(cmd)}")
    if capture:
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise ShellError(result.stderr.strip() or result.stdout.strip())
        return result.stdout

    result = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise ShellError(f"Command failed ({result.returncode}): {' '.join(cmd)}")
    return ""


def read_version() -> str:
    init_file = REPO_ROOT / "src" / "exif_turbo" / "__init__.py"
    text = init_file.read_text(encoding="utf-8")
    match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not match:
        raise ShellError(f"Could not read __version__ from {init_file}")
    return match.group(1)


def normalize_tag(tag_or_version: str) -> str:
    return tag_or_version if tag_or_version.startswith("v") else f"v{tag_or_version}"


def version_from_tag(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def ensure_release_exists(tag: str) -> None:
    run(["gh", "release", "view", tag, "--repo", "baddonkey/exif-turbo"])


def build_dmg(arch: str, sign_identity: str | None) -> None:
    cmd = [sys.executable, "scripts/build_macos.py", "--arch", arch]
    if sign_identity:
        cmd += ["--sign", sign_identity]
    run(cmd)


def delete_existing_dmg_asset(tag: str, dmg_name: str) -> None:
    out = run(
        [
            "gh", "release", "view", tag,
            "--repo", "baddonkey/exif-turbo",
            "--json", "assets",
        ],
        capture=True,
    )
    assets: list[dict[str, object]] = json.loads(out).get("assets", [])
    for asset in assets:
        if asset.get("name") == dmg_name:
            run(
                [
                    "gh", "release", "delete-asset", tag, dmg_name,
                    "--repo", "baddonkey/exif-turbo",
                    "--yes",
                ]
            )
            return


def upload_dmg(tag: str, dmg: Path) -> None:
    if not dmg.exists():
        raise ShellError(f"Missing expected DMG artifact: {dmg}")
    run(
        [
            "gh", "release", "upload", tag, str(dmg),
            "--repo", "baddonkey/exif-turbo",
            "--clobber",
        ]
    )


def print_summary(tag: str) -> None:
    out = run(
        [
            "gh", "release", "view", tag,
            "--repo", "baddonkey/exif-turbo",
            "--json", "assets,url",
        ],
        capture=True,
    )
    data = json.loads(out)
    print("\nmacOS assets currently on release:")
    for asset in data.get("assets", []):
        name = str(asset.get("name", ""))
        if name.endswith(".dmg"):
            size = int(asset.get("size", 0))
            print(f"  {name} ({size:,} bytes)")
    url = data.get("url", f"https://github.com/baddonkey/exif-turbo/releases/tag/{tag}")
    print(f"\nRelease URL: {url}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a macOS DMG for the current version and upload it to the matching GitHub release."
    )
    parser.add_argument(
        "--arch",
        choices=list(ARCH_SUFFIX),
        default="arm64",
        help="Target architecture: arm64 (default, Apple Silicon) or intel (x86_64).",
    )
    parser.add_argument(
        "--tag",
        help="Release tag (e.g. v1.14.7). Defaults to the version in src/exif_turbo/__init__.py.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip build_macos.py and only replace/upload the DMG on the release.",
    )
    parser.add_argument(
        "--sign",
        dest="sign_identity",
        default=None,
        help="Developer ID Application identity for codesign (omit for ad-hoc signing).",
    )
    args = parser.parse_args()

    try:
        current_version = read_version()
        tag = normalize_tag(args.tag or current_version)
        version = version_from_tag(tag)
        suffix = ARCH_SUFFIX[args.arch]
        dmg_name = f"exif-turbo-{version}-macos-{suffix}.dmg"
        dmg = REPO_ROOT / "dist" / dmg_name

        print(f"Target release : {tag}")
        print(f"Architecture   : {args.arch}")
        print(f"DMG artifact   : {dmg_name}")

        ensure_release_exists(tag)

        if not args.skip_build:
            build_dmg(args.arch, args.sign_identity)

        delete_existing_dmg_asset(tag, dmg_name)
        upload_dmg(tag, dmg)
        print_summary(tag)

    except ShellError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
