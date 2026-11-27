"""Resolve the verified Vec1 extension in a frozen application."""
from __future__ import annotations

import hashlib
import importlib
import re
import sys
from pathlib import Path


def bundled_vec1_extension() -> Path:
    """Return only the packaged binary matching the digest embedded at build time."""
    bundle = getattr(sys, "_MEIPASS", None)
    names = {"win32": "vec1.dll", "linux": "vec1.so", "darwin": "vec1.dylib"}
    name = names.get(sys.platform)
    if name is None:
        raise RuntimeError("The bundled Vec1 extension is unavailable on this installation")
    if getattr(sys, "frozen", False) and isinstance(bundle, str):
        try:
            manifest = importlib.import_module("_vec1_release_hash")
        except ModuleNotFoundError as exc:
            raise RuntimeError("The bundled Vec1 integrity metadata is unavailable") from exc
        expected = getattr(manifest, "EXPECTED_SHA256", None)
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise RuntimeError("The bundled Vec1 integrity metadata is invalid")
        root = (
            Path(sys.executable).resolve().parent.parent / "Resources"
            if sys.platform == "darwin" else Path(bundle)
        )
        directory = root / "exif_turbo" / "assets" / "native"
    else:
        source = Path(__file__).resolve()
        root = source.parents[3]
        if not (root / "pyproject.toml").is_file() or source != (
            root / "src" / "exif_turbo" / "utils" / "vec1_extension.py"
        ):
            raise RuntimeError("The bundled Vec1 extension is unavailable on this installation")
        directory = root / "build" / "vec1"
        manifest_path = directory / "_vec1_release_hash.py"
        try:
            contents = manifest_path.read_text(encoding="ascii")
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Vec1 is not built; run scripts\\stage_vec1_development.py"
            ) from exc
        match = re.fullmatch(r'EXPECTED_SHA256 = "([0-9a-f]{64})"\r?\n', contents)
        if match is None:
            raise RuntimeError("The Vec1 development integrity metadata is invalid")
        expected = match.group(1)
    binary = directory / name
    if not binary.is_file() or binary.is_symlink() or binary.resolve().parent != directory.resolve():
        raise RuntimeError("The bundled Vec1 extension is unavailable")
    digest = hashlib.sha256()
    with binary.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError("The bundled Vec1 extension failed integrity verification")
    return binary
