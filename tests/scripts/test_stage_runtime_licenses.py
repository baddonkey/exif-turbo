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
        native_files: dict[str, str] | None = None,
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
        for filename, contents in (native_files or {}).items():
            relative = PackagePath(filename)
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


def test_python_license_file_homebrew_framework_returns_formula_license(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    formula_root = tmp_path / "python@3.14"
    installed_base = (
        formula_root / "Frameworks" / "Python.framework" / "Versions" / "3.14"
    )
    installed_base.mkdir(parents=True)
    license_file = formula_root / "LICENSE"
    license_file.write_text("Python terms", encoding="utf-8")
    monkeypatch.setattr(
        stage_runtime_licenses.sysconfig,
        "get_config_var",
        lambda _name: str(installed_base),
    )

    # Act
    result = stage_runtime_licenses._python_license_file()

    # Assert
    assert result == license_file


def test_python_license_file_ubuntu_returns_versioned_package_copyright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    installed_base = tmp_path / "usr"
    license_file = installed_base / "share" / "doc" / "python3.12" / "copyright"
    license_file.parent.mkdir(parents=True)
    license_file.write_text("Python terms", encoding="utf-8")
    config_vars = {
        "installed_base": str(installed_base),
        "py_version_short": "3.12",
    }
    monkeypatch.setattr(
        stage_runtime_licenses.sysconfig,
        "get_config_var",
        config_vars.get,
    )

    # Act
    result = stage_runtime_licenses._python_license_file()

    # Assert
    assert result == license_file


def test_python_license_file_almalinux_returns_stdlib_license(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    installed_base = tmp_path / "usr"
    stdlib = installed_base / "lib64" / "python3.11"
    license_file = stdlib / "LICENSE.txt"
    license_file.parent.mkdir(parents=True)
    license_file.write_text("Python terms", encoding="utf-8")
    config_vars = {
        "installed_base": str(installed_base),
        "py_version_short": "3.11",
    }
    monkeypatch.setattr(
        stage_runtime_licenses.sysconfig,
        "get_config_var",
        config_vars.get,
    )
    monkeypatch.setattr(
        stage_runtime_licenses.sysconfig,
        "get_path",
        lambda _name: str(stdlib),
    )

    # Act
    result = stage_runtime_licenses._python_license_file()

    # Assert
    assert result == license_file


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


def test_stage_runtime_licenses_sentencepiece_without_license_uses_upstream_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project_notices(project_root)
    package = FakeDistribution(tmp_path, "sentencepiece", "0.2.2")
    package.metadata.replace_header("License-Expression", "Apache-2.0")
    python_license = tmp_path / "PYTHON-LICENSE.txt"
    python_license.write_text("Python terms", encoding="utf-8")
    upstream_license = tmp_path / "Apache-2.0.txt"
    upstream_license.write_text("Apache terms", encoding="utf-8")
    monkeypatch.setattr(stage_runtime_licenses, "REPO_ROOT", project_root)
    monkeypatch.setattr(
        stage_runtime_licenses, "_python_license_file", lambda: python_license
    )
    monkeypatch.setattr(
        stage_runtime_licenses,
        "_upstream_package_license_files",
        lambda _package: (upstream_license,),
    )
    monkeypatch.setattr(
        stage_runtime_licenses,
        "distribution",
        lambda _name: _as_distribution(package),
    )
    output_dir = tmp_path / "staged"

    # Act
    stage_runtime_licenses.stage_runtime_licenses(
        output_dir, requirements=("sentencepiece",)
    )

    # Assert
    assert (
        output_dir / "python" / "sentencepiece-0.2.2" / "Apache-2.0.txt"
    ).read_text(encoding="utf-8") == "Apache terms"
    manifest = (output_dir / "PYTHON-RUNTIME-LICENSES.txt").read_text(
        encoding="utf-8"
    )
    assert "sentencepiece 0.2.2 [Apache-2.0]" in manifest
    assert "python/sentencepiece-0.2.2/Apache-2.0.txt" in manifest


def test_upstream_package_license_files_classifier_and_valid_cache_returns_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    package = FakeDistribution(tmp_path, "tokenizers", "0.22.2")
    del package.metadata["License-Expression"]
    package.metadata["Classifier"] = (
        "License :: OSI Approved :: Apache Software License"
    )
    cached_license = (
        tmp_path
        / "build"
        / "license-cache"
        / "python"
        / "tokenizers"
        / "0.22.2"
        / "Apache-2.0.txt"
    )
    cached_license.parent.mkdir(parents=True)
    cached_license.write_text(
        "Apache License\n" + ("license text\n" * 1_000) + "END OF TERMS AND CONDITIONS\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(stage_runtime_licenses, "REPO_ROOT", tmp_path)

    # Act
    result = stage_runtime_licenses._upstream_package_license_files(
        _as_distribution(package)
    )

    # Assert
    assert result == (cached_license,)


def test_stage_runtime_licenses_qt_wheels_without_licenses_use_upstream_texts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project_notices(project_root)
    packages = {
        "PySide6": FakeDistribution(
            tmp_path,
            "PySide6",
            "6.11.1",
            requires=("PySide6-Essentials", "PySide6-Addons", "shiboken6"),
        ),
        "PySide6-Essentials": FakeDistribution(
            tmp_path, "PySide6-Essentials", "6.11.1"
        ),
        "PySide6-Addons": FakeDistribution(tmp_path, "PySide6-Addons", "6.11.1"),
        "shiboken6": FakeDistribution(tmp_path, "shiboken6", "6.11.1"),
    }
    python_license = tmp_path / "PYTHON-LICENSE.txt"
    python_license.write_text("Python terms", encoding="utf-8")
    qt_license = tmp_path / "LGPL-3.0-only.txt"
    qt_license.write_text("Qt terms", encoding="utf-8")
    monkeypatch.setattr(stage_runtime_licenses, "REPO_ROOT", project_root)
    monkeypatch.setattr(
        stage_runtime_licenses, "_python_license_file", lambda: python_license
    )
    monkeypatch.setattr(
        stage_runtime_licenses, "_qt_license_files", lambda _version: (qt_license,)
    )
    monkeypatch.setattr(
        stage_runtime_licenses,
        "distribution",
        lambda name: _as_distribution(packages[name]),
    )
    output_dir = tmp_path / "staged"

    # Act
    stage_runtime_licenses.stage_runtime_licenses(
        output_dir, requirements=("PySide6",)
    )

    # Assert
    assert (output_dir / "qt" / "6.11.1" / "LGPL-3.0-only.txt").read_text(
        encoding="utf-8"
    ) == "Qt terms"
    manifest = (output_dir / "PYTHON-RUNTIME-LICENSES.txt").read_text(
        encoding="utf-8"
    )
    assert all(f"{name} 6.11.1" in manifest for name in packages)
    assert "qt/6.11.1/LGPL-3.0-only.txt" in manifest


def test_stage_runtime_licenses_pyvips_binary_adds_native_compliance_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project_notices(project_root)
    package = FakeDistribution(
        tmp_path,
        "pyvips-binary",
        "8.18.4",
        license_files={"LICENSE": "wrapper terms"},
        native_files={"pyvips_binary.libs/libvips-42.dll": "native library"},
    )
    python_license = tmp_path / "PYTHON-LICENSE.txt"
    python_license.write_text("Python terms", encoding="utf-8")
    native_license = tmp_path / "LIBVIPS-LGPL-2.1.txt"
    native_license.write_text("LGPL terms", encoding="utf-8")
    monkeypatch.setattr(stage_runtime_licenses, "REPO_ROOT", project_root)
    monkeypatch.setattr(
        stage_runtime_licenses, "_python_license_file", lambda: python_license
    )
    monkeypatch.setattr(
        stage_runtime_licenses,
        "_libvips_license_files",
        lambda _version: (native_license,),
    )
    monkeypatch.setattr(
        stage_runtime_licenses,
        "distribution",
        lambda _name: _as_distribution(package),
    )
    output_dir = tmp_path / "staged"

    # Act
    stage_runtime_licenses.stage_runtime_licenses(
        output_dir, requirements=("pyvips-binary",)
    )

    # Assert
    libvips_dir = output_dir / "libvips" / "8.18.4"
    assert (libvips_dir / "LIBVIPS-LGPL-2.1.txt").read_text(
        encoding="utf-8"
    ) == "LGPL terms"
    assert "libvips-packaging/tree/v8.18.4" in (
        libvips_dir / "SOURCE-AND-REPLACEMENT.txt"
    ).read_text(encoding="utf-8")
    assert "libvips-42.dll" in (libvips_dir / "NATIVE-FILES.sha256").read_text(
        encoding="ascii"
    )