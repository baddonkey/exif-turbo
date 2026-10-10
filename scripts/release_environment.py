"""Run release builds with the committed dependency lock in an isolated environment."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

UV_VERSION = "0.13.0"
REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD_MARKER = "EXIF_TURBO_LOCKED_BUILD"


def ensure_release_environment(script: Path) -> None:
    script = script.resolve()
    environment = REPO_ROOT / "build" / (
        f"release-venv-{sys.platform}-{platform.machine()}-"
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
    if (
        os.environ.get(_BUILD_MARKER) == str(script)
        and Path(sys.prefix).resolve() == environment.resolve()
    ):
        return

    child_environment = os.environ.copy()
    child_environment["UV_PROJECT_ENVIRONMENT"] = str(environment)
    child_environment[_BUILD_MARKER] = str(script)
    command = [
        sys.executable,
        "-m",
        "uv",
        "run",
        "--locked",
        "--no-default-groups",
        "--extra",
        "build",
        "--python",
        sys.executable,
        "--no-managed-python",
        "--project",
        str(REPO_ROOT),
        "python",
        str(script),
        *sys.argv[1:],
    ]
    print(f"Using locked release dependencies in {environment}", flush=True)
    result = subprocess.run(command, cwd=REPO_ROOT, env=child_environment)
    raise SystemExit(result.returncode)