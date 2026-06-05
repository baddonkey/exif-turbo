"""Build Linux packages and publish them to an existing GitHub release.

Usage:
    python scripts/update_linux_release.py
    python scripts/update_linux_release.py --tag v1.14.7
    python scripts/update_linux_release.py --skip-build
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


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


def build_linux_packages() -> None:
    py = sys.executable
    run([py, "scripts/build_deb.py"])
    run([py, "scripts/build_rpm.py"])


def delete_existing_linux_assets(tag: str) -> None:
    out = run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            "baddonkey/exif-turbo",
            "--json",
            "assets",
        ],
        capture=True,
    )
    data = json.loads(out)
    assets: list[dict[str, object]] = data.get("assets", [])
    for asset in assets:
        name = str(asset.get("name", ""))
        if name.endswith(".deb") or name.endswith(".rpm"):
            run(
                [
                    "gh",
                    "release",
                    "delete-asset",
                    tag,
                    name,
                    "--repo",
                    "baddonkey/exif-turbo",
                    "--yes",
                ]
            )


def upload_linux_assets(tag: str, deb: Path, rpm: Path) -> None:
    if not deb.exists():
        raise ShellError(f"Missing expected DEB artifact: {deb}")
    if not rpm.exists():
        raise ShellError(f"Missing expected RPM artifact: {rpm}")

    run(
        [
            "gh",
            "release",
            "upload",
            tag,
            str(deb),
            str(rpm),
            "--repo",
            "baddonkey/exif-turbo",
            "--clobber",
        ]
    )


def print_summary(tag: str) -> None:
    out = run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            "baddonkey/exif-turbo",
            "--json",
            "assets,url",
        ],
        capture=True,
    )
    data = json.loads(out)
    print("\nLinux assets currently on release:")
    for asset in data.get("assets", []):
        name = str(asset.get("name", ""))
        if name.endswith(".deb") or name.endswith(".rpm"):
            size = int(asset.get("size", 0))
            print(f"- {name} ({size} bytes)")
    print(f"\nRelease URL: {data.get('url', f'https://github.com/baddonkey/exif-turbo/releases/tag/{tag}')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build DEB/RPM for the current version and upload to the matching GitHub release."
    )
    parser.add_argument(
        "--tag",
        help="Release tag (for example v1.14.7). Defaults to current src/exif_turbo/__init__.py version.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip build_deb.py/build_rpm.py and only do release asset replacement/upload.",
    )
    args = parser.parse_args()

    try:
        current_version = read_version()
        tag = normalize_tag(args.tag or current_version)
        version = version_from_tag(tag)

        print(f"Target release: {tag}")
        ensure_release_exists(tag)

        if not args.skip_build:
            build_linux_packages()

        deb = REPO_ROOT / "dist" / f"exif-turbo-{version}-linux-amd64.deb"
        rpm = REPO_ROOT / "dist" / f"exif-turbo-{version}-linux-x86_64.rpm"

        delete_existing_linux_assets(tag)
        upload_linux_assets(tag, deb, rpm)
        print_summary(tag)
        return 0
    except ShellError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
