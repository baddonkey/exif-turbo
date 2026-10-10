from __future__ import annotations

from pathlib import Path
import runpy
import tomllib

import pytest

from scripts import build_deb, build_rpm, release_environment


_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_linux_container_builds_pinned_bootstrap_preserves_explicit_cpu_source() -> None:
    # Arrange
    bootstrap = (
        "pip install --quiet --index-url https://pypi.org/simple "
        f"uv=={release_environment.UV_VERSION}"
    )
    project = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    # Act
    scripts = (build_deb.CONTAINER_SCRIPT, build_rpm.CONTAINER_SCRIPT)
    cpu_index = next(
        index for index in project["tool"]["uv"]["index"]
        if index["name"] == "pytorch-cpu"
    )

    # Assert
    assert all(bootstrap in script for script in scripts)
    assert all("-e '.[build]'" not in script for script in scripts)
    assert all("torch torchvision" not in script for script in scripts)
    assert cpu_index["explicit"] is True
    assert cpu_index["url"] == "https://download.pytorch.org/whl/cpu"
    assert project["tool"]["uv"]["sources"]["torch"][0]["index"] == "pytorch-cpu"
    assert project["tool"]["uv"]["sources"]["torchvision"][0]["index"] == "pytorch-cpu"


def test_rpm_spec_explicitly_collects_qt_webengine_binary_payload() -> None:
    # Arrange / Act
    source = (_REPO_ROOT / "exif-turbo-rpm.spec").read_text(encoding="utf-8")

    # Assert
    assert "collect_all('PySide6.QtWebEngineCore')" in source
    assert "collect_all('PySide6.QtWebEngineQuick')" in source
    assert "binaries=_wec_bins + _weq_bins" in source


@pytest.mark.parametrize(
    "native_names",
    [("_C.so", "image.so"), ("_C.pyd", "image.pyd"), ("_C.dylib", "image.dylib")],
)
def test_torchvision_hook_native_libraries_collected_in_package_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_names: tuple[str, str],
) -> None:
    # Arrange
    from PyInstaller.utils import hooks

    hook_path = _REPO_ROOT / "hooks" / "hook-torchvision.py"
    package_dir = tmp_path / "torchvision"
    package_dir.mkdir()
    for name in native_names:
        (package_dir / name).write_bytes(b"native library")
    (package_dir / "extension.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(hooks, "is_package", lambda package: package == "torchvision")
    monkeypatch.setattr(hooks, "get_all_package_paths", lambda package: [str(package_dir)])

    # Act
    hook = runpy.run_path(str(hook_path))

    # Assert
    assert set(hook["binaries"]) == {
        (str(package_dir / name), "torchvision") for name in native_names
    }