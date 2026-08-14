from __future__ import annotations

from email.message import Message
from importlib.metadata import Distribution, PackagePath
from pathlib import Path
from typing import cast

import pytest

from scripts import stage_runtime_licenses


class FakeDistribution:
    def __init__(
        self,
        root: Path,
        name: str,
        version: str,
        *,
        requires: tuple[str, ...] = (),
        license_files: dict[str, str] | None = None,
    ) -> None:
        self._root = root
        self.metadata = Message()
        self.metadata["Name"] = name
        self.metadata["License-Expression"] = "MIT"
        self.version = version
        self.requires = requires
        self.files: list[PackagePath] = []
        for filename, contents in (license_files or {}).items():
            relative = PackagePath(f"{name}-{version}.dist-info/licenses/{filename}")
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
            self.files.append(relative)

    def locate_file(self, path: PackagePath) -> Path:
        return self._root / path


def _as_distribution(package: FakeDistribution) -> Distribution:
    return cast(Distribution, package)


def _write_project_notices(project_root: Path) -> None:
    (project_root / "LICENSE").write_text("project terms", encoding="utf-8")
    (project_root / "THIRD-PARTY-LICENSES.md").write_text(
        "dependency notices", encoding="utf-8"
    )


def test_runtime_distributions_transitive_and_inactive_marker_resolves_active_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    root = FakeDistribution(
        tmp_path,
        "Root-Package",
        "1.0",
        requires=("child-package[feature]>=2", 'unused-package; python_version < "3"'),
    )
    child = FakeDistribution(
        tmp_path,
        "child-package",
        "2.0",
        requires=('optional-package; extra == "feature"',),
    )
    optional = FakeDistribution(tmp_path, "optional-package", "3.0")
    packages = {
        "Root-Package": root,
        "child-package": child,
        "optional-package": optional,
    }
    monkeypatch.setattr(
        stage_runtime_licenses,
        "distribution",
        lambda name: _as_distribution(packages[name]),
    )

    # Act
    resolved = stage_runtime_licenses._runtime_distributions(("Root-Package",))

    # Assert
    assert [package.metadata["Name"] for package in resolved] == [
        "child-package",
        "optional-package",
        "Root-Package",
    ]


def test_stage_runtime_licenses_installed_package_copies_complete_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project_notices(project_root)
    package = FakeDistribution(
        tmp_path,
        "Demo-Package",
        "1.2.3",
        license_files={"LICENSE.txt": "demo terms", "NOTICE": "demo notice"},
    )
    monkeypatch.setattr(stage_runtime_licenses, "REPO_ROOT", project_root)
    python_license = tmp_path / "PYTHON-LICENSE.txt"
    python_license.write_text("Python terms", encoding="utf-8")
    monkeypatch.setattr(
        stage_runtime_licenses, "_python_license_file", lambda: python_license
    )
    monkeypatch.setattr(
        stage_runtime_licenses,
        "distribution",
        lambda _name: _as_distribution(package),
    )
    output_dir = tmp_path / "staged"

    # Act
    stage_runtime_licenses.stage_runtime_licenses(
        output_dir, requirements=("Demo-Package",)
    )

    # Assert
    assert (output_dir / "PROJECT-LICENSE.txt").read_text(encoding="utf-8") == (
        "project terms"
    )
    assert (output_dir / "CPYTHON-LICENSE.txt").read_text(
        encoding="utf-8"
    ) == "Python terms"
    assert (output_dir / "STAGING-COMPLETE").is_file()
    assert (
        output_dir / "python" / "demo-package-1.2.3" / "LICENSE.txt"
    ).read_text(encoding="utf-8") == "demo terms"
    assert "Demo-Package 1.2.3 [MIT]" in (
        output_dir / "PYTHON-RUNTIME-LICENSES.txt"
    ).read_text(encoding="utf-8")


def test_stage_runtime_licenses_package_without_license_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project_notices(project_root)
    package = FakeDistribution(tmp_path, "Missing-License", "1.0")
    monkeypatch.setattr(stage_runtime_licenses, "REPO_ROOT", project_root)
    monkeypatch.setattr(
        stage_runtime_licenses,
        "distribution",
        lambda _name: _as_distribution(package),
    )
    output_dir = tmp_path / "staged"
    output_dir.mkdir()
    (output_dir / "STAGING-COMPLETE").write_text("previous\n", encoding="ascii")

    # Act
    with pytest.raises(
        stage_runtime_licenses.LicenseStagingError,
        match="runtime distribution has no packaged license file: Missing-License 1.0",
    ):
        stage_runtime_licenses.stage_runtime_licenses(
            output_dir, requirements=("Missing-License",)
        )

    # Assert
    assert (output_dir / "STAGING-COMPLETE").read_text(encoding="ascii") == (
        "previous\n"
    )