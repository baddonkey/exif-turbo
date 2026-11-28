from __future__ import annotations

import hashlib
import io
import runpy
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest

from scripts import build_macos, build_vec1, build_windows


def test_vec1_pins_match_windows_source_and_headers() -> None:
    assert build_vec1._SOURCE_URL == build_windows._VEC1_SOURCE_URL
    assert build_vec1._SOURCE_SHA256 == build_windows._VEC1_SOURCE_SHA256
    assert build_vec1._HEADERS_URL == build_windows._VEC1_HEADERS_URL
    assert build_vec1._HEADERS_SHA256 == build_windows._VEC1_HEADERS_SHA256


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("linux", "x86_64", "vec1.so"),
        ("linux", "aarch64", "vec1.so"),
        ("darwin", "arm64", "vec1.dylib"),
        ("darwin", "x86_64", None),
        ("linux", "riscv64", None),
    ],
)
def test_binary_name_platform_selection_returns_supported_extension(
    system: str, machine: str, expected: str | None
) -> None:
    assert build_vec1.binary_name(system, machine) == expected


def test_download_verified_bad_digest_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        build_vec1.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(b"bad")
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_vec1._download_verified("https://example.invalid", tmp_path / "source", "0" * 64)


@pytest.mark.parametrize(("system", "machine"), [("linux", "x86_64"), ("linux", "aarch64"), ("darwin", "arm64")])
def test_staged_vec1_supported_platform_hashes_final_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str, machine: str
) -> None:
    monkeypatch.setattr(build_vec1.sys, "platform", system)
    monkeypatch.setattr(build_vec1.platform, "machine", lambda: machine)
    commands: list[list[str]] = []

    def download(url: str, destination: Path, expected: str) -> None:
        if destination.suffix == ".zip":
            with zipfile.ZipFile(destination, "w") as archive:
                for header in ("sqlite3.h", "sqlite3ext.h"):
                    archive.writestr(f"sqlite-amalgamation-3510100/{header}", header)
        else:
            destination.write_bytes(b"source")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        if command[0] == "cc":
            Path(command[-1]).write_bytes(b"binary")
        else:
            Path(command[-1]).write_bytes(b"signed binary")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build_vec1, "_download_verified", download)
    monkeypatch.setattr(build_vec1.subprocess, "run", run)
    with build_vec1.staged_vec1(tmp_path, sign_identity="identity") as stage:
        assert stage is not None
        name = build_vec1.binary_name(system, machine)
        assert name is not None
        binary = stage / name
        build_vec1.verify_staged_binary(stage, binary)
        expected = b"signed binary" if system == "darwin" else b"binary"
        assert binary.read_bytes() == expected
        assert hashlib.sha256(expected).hexdigest() in (stage / "_vec1_release_hash.py").read_text()
        assert len([command for command in commands if command[0] == "cc"]) == 2
        assert all(not any(arg.startswith("-DVEC1SIMD") for arg in command)
                   for command in commands[:2])
        if system == "linux":
            assert all("-lm" in command and "-Wl,-z,defs" in command
                       for command in commands[:2])
        monkeypatch.setenv(build_vec1.STAGE_ENV, str(stage))
        paths, binaries, hidden = build_vec1.spec_inputs()
        assert paths == [str(stage)]
        assert binaries == [(str(binary), "exif_turbo/assets/native")]
        assert hidden == ["_vec1_release_hash"]


def test_staged_vec1_unsupported_platform_rejects_release_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_vec1.sys, "platform", "linux")
    monkeypatch.setattr(build_vec1.platform, "machine", lambda: "riscv64")
    monkeypatch.setattr(
        build_vec1, "_download_verified",
        lambda *_args: pytest.fail("unsupported platforms must not download Vec1"),
    )
    with pytest.raises(RuntimeError, match="unavailable for release target"):
        with build_vec1.staged_vec1(tmp_path):
            pytest.fail("unsupported releases must not omit Vec1")


def test_staged_vec1_nonreproducible_compiler_output_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_vec1.sys, "platform", "linux")
    monkeypatch.setattr(build_vec1.platform, "machine", lambda: "x86_64")

    def download(_url: str, destination: Path, _expected: str) -> None:
        if destination.suffix == ".zip":
            with zipfile.ZipFile(destination, "w") as archive:
                for header in ("sqlite3.h", "sqlite3ext.h"):
                    archive.writestr(f"sqlite-amalgamation-3510100/{header}", header)
        else:
            destination.write_bytes(b"source")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        output = Path(command[-1])
        output.write_bytes(output.parent.name.encode())
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build_vec1, "_download_verified", download)
    monkeypatch.setattr(build_vec1.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="not reproducible"), build_vec1.staged_vec1(tmp_path):
        pytest.fail("a nonreproducible binary must not be published")


def test_verify_staged_binary_tampering_fails_closed(tmp_path: Path) -> None:
    binary = tmp_path / "vec1.dylib"
    binary.write_bytes(b"altered")
    (tmp_path / "_vec1_release_hash.py").write_text(
        f'EXPECTED_SHA256 = "{hashlib.sha256(b"original").hexdigest()}"\n'
    )
    with pytest.raises(RuntimeError, match="changed"):
        build_vec1.verify_staged_binary(tmp_path, binary)


def test_spec_inputs_unstaged_or_missing_files_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(build_vec1.STAGE_ENV, raising=False)
    assert build_vec1.spec_inputs() == ([], [], [])
    monkeypatch.setenv(build_vec1.STAGE_ENV, str(tmp_path))
    with pytest.raises(RuntimeError, match="Invalid Vec1"):
        build_vec1.spec_inputs()


def test_sign_bundle_preserves_signed_vec1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = tmp_path / "exif-turbo.app"
    native = app / "Contents" / "Resources" / "exif_turbo" / "assets" / "native"
    native.mkdir(parents=True)
    vec1 = native / "vec1.dylib"
    vec1.touch()
    other = native / "other.dylib"
    other.touch()
    signed: list[Path] = []
    monkeypatch.setattr(build_macos, "sign_item", lambda path, _identity: signed.append(path))
    build_macos.sign_bundle(app, "identity")
    assert vec1 not in signed
    assert other in signed
    assert app in signed


@pytest.mark.parametrize(
    ("spec", "system", "machine"),
    [
        ("exif-turbo-deb.spec", "linux", "x86_64"),
        ("exif-turbo-rpm.spec", "linux", "aarch64"),
        ("exif-turbo-macos-arm.spec", "darwin", "arm64"),
        ("exif-turbo.spec", "win32", "AMD64"),
    ],
)
def test_specs_staged_vec1_collects_binary_and_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spec: str, system: str, machine: str
) -> None:
    from PyInstaller.utils import hooks

    monkeypatch.setattr(build_vec1.sys, "platform", system)
    monkeypatch.setattr(build_vec1.platform, "machine", lambda: machine)
    monkeypatch.setenv(build_vec1.STAGE_ENV, str(tmp_path))
    name = "vec1.dll" if system == "win32" else build_vec1.binary_name(system, machine)
    assert name is not None
    (tmp_path / name).write_bytes(b"binary")
    (tmp_path / "_vec1_release_hash.py").write_text("EXPECTED_SHA256 = ''\n")
    licenses = types.ModuleType("stage_runtime_licenses")
    licenses.stage_runtime_licenses = lambda: tmp_path  # type: ignore[attr-defined]
    version_info = types.ModuleType("gen_version_info")
    version_info.write_version_info = lambda *_args: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stage_runtime_licenses", licenses)
    monkeypatch.setitem(sys.modules, "gen_version_info", version_info)
    monkeypatch.setitem(sys.modules, "build_vec1", build_vec1)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(hooks, "collect_all", lambda _name: ([], [], []))
    monkeypatch.setattr(hooks, "collect_data_files", lambda *_args, **_kwargs: [])
    captured: dict[str, object] = {}

    def analysis(_scripts: list[str], **kwargs: object) -> object:
        captured.update(kwargs)
        obj = types.SimpleNamespace(
            pure=[], scripts=[], binaries=[],
            datas=[
                ("faiss_cpu-1.14.3.dist-info/METADATA", "faiss-metadata", "DATA"),
                (r"nested\FAISS_CPU-1.14.3.dist-info\RECORD", "faiss-record", "DATA"),
                ("other-1.0.dist-info/METADATA", "other-metadata", "DATA"),
            ],
        )
        captured["result"] = obj
        return obj

    runpy.run_path(
        str(Path(__file__).resolve().parents[2] / spec),
        init_globals={
            "Analysis": analysis,
            "PYZ": lambda *_args, **_kwargs: None,
            "EXE": lambda *_args, **_kwargs: None,
            "COLLECT": lambda *_args, **_kwargs: None,
            "BUNDLE": lambda *_args, **_kwargs: None,
        },
    )
    if system != "win32":
        assert str(tmp_path) in captured["pathex"]
    assert "_vec1_release_hash" in captured["hiddenimports"]
    assert "faiss" in captured["excludes"]
    result = captured["result"]
    assert ("faiss_cpu-1.14.3.dist-info/METADATA", "faiss-metadata", "DATA") not in result.datas
    assert (r"nested\FAISS_CPU-1.14.3.dist-info\RECORD", "faiss-record", "DATA") not in result.datas
    assert ("other-1.0.dist-info/METADATA", "other-metadata", "DATA") in result.datas
    if system == "darwin":
        assert (str(Path("exif_turbo/assets/native/vec1.dylib")), str(tmp_path / name), "DATA") in result.datas
    elif system != "win32":
        assert (str(tmp_path / name), "exif_turbo/assets/native") in captured["binaries"]
    else:
        assert (r"build\vec1\vec1.dll", r"exif_turbo\assets\native") in captured["binaries"]
