"""Cut a Windows release for a specific semantic version.

Given ``major minor patch`` this script will:

Prepare-PR stage (default):
1. Bump version in ``src/exif_turbo/__init__.py`` and ``pyproject.toml``.
2. Commit the version bump on the current branch.
3. Push the branch and create (or reuse) a PR to ``main``.

Publish stage (``--stage publish``):
1. Build Windows artifacts via ``scripts/build_windows.py``.
2. Create and push an annotated git tag ``v<version>``.
3. Create a GitHub release and upload Windows binaries.

Uploaded assets:
    - dist/exif-turbo-<version>-windows.msi
    - dist/exif-turbo-<version>-windows.zip (zipped onedir bundle)

Usage:
    python scripts/release_windows.py 1 15 0
    python scripts/release_windows.py 1 15 0 --stage publish
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


def current_branch() -> str:
    branch = run(["git", "branch", "--show-current"], capture=True).strip()
    if not branch:
        raise ShellError("Could not determine current git branch")
    return branch


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


def push_branch(branch: str) -> None:
    run(["git", "push", "-u", "origin", branch])


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
    run(["git", "fetch", "origin", "--tags"])
    existing = run(["git", "tag", "--list", tag], capture=True).strip()
    if existing:
        raise ShellError(f"Tag already exists locally: {tag}")

    remote_existing = run(
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"],
        capture=True,
    ).strip()
    if remote_existing:
        raise ShellError(f"Tag already exists on origin: {tag}")

    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    run(["git", "push", "origin", tag])


def create_or_reuse_pr(*, repo: str, branch: str, version: str) -> str:
    existing_url = run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--head",
            branch,
            "--base",
            "main",
            "--state",
            "open",
            "--json",
            "url",
            "--jq",
            ".[0].url",
        ],
        capture=True,
    ).strip()
    if existing_url:
        return existing_url

    body = (
        f"Prepare release v{version}.\n\n"
        "This PR bumps project version metadata for the release.\n"
        "After merge, run:\n"
        f"python scripts/release_windows.py {version.replace('.', ' ')} --stage publish"
    )
    return run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            repo,
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            f"chore: prepare release v{version}",
            "--body",
            body,
        ],
        capture=True,
    ).strip()


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
            "Prepare a PR for a release version bump or publish a merged release."
        )
    )
    parser.add_argument("major", type=int, help="Major version number")
    parser.add_argument("minor", type=int, help="Minor version number")
    parser.add_argument("patch", type=int, help="Patch version number")
    parser.add_argument(
        "--stage",
        choices=["prepare-pr", "publish"],
        default="prepare-pr",
        help=(
            "prepare-pr: bump version, commit, push branch, and open PR. "
            "publish: build artifacts, tag, and create GitHub release."
        ),
    )
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

        if args.stage == "prepare-pr":
            branch = current_branch()
            if branch == "main":
                raise ShellError(
                    "Refusing to run prepare-pr on 'main'. "
                    "Create/use a release branch and re-run."
                )
            if current == version:
                raise ShellError(
                    f"Version is already {version}. Nothing to bump for PR."
                )

            write_version(version)
            commit_version_bump(version)
            push_branch(branch)
            pr_url = create_or_reuse_pr(
                repo=args.repo,
                branch=branch,
                version=version,
            )

            print("\nPR preparation completed successfully.")
            print(f"Branch     : {branch}")
            print(f"PR         : {pr_url}")
            print(
                "Next step  : merge the PR, then run this script with "
                "'--stage publish' from main."
            )
            return 0

        branch = current_branch()
        if branch != "main":
            raise ShellError(
                "Publish stage must run from 'main' after the release PR is merged."
            )
        if current != version:
            raise ShellError(
                "Publish stage requires main to already contain the target version. "
                "Merge the release PR first."
            )

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
