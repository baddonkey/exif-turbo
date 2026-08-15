from __future__ import annotations

from pathlib import Path

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