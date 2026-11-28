"""Build and stage the pinned Vec1 SQLite extension for Unix releases."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

_COMMIT = "803d64f73ba09b9a0ea338b5c621493ac857d1e3"
_SOURCE_URL = f"https://raw.githubusercontent.com/sqlite/sqlite/{_COMMIT}/ext/vec1/vec1.c"
_SOURCE_SHA256 = "2fdaf637bf06639780f4c26ee165dbdbaa50849362f87d86e8388537567a2701"
_HEADERS_URL = "https://www.sqlite.org/2025/sqlite-amalgamation-3510100.zip"
_HEADERS_SHA256 = "84a85d6a1b920234349f01720912c12391a4f0cb5cb998087e641dee3ef8ef2e"
STAGE_ENV = "EXIF_TURBO_BUILD_VEC1_STAGE"


def binary_name(system: str, machine: str) -> str | None:
    if system == "linux" and machine in {"x86_64", "aarch64"}:
        return "vec1.so"
    if system == "darwin" and machine == "arm64":
        return "vec1.dylib"
    return None


def _download_verified(url: str, destination: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=300) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch for {url}")


@contextmanager
def staged_vec1(build_dir: Path, *, sign_identity: str | None = None) -> Generator[Path]:
    """Create a private build stage; reject unsupported release targets."""
    system, machine = sys.platform, platform.machine()
    name = binary_name(system, machine)
    if name is None:
        raise RuntimeError(f"Vec1 is unavailable for release target {system}/{machine}")

    build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vec1-unix-", dir=build_dir) as work:
        root = Path(work)
        source, headers = root / "vec1.c", root / "headers.zip"
        _download_verified(_SOURCE_URL, source, _SOURCE_SHA256)
        _download_verified(_HEADERS_URL, headers, _HEADERS_SHA256)
        include = root / "include"
        include.mkdir()
        with zipfile.ZipFile(headers) as archive:
            for header in ("sqlite3.h", "sqlite3ext.h"):
                (include / header).write_bytes(
                    archive.read(f"sqlite-amalgamation-3510100/{header}")
                )

        outputs = []
        for index in range(2):
            output = root / f"build-{index}" / name
            output.parent.mkdir()
            command = [
                "cc", "-O2", "-fPIC", "-I", str(include),
                "-dynamiclib" if system == "darwin" else "-shared",
            ]
            if system == "darwin":
                command += ["-arch", "arm64", "-Wl,-install_name,@rpath/vec1.dylib"]
            else:
                command += ["-Wl,-z,defs"]
            command.append(str(source))
            if system == "linux":
                command.append("-lm")
            command += ["-o", str(output)]
            subprocess.run(command, cwd=root, check=True)
            outputs.append(output.read_bytes())
        if outputs[0] != outputs[1]:
            raise RuntimeError("The Vec1 Unix build is not reproducible")

        stage = root / "stage"
        stage.mkdir()
        binary = stage / name
        binary.write_bytes(outputs[0])
        if system == "darwin":
            command = ["codesign", "--force"]
            if sign_identity:
                command += ["--options", "runtime", "--sign", sign_identity, "--timestamp"]
            else:
                command += ["--sign", "-"]
            subprocess.run([*command, str(binary)], check=True)
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        (stage / "_vec1_release_hash.py").write_text(
            f'EXPECTED_SHA256 = "{digest}"\n', encoding="ascii"
        )
        yield stage


def spec_inputs() -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Return spec inputs only when explicitly staged by the release script."""
    stage = os.environ.get(STAGE_ENV)
    if not stage:
        return [], [], []
    root = Path(stage)
    name = binary_name(sys.platform, platform.machine())
    if name is None or not (root / name).is_file() or not (root / "_vec1_release_hash.py").is_file():
        raise RuntimeError("Invalid Vec1 build stage")
    return [str(root)], [(str(root / name), "exif_turbo/assets/native")], ["_vec1_release_hash"]


def verify_staged_binary(stage: Path, binary: Path) -> None:
    """Fail closed if PyInstaller or signing changed the packaged native code."""
    import re

    manifest = (stage / "_vec1_release_hash.py").read_text(encoding="ascii")
    match = re.fullmatch(r'EXPECTED_SHA256 = "([0-9a-f]{64})"\n', manifest)
    if match is None or not binary.is_file() or binary.is_symlink():
        raise RuntimeError("The packaged Vec1 binary or digest is missing or invalid")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != match.group(1):
        raise RuntimeError("The packaged Vec1 binary changed after its digest was generated")
