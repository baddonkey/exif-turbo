"""Stage project and runtime dependency license texts for release bundles."""

from __future__ import annotations

import re
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
    for candidate in (installed_base / "LICENSE.txt", installed_base / "LICENSE"):
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
        if not files:
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
            "",
        ]
        python_dir = staged / "python"
        for package, license_files in package_licenses:
            name = package.metadata["Name"]
            version = package.version
            package_dir = python_dir / f"{canonicalize_name(name)}-{version}"
            package_dir.mkdir(parents=True)
            used_names: set[str] = set()
            copied_names: list[str] = []
            for source in license_files:
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
            manifest.append("")

            if canonicalize_name(name) == "pyside6":
                qt_dir = staged / "qt" / version
                qt_dir.mkdir(parents=True)
                for source in _qt_license_files(version):
                    shutil.copy2(source, qt_dir / source.name)

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
