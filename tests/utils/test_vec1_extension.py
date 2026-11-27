from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

from exif_turbo.utils import vec1_extension
from exif_turbo.utils.vec1_extension import bundled_vec1_extension


def test_bundled_vec1_extension_rejects_modified_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    directory = tmp_path / "exif_turbo" / "assets" / "native"
    directory.mkdir(parents=True)
    binary = directory / "vec1.dll"
    binary.write_bytes(b"verified extension")
    manifest = ModuleType("_vec1_release_hash")
    manifest.EXPECTED_SHA256 = hashlib.sha256(binary.read_bytes()).hexdigest()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_vec1_release_hash", manifest)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    # Act / Assert
    assert bundled_vec1_extension() == binary
    binary.write_bytes(b"modified extension")
    with pytest.raises(RuntimeError, match="integrity verification"):
        bundled_vec1_extension()


def test_bundled_vec1_extension_unfrozen_installation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(vec1_extension, "__file__", str(tmp_path / "package" / "utils" / "module.py"))

    # Act / Assert
    with pytest.raises(RuntimeError, match="unavailable"):
        bundled_vec1_extension()


def test_bundled_vec1_extension_source_build_verifies_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    source = tmp_path / "src" / "exif_turbo" / "utils" / "vec1_extension.py"
    source.parent.mkdir(parents=True)
    source.touch()
    (tmp_path / "pyproject.toml").touch()
    directory = tmp_path / "build" / "vec1"
    directory.mkdir(parents=True)
    binary = directory / "vec1.dll"
    binary.write_bytes(b"development extension")
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    (directory / "_vec1_release_hash.py").write_text(
        f'EXPECTED_SHA256 = "{digest}"\n', encoding="ascii"
    )
    monkeypatch.setattr(vec1_extension, "__file__", str(source))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    # Act / Assert
    assert bundled_vec1_extension() == binary
    binary.write_bytes(b"modified extension")
    with pytest.raises(RuntimeError, match="integrity verification"):
        bundled_vec1_extension()


@pytest.mark.parametrize(
    ("platform", "name"),
    [("linux", "vec1.so"), ("darwin", "vec1.dylib")],
)
def test_bundled_vec1_extension_resolves_platform_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, name: str
) -> None:
    # Arrange
    root = tmp_path / "Contents" / "Resources" if platform == "darwin" else tmp_path
    directory = root / "exif_turbo" / "assets" / "native"
    directory.mkdir(parents=True)
    binary = directory / name
    binary.write_bytes(b"verified extension")
    manifest = ModuleType("_vec1_release_hash")
    manifest.EXPECTED_SHA256 = hashlib.sha256(binary.read_bytes()).hexdigest()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_vec1_release_hash", manifest)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Contents" / "MacOS" / "exif-turbo"))

    # Act / Assert
    assert bundled_vec1_extension() == binary
    binary.write_bytes(b"modified extension")
    with pytest.raises(RuntimeError, match="integrity verification"):
        bundled_vec1_extension()
