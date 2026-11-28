from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_linux


def test_build_deb_runtime_dependencies_include_opengl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(build_linux, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        build_linux, "create_package_staging",
        lambda bundle, version, staging: staging.mkdir() or False,
    )
    monkeypatch.setattr(build_linux, "audit_release_payload", lambda *args, **kwargs: None)
    control = ""

    def run(command: list[str], **kwargs: object) -> None:
        nonlocal control
        control = (Path(command[-2]) / "DEBIAN" / "control").read_text()

    monkeypatch.setattr(build_linux, "run", run)

    # Act
    build_linux.build_deb(tmp_path, "1.0")

    # Assert
    depends = next(line for line in control.splitlines() if line.startswith("Depends: "))
    assert {"libgl1", "libegl1", "libopengl0"} <= set(
        depends.removeprefix("Depends: ").split(", ")
    )
    assert {"libsnappy1v5", "libwebpdemux2", "libwebpmux3", "liblcms2-2", "libopus0"} <= set(
        depends.removeprefix("Depends: ").split(", ")
    )


def test_build_rpm_runtime_dependencies_include_opengl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    (tmp_path / "dist").mkdir()
    monkeypatch.setattr(build_linux, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        build_linux, "create_package_staging",
        lambda bundle, version, staging: staging.mkdir() or False,
    )
    monkeypatch.setattr(build_linux, "audit_release_payload", lambda *args, **kwargs: None)
    spec = ""

    def run(command: list[str], **kwargs: object) -> None:
        nonlocal spec
        spec_path = Path(command[-1])
        spec = spec_path.read_text()
        (spec_path.parent.parent / "RPMS" / "test.rpm").write_bytes(b"rpm")

    monkeypatch.setattr(build_linux, "run", run)

    # Act
    build_linux.build_rpm(tmp_path, "1.0")

    # Assert
    requires = [line.removeprefix("Requires:").strip() for line in spec.splitlines()
                if line.startswith("Requires:")]
    assert {"mesa-libGL", "mesa-libEGL", "libglvnd-opengl"} <= {
        item.strip() for line in requires for item in line.split(",")
    }
    assert {"snappy", "libwebp", "lcms2", "opus"} <= {
        item.strip() for line in requires for item in line.split(",")
    }


def test_create_package_staging_generated_licenses_installs_standard_doc_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    project_root = tmp_path / "project"
    license_source = project_root / "build" / "license-staged"
    dependency_dir = license_source / "python" / "demo-1.0"
    dependency_dir.mkdir(parents=True)
    (license_source / "PROJECT-LICENSE.txt").write_text(
        "project terms", encoding="utf-8"
    )
    (license_source / "THIRD-PARTY-LICENSES.md").write_text(
        "dependency notices", encoding="utf-8"
    )
    (license_source / "STAGING-COMPLETE").write_text("complete\n", encoding="ascii")
    (dependency_dir / "LICENSE").write_text("dependency terms", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "exif-turbo").write_text("binary", encoding="utf-8")
    monkeypatch.setattr(build_linux, "REPO_ROOT", project_root)
    staging = tmp_path / "staging"

    # Act
    build_linux.create_package_staging(bundle_dir, "1.0", staging)

    # Assert
    doc_dir = staging / "usr" / "share" / "doc" / "exif-turbo"
    assert (doc_dir / "python" / "demo-1.0" / "LICENSE").read_text(
        encoding="utf-8"
    ) == "dependency terms"
    assert (doc_dir / "copyright").read_text(encoding="utf-8") == (
        "project terms\n\n"
        "Third-party notices and exact license texts are installed in this directory.\n\n"
        "dependency notices"
    )


def test_create_package_staging_normalizes_bundled_file_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    project_root = tmp_path / "project"
    license_source = project_root / "build" / "license-staged"
    license_source.mkdir(parents=True)
    (license_source / "PROJECT-LICENSE.txt").write_text("project terms")
    (license_source / "THIRD-PARTY-LICENSES.md").write_text("notices")
    (license_source / "STAGING-COMPLETE").write_text("complete\n")
    bundle_dir = tmp_path / "bundle"
    metadata_dir = bundle_dir / "demo-1.0.dist-info"
    metadata_dir.mkdir(parents=True)
    executable = bundle_dir / "exif-turbo"
    executable.write_bytes(b"\x7fELFbinary")
    metadata = metadata_dir / "METADATA"
    metadata.write_text("Name: demo\n")
    module = bundle_dir / "demo.py"
    module.write_text("VALUE = 1\n")
    ambiguous_python_module = bundle_dir / "ambiguous.py"
    ambiguous_python_module.write_text("#!/usr/bin/env python\nVALUE = 1\n")
    monkeypatch.setattr(build_linux, "REPO_ROOT", project_root)
    staging = tmp_path / "staging"
    chmod_calls: list[tuple[Path, int]] = []
    original_chmod = Path.chmod

    def record_chmod(path: Path, mode: int) -> None:
        chmod_calls.append((path, mode))
        original_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", record_chmod)

    # Act
    build_linux.create_package_staging(bundle_dir, "1.0", staging)

    # Assert
    installed = staging / "usr" / "lib" / "exif-turbo"
    installed_modes = {
        path.relative_to(installed): mode & 0o111
        for path, mode in chmod_calls
        if path.is_relative_to(installed)
    }
    assert installed_modes == {
        Path("demo-1.0.dist-info/METADATA"): 0,
        Path("demo.py"): 0,
        Path("exif-turbo"): 0o111,
        Path("ambiguous.py"): 0,
    }
    doc_dir = staging / "usr" / "share" / "doc" / "exif-turbo"
    assert all(path.stat().st_mode & 0o111 == 0 for path in doc_dir.rglob("*") if path.is_file())