from __future__ import annotations

from pathlib import Path
import runpy

import pytest

from scripts import build_deb, build_rpm


_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_linux_container_builds_resolve_project_dependencies_from_pypi() -> None:
    # Arrange
    torch_dependency_index = "--extra-index-url https://pypi.org/simple"
    project_install = (
        "pip install --quiet --index-url https://pypi.org/simple -e '.[build]'"
    )

    # Act
    scripts = (build_deb.CONTAINER_SCRIPT, build_rpm.CONTAINER_SCRIPT)

    # Assert
    assert all(
        torch_dependency_index in script and project_install in script
        for script in scripts
    )


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