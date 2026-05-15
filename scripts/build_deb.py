"""Build the Debian package inside an Ubuntu 24.04 Podman container.

Ensures the bundle is linked against glibc 2.39 (Ubuntu 24.04 LTS),
making it compatible with any Debian/Ubuntu system on glibc >= 2.39.
The finished .deb is written to dist/ on the host.

Usage:
    python scripts/build_deb.py
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CONTAINER_IMAGE = "ubuntu:24.04"

CONTAINER_SCRIPT = """\
set -e
apt-get update -qq
apt-get install -y -q \
    python3 python3-pip python3-dev python3-venv dpkg \
    libnss3 libxfixes3 libxkbfile1 libxkbcommon0 libxkbcommon-x11-0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-render-util0 libxcb-render0 libxcb-shape0 libxcb-shm0 \
    libxcb-util1 libxcb-xkb1 libxcb-glx0 \
    libgbm1 libpango-1.0-0 libasound2t64 libpulse0 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxcomposite1 libxdamage1 libxrandr2 libxshmfence1 libtiff6
python3 -m venv /build-venv
. /build-venv/bin/activate
pip install --quiet -e '.[build]'
python scripts/build_linux.py --deb-only
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

    print(f"Building Debian package inside {CONTAINER_IMAGE} ...")
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
