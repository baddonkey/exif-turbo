from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_linux


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