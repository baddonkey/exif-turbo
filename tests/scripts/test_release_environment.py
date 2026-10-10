from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from scripts import (
    build_linux,
    build_macos,
    build_windows,
    release_environment,
    release_windows,
)


def test_ensure_release_environment_unlocked_process_runs_isolated_locked_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(release_environment, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("EXIF_TURBO_LOCKED_BUILD", raising=False)
    monkeypatch.setattr(sys, "argv", ["build_linux.py", "--deb-only"])
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def run(
        command: list[str], *, cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(release_environment.subprocess, "run", run)
    script = tmp_path / "scripts" / "build_linux.py"

    # Act / Assert
    with pytest.raises(SystemExit) as result:
        release_environment.ensure_release_environment(script)

    assert result.value.code == 7
    command, cwd, environment = calls[0]
    assert command[:5] == [sys.executable, "-m", "uv", "run", "--locked"]
    assert "--no-default-groups" in command
    assert command[command.index("--extra") + 1] == "build"
    assert command[command.index("--python") + 1] == sys.executable
    assert command[-3:] == ["python", str(script.resolve()), "--deb-only"]
    assert cwd == tmp_path
    assert Path(environment["UV_PROJECT_ENVIRONMENT"]).parent == tmp_path / "build"
    assert environment["EXIF_TURBO_LOCKED_BUILD"] == str(script.resolve())


def test_ensure_release_environment_locked_child_does_not_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(release_environment, "REPO_ROOT", tmp_path)
    script = tmp_path / "scripts" / "build_windows.py"
    environment = tmp_path / "build" / (
        f"release-venv-{sys.platform}-{release_environment.platform.machine()}-"
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
    monkeypatch.setenv("EXIF_TURBO_LOCKED_BUILD", str(script.resolve()))
    monkeypatch.setattr(sys, "prefix", str(environment))

    def run(*args: object, **kwargs: object) -> None:
        pytest.fail("A locked child must not restart the build")

    monkeypatch.setattr(release_environment.subprocess, "run", run)

    # Act
    release_environment.ensure_release_environment(script)

    # Assert
    assert os.environ["EXIF_TURBO_LOCKED_BUILD"] == str(script.resolve())


@pytest.mark.parametrize("builder", [build_windows, build_macos, build_linux])
def test_find_tool_global_packaging_tool_does_not_bypass_locked_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builder: ModuleType
) -> None:
    # Arrange
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(builder.shutil, "which", lambda name: "/global/pyinstaller")

    # Act / Assert
    with pytest.raises(SystemExit):
        builder.find_tool("pyinstaller", venv_subpath=".venv/bin/pyinstaller")


def test_release_lock_pytorch_packages_use_cpu_or_macos_sources() -> None:
    # Arrange
    root = Path(__file__).resolve().parents[2]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = lock["package"]

    # Act
    torch_packages = [
        package for package in packages if package["name"] in {"torch", "torchvision"}
    ]

    # Assert
    assert torch_packages
    for package in torch_packages:
        registry = package["source"]["registry"]
        if registry == "https://download.pytorch.org/whl/cpu":
            assert package["wheels"]
            assert all(wheel["hash"].startswith("sha256:") for wheel in package["wheels"])
        else:
            assert registry == "https://pypi.org/simple"
            assert all("macosx" in wheel["url"] for wheel in package["wheels"])
    assert not any(package["name"].startswith("nvidia-") for package in packages)


def test_write_version_release_bump_refreshes_and_stages_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    init = tmp_path / "__init__.py"
    project = tmp_path / "pyproject.toml"
    metadata = tmp_path / "version_info.py"
    lock = tmp_path / "uv.lock"
    init.write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    project.write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    monkeypatch.setattr(release_windows, "INIT_FILE", init)
    monkeypatch.setattr(release_windows, "PYPROJECT_FILE", project)
    monkeypatch.setattr(release_windows, "VERSION_INFO_FILE", metadata)
    monkeypatch.setattr(release_windows, "LOCK_FILE", lock)
    commands: list[list[str]] = []

    def run(command: list[str], *, capture: bool = False) -> str:
        commands.append(command)
        return ""

    monkeypatch.setattr(release_windows, "run", run)

    # Act
    release_windows.write_version("1.0.1")
    release_windows.commit_version_bump("1.0.1")

    # Assert
    assert commands[0] == [sys.executable, "-m", "uv", "lock", "--offline"]
    assert str(lock) in commands[1]
    assert 'version = "1.0.1"' in project.read_text(encoding="utf-8")