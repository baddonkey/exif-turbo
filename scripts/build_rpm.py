"""Build the RPM package inside an AlmaLinux 9 Podman container.

Ensures the bundle is linked against glibc 2.34 (AlmaLinux 9 / RHEL 9),
making it compatible with RHEL 9, AlmaLinux 9, Rocky Linux 9, and
Fedora releases that carry glibc >= 2.34.
The finished .rpm is written to dist/ on the host.

Usage:
    python scripts/build_rpm.py
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CONTAINER_IMAGE = "almalinux:9"

CONTAINER_SCRIPT = """\
set -e
dnf install -y -q python3.11 python3.11-devel python3-pip rpm-build
python3.11 -m venv /build-venv
. /build-venv/bin/activate
pip install --quiet -e '.[build]'
python scripts/build_linux.py --rpm-only
"""


def run(cmd: list[str], *, check: bool = True) -> int:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if check and result.returncode != 0:
        print(f"ERROR: Command failed ({result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)
    return result.returncode


def main() -> None:
    if platform.system() == "Windows":
        print("Ensuring Podman machine is running ...")
        run(["podman", "machine", "start"], check=False)

    print(f"Building RPM package inside {CONTAINER_IMAGE} ...")
    run([
        "podman", "run", "--rm",
        "-v", f"{REPO_ROOT}:/workspace",
        "-w", "/workspace",
        CONTAINER_IMAGE,
        "bash", "-c", CONTAINER_SCRIPT,
    ])

    print()
    print("Done. Package is in dist/.")


if __name__ == "__main__":
    main()
