"""Stage project and runtime dependency license texts for release bundles."""

from __future__ import annotations

import re
import hashlib
import shutil
import sysconfig
import tempfile
import tomllib
import urllib.request
from importlib.metadata import Distribution, PackageNotFoundError, distribution
from pathlib import Path
from typing import Sequence

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "license-staged"
_LICENSE_PREFIXES = ("LICENSE", "COPYING", "NOTICE")
_QT_DISTRIBUTIONS = {
    "pyside6",
    "pyside6-addons",
    "pyside6-essentials",
    "shiboken6",
}
_QT_LICENSES = {
    "GPL-2.0-only.txt": ("GNU GENERAL PUBLIC LICENSE", 17_000, "END OF TERMS AND CONDITIONS"),
    "GPL-3.0-only.txt": ("GNU GENERAL PUBLIC LICENSE", 34_000, "END OF TERMS AND CONDITIONS"),
    "LGPL-3.0-only.txt": (
        "GNU LESSER GENERAL PUBLIC LICENSE",
        7_000,
        "permanent authorization for you to choose that version",
    ),
    "Qt-GPL-exception-1.0.txt": ("The Qt Company GPL Exception 1.0", 800, "Exception 2:"),
}
_LIBVIPS_FILES = {
    "LIBVIPS-LGPL-2.1.txt": (
        "https://raw.githubusercontent.com/libvips/libvips/v{version}/LICENSE",
        "GNU LESSER GENERAL PUBLIC LICENSE",
        25_000,
        "END OF TERMS AND CONDITIONS",
    ),
    "LGPL-3.0-only.txt": (
        "https://raw.githubusercontent.com/spdx/license-list-data/"
        "main/text/LGPL-3.0-only.txt",
        "GNU LESSER GENERAL PUBLIC LICENSE",
        7_000,
        "permanent authorization for you to choose that version",
    ),
    "PACKAGING-APACHE-2.0.txt": (
        "https://raw.githubusercontent.com/kleisauke/libvips-packaging/"
        "v{version}/LICENSE",
        "Apache License",
        11_000,
        "END OF TERMS AND CONDITIONS",
    ),
    "THIRD-PARTY-NOTICES.md": (
        "https://raw.githubusercontent.com/kleisauke/libvips-packaging/"
        "v{version}/THIRD-PARTY-NOTICES.md",
        "# Third-party notices",
        4_000,
        "libvips       | LGPLv3",
    ),
    "VERSIONS.properties": (
        "https://raw.githubusercontent.com/kleisauke/libvips-packaging/"
        "v{version}/versions.properties",
        "VERSION_AOM=",
        500,
        "VERSION_VIPS={version}",
    ),
}


class LicenseStagingError(RuntimeError):
    """Raised when a runtime dependency cannot supply its license text."""


def _declared_runtime_requirements() -> tuple[str, ...]:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return tuple(pyproject["project"]["dependencies"])


def _runtime_distributions(requirements: Sequence[str]) -> tuple[Distribution, ...]:
    pending = [
        requirement
        for spec in requirements
        if (requirement := Requirement(spec)).marker is None
        or requirement.marker.evaluate()
    ]
    resolved: dict[str, Distribution] = {}
    expanded_contexts: dict[str, set[str]] = {}

    while pending:
        requirement = pending.pop(0)
        key = canonicalize_name(requirement.name)
        package = resolved.get(key)
        if package is None:
            try:
                package = distribution(requirement.name)
            except PackageNotFoundError as exc:
                raise LicenseStagingError(
                    f"runtime distribution is not installed: {requirement.name}"
                ) from exc
            resolved[key] = package

        contexts = {"", *requirement.extras}
        new_contexts = contexts - expanded_contexts.setdefault(key, set())
        if not new_contexts:
            continue
        expanded_contexts[key].update(new_contexts)
        for spec in package.requires or ():
            dependency = Requirement(spec)
            if dependency.marker is not None and not any(
                dependency.marker.evaluate({"extra": extra}) for extra in new_contexts
            ):
                continue
            pending.append(dependency)

    return tuple(
        sorted(
            resolved.values(),
            key=lambda package: canonicalize_name(package.metadata["Name"]),
        )
    )


def _license_files(package: Distribution) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative in package.files or ():
        if not any(
            part.upper().startswith(_LICENSE_PREFIXES)
            for part in Path(str(relative)).parts
        ):
            continue
        source = Path(package.locate_file(relative))
        if source.is_file():
            files.append(source)
    return tuple(sorted(set(files), key=lambda path: str(path).casefold()))


def _safe_filename(path: Path, used: set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", path.name)
    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    number = 2
    while candidate.casefold() in used:
        candidate = f"{stem}-{number}{suffix}"
        number += 1
    used.add(candidate.casefold())
    return candidate


def _python_license_file() -> Path:
    installed_base = Path(str(sysconfig.get_config_var("installed_base")))
    candidates = [installed_base / "LICENSE.txt", installed_base / "LICENSE"]
    stdlib = sysconfig.get_path("stdlib")
    if stdlib:
        candidates.extend((Path(stdlib) / "LICENSE.txt", Path(stdlib) / "LICENSE"))
    version = sysconfig.get_config_var("py_version_short")
    if version:
        candidates.append(
            installed_base / "share" / "doc" / f"python{version}" / "copyright"
        )
    candidates.append(installed_base / "share" / "doc" / "python3" / "copyright")
    framework_dir = next(
        (parent for parent in installed_base.parents if parent.name == "Python.framework"),
        None,
    )
    if framework_dir is not None:
        candidates.extend(
            (
                framework_dir / "Resources" / "English.lproj" / "License.rtf",
                framework_dir.parent.parent / "LICENSE.txt",
                framework_dir.parent.parent / "LICENSE",
            )
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise LicenseStagingError(
        f"CPython license file not found under interpreter base: {installed_base}"
    )


def _qt_license_files(version: str) -> tuple[Path, ...]:
    cache_dir = REPO_ROOT / "build" / "license-cache" / "qt" / version
    cache_dir.mkdir(parents=True, exist_ok=True)
    for filename, (expected_heading, minimum_size, required_text) in _QT_LICENSES.items():
        target = cache_dir / filename
        if target.is_file():
            cached = target.read_text(encoding="utf-8", errors="replace")
            if (
                len(cached.encode("utf-8")) >= minimum_size
                and expected_heading in cached
                and required_text in cached
            ):
                continue
        url = (
            "https://code.qt.io/cgit/pyside/pyside-setup.git/plain/LICENSES/"
            f"{filename}?h={version}"
        )
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
                contents = response.read()
        except OSError as exc:
            raise LicenseStagingError(
                f"could not download Qt {version} license text: {filename}"
            ) from exc
        text = contents.decode("utf-8")
        if (
            len(contents) < minimum_size
            or expected_heading not in text
            or required_text not in text
        ):
            raise LicenseStagingError(
                f"downloaded Qt license text is invalid: {filename}"
            )
        target.write_text(text, encoding="utf-8")
    return tuple(cache_dir / filename for filename in _QT_LICENSES)


def _libvips_license_files(version: str) -> tuple[Path, ...]:
    cache_dir = REPO_ROOT / "build" / "license-cache" / "libvips" / version
    cache_dir.mkdir(parents=True, exist_ok=True)
    for filename, (url_template, heading, minimum_size, required_template) in (
        _LIBVIPS_FILES.items()
    ):
        target = cache_dir / filename
        required_text = required_template.format(version=version)
        if target.is_file():
            cached = target.read_text(encoding="utf-8", errors="replace")
            if (
                len(cached.encode("utf-8")) >= minimum_size
                and heading in cached
                and required_text in cached
            ):
                continue
        url = url_template.format(version=version)
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
                contents = response.read()
        except OSError as exc:
            raise LicenseStagingError(
                f"could not download libvips {version} compliance file: {filename}"
            ) from exc
        text = contents.decode("utf-8")
        if (
            len(contents) < minimum_size
            or heading not in text
            or required_text not in text
        ):
            raise LicenseStagingError(
                f"downloaded libvips compliance file is invalid: {filename}"
            )
        target.write_text(text, encoding="utf-8")
    return tuple(cache_dir / filename for filename in _LIBVIPS_FILES)


def _write_libvips_source_notice(target: Path, version: str) -> None:
    target.write_text(
        f"""libvips {version} source and replacement information
================================================

This release includes shared libraries supplied by pyvips-binary {version}.
The exact build scripts, dependency versions, and corresponding source links are:

https://github.com/kleisauke/libvips-packaging/tree/v{version}
https://github.com/libvips/libvips/tree/v{version}

The bundled libraries are separate shared-library files. You may replace a
library with a modified, interface-compatible build by replacing the matching
file in the application's internal library directory. Keep the original
filename because the Python extension loads that name. Back up the application
first. On macOS, replacing a dylib invalidates the app signature; ad-hoc re-sign
the modified app with: codesign --force --deep --sign - exif-turbo.app

NATIVE-FILES.sha256 identifies the native libvips files as supplied by the
pyvips-binary wheel. Packaging tools may rewrite ELF or Mach-O loader metadata,
so packaged Linux and macOS file hashes can legitimately differ.

No warranty or support is provided for modified libraries or modified bundles.
See LIBVIPS-LGPL-2.1.txt and THIRD-PARTY-NOTICES.md in this directory.
""",
        encoding="utf-8",
    )


def _write_libvips_hash_manifest(target: Path, package: Distribution) -> None:
    entries: list[str] = []
    for relative in package.files or ():
        source = Path(package.locate_file(relative))
        name = source.name.casefold()
        if not (
            name.startswith(("libvips", "vips-"))
            and (name.endswith((".dll", ".dylib", ".so")) or ".so." in name)
            and source.is_file()
        ):
            continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        entries.append(f"{digest}  {source.name}")
    if not entries:
        raise LicenseStagingError(
            f"pyvips-binary {package.version} contains no libvips shared library"
        )
    target.write_text("\n".join(sorted(entries)) + "\n", encoding="ascii")


def stage_runtime_licenses(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    requirements: Sequence[str] | None = None,
) -> Path:
    """Create a release-ready tree containing project and dependency licenses."""
    packages = _runtime_distributions(
        requirements if requirements is not None else _declared_runtime_requirements()
    )

    package_licenses: list[tuple[Distribution, tuple[Path, ...]]] = []
    for package in packages:
        files = _license_files(package)
        if not files and canonicalize_name(package.metadata["Name"]) not in (
            _QT_DISTRIBUTIONS
        ):
            raise LicenseStagingError(
                "runtime distribution has no packaged license file: "
                f"{package.metadata['Name']} {package.version}"
            )
        package_licenses.append((package, files))

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir.parent) as temporary:
        staged = Path(temporary) / "licenses"
        staged.mkdir()
        shutil.copy2(REPO_ROOT / "LICENSE", staged / "PROJECT-LICENSE.txt")
        shutil.copy2(
            REPO_ROOT / "THIRD-PARTY-LICENSES.md",
            staged / "THIRD-PARTY-LICENSES.md",
        )
        shutil.copy2(_python_license_file(), staged / "CPYTHON-LICENSE.txt")

        manifest = [
            "Python runtime dependency license files",
            "=======================================",
            "",
            "Generated from the active build environment. Each directory below",
            "contains the unmodified license/notice files shipped by that distribution.",
            "Qt for Python wheels that omit these files reference validated upstream",
            "Qt license texts in the shared qt/<version> directory.",
            "",
        ]
        python_dir = staged / "python"
        for package, license_files in package_licenses:
            name = package.metadata["Name"]
            version = package.version
            canonical_name = canonicalize_name(name)
            package_dir = python_dir / f"{canonical_name}-{version}"
            used_names: set[str] = set()
            copied_names: list[str] = []
            for source in license_files:
                package_dir.mkdir(parents=True, exist_ok=True)
                filename = _safe_filename(source, used_names)
                shutil.copy2(source, package_dir / filename)
                copied_names.append(filename)

            expression = (
                package.metadata.get("License-Expression")
                or package.metadata.get("License")
                or "not declared"
            )
            manifest.append(f"{name} {version} [{expression}]")
            manifest.extend(
                f"  python/{package_dir.name}/{item}" for item in copied_names
            )

            if canonical_name in _QT_DISTRIBUTIONS:
                qt_dir = staged / "qt" / version
                if not qt_dir.exists():
                    qt_dir.mkdir(parents=True)
                    for source in _qt_license_files(version):
                        shutil.copy2(source, qt_dir / source.name)
                if not license_files:
                    manifest.extend(
                        f"  qt/{version}/{source.name}"
                        for source in sorted(qt_dir.iterdir())
                        if source.is_file()
                    )

            manifest.append("")

            if canonical_name == "pyvips-binary":
                libvips_dir = staged / "libvips" / version
                libvips_dir.mkdir(parents=True)
                for source in _libvips_license_files(version):
                    shutil.copy2(source, libvips_dir / source.name)
                _write_libvips_source_notice(
                    libvips_dir / "SOURCE-AND-REPLACEMENT.txt", version
                )
                _write_libvips_hash_manifest(
                    libvips_dir / "NATIVE-FILES.sha256", package
                )

        (staged / "PYTHON-RUNTIME-LICENSES.txt").write_text(
            "\n".join(manifest), encoding="utf-8"
        )
        (staged / "STAGING-COMPLETE").write_text("complete\n", encoding="ascii")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.move(str(staged), output_dir)

    print(f"  Staged licenses for {len(packages)} runtime distributions: {output_dir}")
    return output_dir


if __name__ == "__main__":
    stage_runtime_licenses()
