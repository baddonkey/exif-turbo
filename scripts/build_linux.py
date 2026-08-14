"""Build a self-contained Linux distribution for exif-turbo.

Produces:
    dist/exif-turbo-linux/                        — onedir bundle (GUI + CLI)
    dist/exif-turbo-<version>-linux-amd64.deb     — Debian/Ubuntu package
    dist/exif-turbo-<version>-linux-arm64.deb     — Debian/Ubuntu package
    dist/exif-turbo-<version>-linux-x86_64.rpm    — RPM package (Fedora/RHEL/openSUSE)

Requirements:
    pip install pyinstaller babel packaging
    dpkg-deb   (apt install dpkg)      — for DEB
    rpmbuild   (apt install rpm)       — for RPM

Usage:
    python scripts/build_linux.py
    python scripts/build_linux.py --deb-only
    python scripts/build_linux.py --deb-only --deb-arch arm64
    python scripts/build_linux.py --rpm-only
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        fail(f"Command failed ({result.returncode}): {' '.join(cmd)}")


def find_tool(name: str, venv_subpath: str | None = None) -> str:
    found = shutil.which(name)
    if found:
        return found
    if venv_subpath:
        candidate = REPO_ROOT / venv_subpath
        if candidate.exists():
            return str(candidate)
    fail(f"Required tool '{name}' not found. See script header for install instructions.")
    return ""  # unreachable


def read_version() -> str:
    init_file = REPO_ROOT / "src" / "exif_turbo" / "__init__.py"
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", init_file.read_text())
    if not match:
        fail(f"Could not read __version__ from {init_file}")
    return match.group(1)


def compile_translations() -> None:
    print("  Compiling translation catalogs ...")
    pybabel = find_tool("pybabel", venv_subpath=".venv/bin/pybabel")
    locales_dir = REPO_ROOT / "src" / "exif_turbo" / "i18n" / "locales"
    for po in locales_dir.rglob("*.po"):
        mo = po.with_suffix(".mo")
        run([pybabel, "compile", "-i", str(po), "-o", str(mo)])
        print(f"    {mo}")
    print("  Translation catalogs compiled.")


def deb_arch(target_arch: str | None = None) -> str:
    if target_arch is not None:
        return target_arch
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())


def rpm_arch() -> str:
    return platform.machine()


def _find_icon() -> Path | None:
    for candidate in (
        REPO_ROOT / "assets" / "icon.png",
        REPO_ROOT / "src" / "exif_turbo" / "assets" / "logo.png",
    ):
        if candidate.exists():
            return candidate
    return None


def _write_desktop_file(path: Path, version: str) -> None:
    path.write_text(
        "[Desktop Entry]\n"
        "Name=exif-turbo\n"
        "Comment=Fast EXIF full-text image search\n"
        "Exec=exif-turbo\n"
        "Icon=exif-turbo\n"
        "Terminal=false\n"
        "Type=Application\n"
        "Categories=Graphics;Viewer;\n"
        f"Version={version}\n"
    )


def create_package_staging(bundle_dir: Path, version: str, staging: Path) -> bool:
    """Populate *staging* with the standard /usr layout. Returns True if an icon was installed."""
    lib_dir = staging / "usr" / "lib" / "exif-turbo"
    bin_dir = staging / "usr" / "bin"
    apps_dir = staging / "usr" / "share" / "applications"
    icon_dir = staging / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    metainfo_dir = staging / "usr" / "share" / "metainfo"
    doc_dir = staging / "usr" / "share" / "doc" / "exif-turbo"

    for d in (lib_dir, bin_dir, apps_dir, icon_dir, metainfo_dir, doc_dir):
        d.mkdir(parents=True, exist_ok=True)

    shutil.copytree(bundle_dir, lib_dir, dirs_exist_ok=True)

    license_source = REPO_ROOT / "build" / "license-staged"
    if not (license_source / "STAGING-COMPLETE").is_file():
        fail(f"Generated license bundle not found: {license_source}")
    shutil.copytree(license_source, doc_dir, dirs_exist_ok=True)
    (doc_dir / "copyright").write_text(
        (license_source / "PROJECT-LICENSE.txt").read_text(encoding="utf-8")
        + "\n\nThird-party notices and exact license texts are installed in this directory.\n\n"
        + (license_source / "THIRD-PARTY-LICENSES.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    wrapper = bin_dir / "exif-turbo"
    wrapper.write_text('#!/bin/sh\nexec /usr/lib/exif-turbo/exif-turbo "$@"\n')
    wrapper.chmod(0o755)

    _write_desktop_file(apps_dir / "exif-turbo.desktop", version)

    metainfo_src = REPO_ROOT / "installer" / "com.exifturbo.app.metainfo.xml"
    if metainfo_src.exists():
        shutil.copy2(metainfo_src, metainfo_dir / "com.exifturbo.app.metainfo.xml")

    icon_src = _find_icon()
    if icon_src:
        shutil.copy2(icon_src, icon_dir / "exif-turbo.png")
    return icon_src is not None


def build_deb(
    bundle_dir: Path,
    version: str,
    *,
    deb_arch_override: str | None = None,
) -> Path:
    arch = deb_arch(deb_arch_override)
    deb_out = REPO_ROOT / "dist" / f"exif-turbo-{version}-linux-{arch}.deb"
    print(f"  Building DEB package ({arch}) ...")

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        has_icon = create_package_staging(bundle_dir, version, staging)

        installed_kb = (
            sum(f.stat().st_size for f in staging.rglob("*") if f.is_file()) // 1024
        )

        # System libraries required by Qt/WebEngine that are not bundled.
        _deb_depends = ", ".join([
            "libnss3",
            "libxfixes3",
            "libxkbfile1",
            "libxkbcommon0",
            "libxkbcommon-x11-0",
            "libxcb-cursor0",
            "libxcb-icccm4",
            "libxcb-image0",
            "libxcb-keysyms1",
            "libxcb-render-util0",
            "libxcb-render0",
            "libxcb-shape0",
            "libxcb-shm0",
            "libxcb-util1",
            "libxcb-xkb1",
            "libxcb-glx0",
            "libgbm1",
            "libasound2t64 | libasound2",
            "libpulse0",
            "libtiff6 | libtiff5",
            "libatk1.0-0",
            "libatk-bridge2.0-0",
            "libcups2",
            "libxcomposite1",
            "libxdamage1",
            "libxrandr2",
            "libpango-1.0-0",
            "libminizip1t64 | libminizip1",
        ])

        debian_dir = staging / "DEBIAN"
        debian_dir.mkdir()
        (debian_dir / "control").write_text(
            f"Package: exif-turbo\n"
            f"Version: {version}\n"
            f"Architecture: {arch}\n"
            f"Maintainer: exif-turbo contributors\n"
            f"Installed-Size: {installed_kb}\n"
            f"Depends: {_deb_depends}\n"
            f"Description: Fast EXIF full-text image search\n"
            f" Cross-platform image EXIF metadata search and indexing tool.\n"
            f" Scans image folders, extracts EXIF metadata, stores it in a\n"
            f" SQLite index, and provides fast full-text search.\n"
        )

        run(["dpkg-deb", "--build", "--root-owner-group", str(staging), str(deb_out)])

    return deb_out


def build_rpm(bundle_dir: Path, version: str) -> Path:
    arch = rpm_arch()
    rpm_out = REPO_ROOT / "dist" / f"exif-turbo-{version}-linux-{arch}.rpm"
    print(f"  Building RPM package ({arch}) ...")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for subdir in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS"):
            (tmp_path / subdir).mkdir()

        staging = tmp_path / "staging"
        has_icon = create_package_staging(bundle_dir, version, staging)

        icon_files_line = (
            "/usr/share/icons/hicolor/256x256/apps/exif-turbo.png" if has_icon else ""
        )

        spec_content = textwrap.dedent(f"""\
            %global __strip /bin/true
            %global __brp_strip_lto /bin/true
            %global __brp_strip_static_archive /bin/true
            Name:           exif-turbo
            Version:        {version}
            Release:        1
            Summary:        Fast EXIF full-text image search
            License:        MIT
            AutoReqProv:    no
            Obsoletes:      exif-turbo < %{{version}}
            Requires:       nss, libXfixes, libxkbfile, libxkbcommon, libxkbcommon-x11
            Requires:       xcb-util, xcb-util-wm, xcb-util-image, xcb-util-keysyms, xcb-util-renderutil, xcb-util-cursor
            Requires:       libxcb, mesa-libgbm, pango, alsa-lib, pulseaudio-libs, libtiff
            Requires:       atk, at-spi2-atk, cups-libs
            Requires:       libXcomposite, libXdamage, libXrandr, libxshmfence

            %description
            Cross-platform image EXIF metadata search and indexing tool.
            Scans image folders, extracts EXIF metadata, stores it in a
            SQLite index, and provides fast full-text search.

            %install
            cp -a {staging}/usr %{{buildroot}}/

            %files
            %defattr(-,root,root,-)
            /usr/bin/exif-turbo
            /usr/lib/exif-turbo
            /usr/share/applications/exif-turbo.desktop
            /usr/share/metainfo/com.exifturbo.app.metainfo.xml
            %license /usr/share/doc/exif-turbo
            {icon_files_line}

            %changelog
        """)

        spec_file = tmp_path / "SPECS" / "exif-turbo.spec"
        spec_file.write_text(spec_content)

        run([
            "rpmbuild", "-bb",
            "--define", f"_topdir {tmp_path}",
            "--define", "__check_files %{nil}",
            "--target", arch,
            str(spec_file),
        ])

        rpm_files = list((tmp_path / "RPMS").rglob("*.rpm"))
        if not rpm_files:
            fail("rpmbuild completed but no .rpm file was produced.")
        shutil.copy2(rpm_files[0], rpm_out)

    return rpm_out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--deb-only", action="store_true", help="Build only the DEB package."
    )
    group.add_argument(
        "--rpm-only", action="store_true", help="Build only the RPM package."
    )
    parser.add_argument(
        "--deb-arch",
        choices=("amd64", "arm64"),
        help="Override DEB architecture metadata (useful in cross-arch container builds).",
    )
    args = parser.parse_args()

    if args.deb_arch and args.rpm_only:
        fail("--deb-arch cannot be used with --rpm-only")

    find_tool("pyinstaller")
    if not args.rpm_only:
        find_tool("dpkg-deb")
    if not args.deb_only:
        find_tool("rpmbuild")

    version = read_version()
    print(f"Building exif-turbo {version} for Linux ...")

    compile_translations()

    artifacts: list[Path] = []

    if not args.rpm_only:
        run(["pyinstaller", "--noconfirm", "--clean", "exif-turbo-deb.spec"])
        print("  PyInstaller DEB build complete.")
        deb_bundle = REPO_ROOT / "dist" / "exif-turbo-deb"
        artifacts.append(deb_bundle)
        deb_out = build_deb(deb_bundle, version, deb_arch_override=args.deb_arch)
        artifacts.append(deb_out)

    if not args.deb_only:
        run(["pyinstaller", "--noconfirm", "--clean", "exif-turbo-rpm.spec"])
        print("  PyInstaller RPM build complete.")
        rpm_bundle = REPO_ROOT / "dist" / "exif-turbo-rpm"
        artifacts.append(rpm_bundle)
        rpm_out = build_rpm(rpm_bundle, version)
        artifacts.append(rpm_out)

    print()
    print("Done! Artifacts:")
    for p in artifacts:
        print(f"  {p}")


if __name__ == "__main__":
    main()
