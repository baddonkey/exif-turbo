"""Build Linux packages and publish them to an existing GitHub release.

Usage:
    python scripts/update_linux_release.py
    python scripts/update_linux_release.py --tag v1.14.7
    python scripts/update_linux_release.py --skip-build
    python scripts/update_linux_release.py --deb-only
    python scripts/update_linux_release.py --deb-arm-only
    python scripts/update_linux_release.py --deb-amd64-only
    python scripts/update_linux_release.py --rpm-only
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


def build_linux_packages(
    *,
    build_deb: bool,
    build_rpm: bool,
    deb_arches: list[str],
) -> None:
    py = sys.executable
    if build_deb:
        if deb_arches == ["amd64"]:
            run([py, "scripts/build_deb.py", "--arch", "amd64"])
        elif deb_arches == ["arm64"]:
            run([py, "scripts/build_deb.py", "--arch", "arm64"])
        else:
            run([py, "scripts/build_deb.py"])
    if build_rpm:
        run([py, "scripts/build_rpm.py"])


def delete_existing_linux_assets(
    tag: str,
    *,
    delete_deb: bool,
    delete_rpm: bool,
) -> None:
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
        is_deb = name.endswith(".deb")
        is_rpm = name.endswith(".rpm")
        if (is_deb and delete_deb) or (is_rpm and delete_rpm):
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


def upload_linux_assets(tag: str, assets: list[Path]) -> None:
    if not assets:
        raise ShellError("No assets selected for upload")
    for asset in assets:
        if not asset.exists():
            raise ShellError(f"Missing expected artifact: {asset}")

    cmd = ["gh", "release", "upload", tag]
    cmd += [str(asset) for asset in assets]
    cmd += ["--repo", "baddonkey/exif-turbo", "--clobber"]
    run(cmd)


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
        description=(
            "Build Linux packages and upload to the matching GitHub release. "
            "Default: amd64 DEB + arm64 DEB + x86_64 RPM."
        )
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--deb-only",
        action="store_true",
        help="Only build/upload DEB assets (amd64 + arm64).",
    )
    mode.add_argument(
        "--deb-arm-only",
        action="store_true",
        help="Only build/upload arm64 DEB assets.",
    )
    mode.add_argument(
        "--deb-amd64-only",
        action="store_true",
        help="Only build/upload amd64 DEB assets.",
    )
    mode.add_argument(
        "--rpm-only",
        action="store_true",
        help="Only build/upload RPM assets.",
    )
    args = parser.parse_args()

    try:
        current_version = read_version()
        tag = normalize_tag(args.tag or current_version)
        version = version_from_tag(tag)
        include_deb = not args.rpm_only
        include_rpm = not (args.deb_only or args.deb_arm_only or args.deb_amd64_only)
        if args.deb_arm_only:
            deb_arches = ["arm64"]
        elif args.deb_amd64_only:
            deb_arches = ["amd64"]
        else:
            deb_arches = ["amd64", "arm64"]

        print(f"Target release: {tag}")
        print(
            "Selected package types: "
            + ("DEB " if include_deb else "")
            + ("RPM" if include_rpm else "")
        )
        if include_deb:
            print("Selected DEB architectures: " + ", ".join(deb_arches))
        ensure_release_exists(tag)

        if not args.skip_build:
            build_linux_packages(
                build_deb=include_deb,
                build_rpm=include_rpm,
                deb_arches=deb_arches,
            )

        assets: list[Path] = []
        if include_deb:
            if "amd64" in deb_arches:
                assets.append(REPO_ROOT / "dist" / f"exif-turbo-{version}-linux-amd64.deb")
            if "arm64" in deb_arches:
                assets.append(REPO_ROOT / "dist" / f"exif-turbo-{version}-linux-arm64.deb")
        if include_rpm:
            assets.append(REPO_ROOT / "dist" / f"exif-turbo-{version}-linux-x86_64.rpm")

        print("Expected upload artifacts:")
        for asset in assets:
            print(f"- {asset.name}")

        delete_existing_linux_assets(tag, delete_deb=include_deb, delete_rpm=include_rpm)
        upload_linux_assets(tag, assets)
        print_summary(tag)
        return 0
    except ShellError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
