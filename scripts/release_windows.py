"""Cut a Windows release for a specific semantic version.

Given ``major minor patch`` this script will:

1. Bump version in ``src/exif_turbo/__init__.py`` and ``pyproject.toml``.
2. Commit the version bump.
3. Build Windows artifacts via ``scripts/build_windows.py``.
4. Create and push an annotated git tag ``v<version>``.
5. Create a GitHub release and upload Windows binaries.

Uploaded assets:
    - dist/exif-turbo-<version>-windows.msi
    - dist/exif-turbo-<version>-windows.zip (zipped onedir bundle)

Usage:
    python scripts/release_windows.py 1 15 0
    python scripts/release_windows.py 1 15 0 --repo owner/repo
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = REPO_ROOT / "src" / "exif_turbo" / "__init__.py"
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"


class ShellError(RuntimeError):
    pass


def run(cmd: list[str], *, capture: bool = False) -> str:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=capture,
    )
    if result.returncode != 0:
        if capture:
            msg = result.stderr.strip() or result.stdout.strip()
        else:
            msg = f"Command failed ({result.returncode}): {' '.join(cmd)}"
        raise ShellError(msg)
    return result.stdout if capture else ""


def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise ShellError(f"Required tool '{name}' not found on PATH")


def ensure_clean_tree() -> None:
    status = run(["git", "status", "--short"], capture=True).strip()
    if status:
        raise ShellError(
            "Working tree is not clean. Commit or stash changes first."
        )


def read_version() -> str:
    text = INIT_FILE.read_text(encoding="utf-8")
    match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not match:
        raise ShellError(f"Could not read __version__ from {INIT_FILE}")
    return match.group(1)


def write_version(version: str) -> None:
    init_text = INIT_FILE.read_text(encoding="utf-8")
    init_new = re.sub(
        r"(__version__\s*=\s*['\"])([^'\"]+)(['\"])",
        rf"\g<1>{version}\g<3>",
        init_text,
        count=1,
    )
    if init_text == init_new:
        raise ShellError(f"Failed to update __version__ in {INIT_FILE}")
    INIT_FILE.write_text(init_new, encoding="utf-8")

    pyproject_text = PYPROJECT_FILE.read_text(encoding="utf-8")
    pyproject_new = re.sub(
        r"(^version\s*=\s*['\"])([^'\"]+)(['\"])",
        rf"\g<1>{version}\g<3>",
        pyproject_text,
        count=1,
        flags=re.MULTILINE,
    )
    if pyproject_text == pyproject_new:
        raise ShellError(f"Failed to update version in {PYPROJECT_FILE}")
    PYPROJECT_FILE.write_text(pyproject_new, encoding="utf-8")


def commit_version_bump(version: str) -> None:
    run(["git", "add", str(INIT_FILE), str(PYPROJECT_FILE)])
    run(["git", "commit", "-m", f"chore: bump version to {version}"])


def build_windows() -> None:
    run([sys.executable, "scripts/build_windows.py"])


def create_zip_bundle(version: str) -> Path:
    source_dir = REPO_ROOT / "dist" / "exif-turbo"
    if not source_dir.exists():
        raise ShellError(f"Missing expected build output directory: {source_dir}")

    zip_path = REPO_ROOT / "dist" / f"exif-turbo-{version}-windows.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in source_dir.rglob("*"):
            arcname = Path("exif-turbo") / path.relative_to(source_dir)
            if path.is_dir():
                continue
            zf.write(path, arcname)

    return zip_path


def create_and_push_tag(tag: str) -> None:
    existing = run(["git", "tag", "--list", tag], capture=True).strip()
    if existing:
        raise ShellError(f"Tag already exists locally: {tag}")
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    run(["git", "push", "origin", "main"])
    run(["git", "push", "origin", tag])


def create_release(
    *,
    repo: str,
    tag: str,
    version: str,
    msi: Path,
    bundle_zip: Path,
) -> None:
    if not msi.exists():
        raise ShellError(f"Missing expected MSI artifact: {msi}")
    if not bundle_zip.exists():
        raise ShellError(f"Missing expected ZIP artifact: {bundle_zip}")

    # Fail early if the release already exists.
    existing = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if existing.returncode == 0:
        raise ShellError(
            f"Release {tag} already exists on {repo}. "
            "Delete it first or use a new version."
        )

    run(
        [
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            repo,
            "--title",
            f"exif-turbo v{version}",
            "--notes",
            f"Release v{version}",
            str(msi),
            str(bundle_zip),
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bump version, build Windows binaries, create git tag, "
            "and publish a GitHub release."
        )
    )
    parser.add_argument("major", type=int, help="Major version number")
    parser.add_argument("minor", type=int, help="Minor version number")
    parser.add_argument("patch", type=int, help="Patch version number")
    parser.add_argument(
        "--repo",
        default="baddonkey/exif-turbo",
        help="GitHub repository in owner/repo format",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = f"{args.major}.{args.minor}.{args.patch}"
    tag = f"v{version}"

    try:
        ensure_tool("git")
        ensure_tool("gh")
        ensure_clean_tree()

        current = read_version()
        print(f"Current version: {current}")
        print(f"Target version : {version}")

        write_version(version)
        commit_version_bump(version)

        build_windows()
        msi = REPO_ROOT / "dist" / f"exif-turbo-{version}-windows.msi"
        bundle_zip = create_zip_bundle(version)

        create_and_push_tag(tag)
        create_release(
            repo=args.repo,
            tag=tag,
            version=version,
            msi=msi,
            bundle_zip=bundle_zip,
        )

        print("\nRelease completed successfully.")
        print(f"Tag        : {tag}")
        print(f"MSI        : {msi}")
        print(f"ZIP bundle : {bundle_zip}")
        print(f"URL        : https://github.com/{args.repo}/releases/tag/{tag}")
        return 0
    except ShellError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
