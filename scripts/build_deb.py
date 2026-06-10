"""Build the Debian package inside an Ubuntu 24.04 Podman container.

Ensures the bundle is linked against glibc 2.39 (Ubuntu 24.04 LTS),
making it compatible with any Debian/Ubuntu system on glibc >= 2.39.
By default it builds both amd64 and arm64 packages (the latter targets
Raspberry Pi 5 / Debian arm64) and writes them to dist/ on the host.

Usage:
    python scripts/build_deb.py
    python scripts/build_deb.py --arch amd64
    python scripts/build_deb.py --arch arm64
"""

from __future__ import annotations

import argparse
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
pip install --quiet --index-url https://download.pytorch.org/whl/cpu torch torchvision
pip install --quiet -e '.[build]'
python scripts/build_linux.py --deb-only --deb-arch "${TARGET_DEB_ARCH}"
"""

ARCH_TO_PLATFORM: dict[str, str] = {
    "amd64": "linux/amd64",
    "arm64": "linux/arm64",
}


def run(cmd: list[str], *, check: bool = True) -> int:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if check and result.returncode != 0:
        print(f"ERROR: Command failed ({result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)
    return result.returncode


def _ensure_arm64_platform_available() -> None:
    """Fail fast with actionable guidance when arm64 container emulation is missing."""
    probe = subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "--platform",
            "linux/arm64",
            CONTAINER_IMAGE,
            "bash",
            "-lc",
            "true",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode == 0:
        return

    details = (probe.stderr or probe.stdout).strip()
    if "Exec format error" in details:
        print(
            "ERROR: arm64 container execution is not available on this host.\n"
            "Podman can pull linux/arm64 images, but cannot execute them without\n"
            "binfmt/qemu emulation support inside the Podman machine.\n\n"
            "Suggested fix (Windows/macOS Podman machine):\n"
            "  podman machine ssh \"sudo apt-get update && sudo apt-get install -y qemu-user-static binfmt-support\"\n"
            "  podman machine stop\n"
            "  podman machine start\n\n"
            "Then rerun: python scripts/build_deb.py --arch arm64\n"
            "Alternatively, run this command on a native arm64 host (e.g. Raspberry Pi 5).",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"ERROR: arm64 probe failed: {details}", file=sys.stderr)
    sys.exit(1)


def _build_arch(arch: str) -> None:
    platform_name = ARCH_TO_PLATFORM[arch]
    if arch == "arm64":
        _ensure_arm64_platform_available()
    print(f"Building Debian package ({arch}) inside {CONTAINER_IMAGE} ...")
    run([
        "podman", "run", "--rm",
        "--platform", platform_name,
        "-e", f"TARGET_DEB_ARCH={arch}",
        "-v", f"{REPO_ROOT}:/workspace",
        "-w", "/workspace",
        CONTAINER_IMAGE,
        "bash", "-c", CONTAINER_SCRIPT,
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arch",
        choices=("all", "amd64", "arm64"),
        default="all",
        help="Target DEB architecture(s). Default: all (amd64 + arm64).",
    )
    args = parser.parse_args()

    if platform.system() == "Windows":
        print("Ensuring Podman machine is running ...")
        run(["podman", "machine", "start"], check=False)

    targets = ["amd64", "arm64"] if args.arch == "all" else [args.arch]
    for arch in targets:
        _build_arch(arch)

    print()
    print("Done. Package(s) are in dist/.")


if __name__ == "__main__":
    main()
