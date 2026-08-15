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
import re
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
    libxcomposite1 libxdamage1 libxrandr2 libxshmfence1 libtiff6 \
    libminizip1t64
python3 -m venv /build-venv
. /build-venv/bin/activate
pip install --quiet \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    torch torchvision
pip install --quiet --index-url https://pypi.org/simple -e '.[build]'
python scripts/build_linux.py --deb-only --deb-arch "${TARGET_DEB_ARCH}"
"""

ARCH_TO_PLATFORM: dict[str, str] = {
    "amd64": "linux/amd64",
    "arm64": "linux/arm64",
}


def _read_version() -> str:
    init_file = REPO_ROOT / "src" / "exif_turbo" / "__init__.py"
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", init_file.read_text())
    if not match:
        return ""
    return match.group(1)


def _podman_machine_os_id() -> str | None:
    """Return Podman machine OS ID from /etc/os-release, or None on failure."""
    probe = subprocess.run(
        ["podman", "machine", "ssh", "cat /etc/os-release"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    for line in probe.stdout.splitlines():
        if line.startswith("ID="):
            return line.split("=", 1)[1].strip().strip('"').lower()
    return None


def _arm64_recovery_instructions() -> str:
    """Return host-specific commands to enable arm64 emulation in Podman machine."""
    os_id = _podman_machine_os_id()
    if os_id in {"fedora", "rhel", "centos"}:
        return (
            "  podman machine ssh \"sudo dnf install -y qemu-user-static\"\n"
            "  podman machine ssh \"sudo systemctl restart systemd-binfmt || true\"\n"
            "  podman machine ssh \"sudo podman run --privileged --rm docker.io/tonistiigi/binfmt --install arm64\"\n"
            "  podman machine stop\n"
            "  podman machine start"
        )
    if os_id in {"debian", "ubuntu"}:
        return (
            "  podman machine ssh \"sudo apt-get update && sudo apt-get install -y qemu-user-static binfmt-support\"\n"
            "  podman machine ssh \"sudo podman run --privileged --rm docker.io/tonistiigi/binfmt --install arm64\"\n"
            "  podman machine stop\n"
            "  podman machine start"
        )
    return (
        "  # Fedora-based Podman machine:\n"
        "  podman machine ssh \"sudo dnf install -y qemu-user-static\"\n"
        "  podman machine ssh \"sudo systemctl restart systemd-binfmt || true\"\n"
        "  podman machine ssh \"sudo podman run --privileged --rm docker.io/tonistiigi/binfmt --install arm64\"\n"
        "\n"
        "  # Debian/Ubuntu-based Podman machine:\n"
        "  podman machine ssh \"sudo apt-get update && sudo apt-get install -y qemu-user-static binfmt-support\"\n"
        "  podman machine ssh \"sudo podman run --privileged --rm docker.io/tonistiigi/binfmt --install arm64\"\n"
        "  podman machine stop\n"
        "  podman machine start"
    )


def _try_enable_arm64_emulation() -> None:
    """Best-effort emulation bootstrap inside Podman machine."""
    os_id = _podman_machine_os_id()
    if os_id in {"fedora", "rhel", "centos"}:
        cmds = [
            "sudo dnf install -y qemu-user-static",
            "sudo systemctl restart systemd-binfmt || true",
        ]
    elif os_id in {"debian", "ubuntu"}:
        cmds = [
            "sudo apt-get update && sudo apt-get install -y qemu-user-static binfmt-support",
        ]
    else:
        return

    print("Attempting automatic arm64 emulation bootstrap in Podman machine ...")
    for c in cmds:
        subprocess.run(
            ["podman", "machine", "ssh", c],
            cwd=REPO_ROOT,
            check=False,
        )

    # Fallback for environments where systemd-binfmt is present but broken.
    subprocess.run(
        [
            "podman",
            "machine",
            "ssh",
            "sudo podman run --privileged --rm docker.io/tonistiigi/binfmt --install arm64",
        ],
        cwd=REPO_ROOT,
        check=False,
    )


def run(cmd: list[str], *, check: bool = True) -> int:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if check and result.returncode != 0:
        print(f"ERROR: Command failed ({result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)
    return result.returncode


def _ensure_arm64_platform_available(*, strict: bool = True) -> bool:
    """Check arm64 container execution support.

    When strict is True, exits with actionable guidance if unavailable.
    When strict is False, prints a warning and returns False.
    """
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
        return True

    details = (probe.stderr or probe.stdout).strip()
    if "Exec format error" in details:
        recovery = _arm64_recovery_instructions()
        msg = (
            "arm64 container execution is not available on this host.\n"
            "Podman can pull linux/arm64 images, but cannot execute them without\n"
            "binfmt/qemu emulation support inside the Podman machine.\n\n"
            "Suggested fix (Windows/macOS Podman machine):\n"
            f"{recovery}\n\n"
            "Then rerun: python scripts/build_deb.py --arch arm64\n"
            "Alternatively, run this command on a native arm64 host (e.g. Raspberry Pi 5)."
        )
        if strict:
            print(f"ERROR: {msg}", file=sys.stderr)
            sys.exit(1)
        print(f"WARNING: {msg}", file=sys.stderr)
        return False

    if strict:
        print(f"ERROR: arm64 probe failed: {details}", file=sys.stderr)
        sys.exit(1)
    print(f"WARNING: arm64 probe failed: {details}", file=sys.stderr)
    return False


def _build_arch(arch: str, *, strict_arm64: bool = True) -> bool:
    platform_name = ARCH_TO_PLATFORM[arch]
    if arch == "arm64":
        if not _ensure_arm64_platform_available(strict=False):
            _try_enable_arm64_emulation()
            if not _ensure_arm64_platform_available(strict=strict_arm64):
                return False
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
    return True


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
    built: list[str] = []
    skipped: list[str] = []
    for arch in targets:
        strict_arm64 = True
        if _build_arch(arch, strict_arm64=strict_arm64):
            built.append(arch)
        else:
            skipped.append(arch)

    print()
    if built:
        print(f"Built: {', '.join(built)}")
    if skipped:
        print(f"Skipped: {', '.join(skipped)}")
        version = _read_version()
        for arch in skipped:
            if not version:
                break
            stale = REPO_ROOT / "dist" / f"exif-turbo-{version}-linux-{arch}.deb"
            if stale.exists():
                print(
                    f"WARNING: Existing artifact was NOT rebuilt for {arch}: {stale}\n"
                    "         It may be stale. Do not distribute/install it as the current build output."
                )
    print("Done. Package(s) are in dist/.")


if __name__ == "__main__":
    main()
