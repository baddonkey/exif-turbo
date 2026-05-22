"""PyInstaller hook for pyvips.

pyvips-binary installs the _libvips binary extension and the companion
libvips shared library directly into site-packages root (not inside the
pyvips/ package directory), so PyInstaller's standard package-collection
misses them.

This hook reads the pyvips_binary dist-info RECORD to find every binary
file that pyvips-binary installed, then adds them all to the bundle root
(".").  Using the RECORD ensures we catch any transitive shared libraries
that pyvips-binary bundles on Linux manylinux wheels.
"""
from __future__ import annotations

import glob
import os
import sysconfig

# _libvips is a CFFI extension module installed by pyvips-binary directly
# into site-packages root.  PyInstaller's static analysis may miss the
# `import _libvips` inside pyvips/__init__.py (it is inside a try/except).
# Adding it here ensures the extension is registered in the module graph so
# PyInstaller's FrozenImporter can resolve it, not just the PathFinder.
hiddenimports: list[str] = ["_libvips"]

sp = sysconfig.get_path("purelib")

binaries: list[tuple[str, str]] = []

# Locate the pyvips_binary dist-info directory and read its RECORD.
for record_file in glob.glob(os.path.join(sp, "pyvips_binary-*.dist-info", "RECORD")):
    with open(record_file, encoding="utf-8") as fh:
        for line in fh:
            # RECORD lines: relative_path,hash,size
            fname = line.strip().split(",")[0]
            if not fname:
                continue
            # Keep only binary files (extension modules, shared libs, DLLs).
            is_binary = (
                fname.endswith((".pyd", ".dll", ".dylib"))
                or fname.endswith(".so")
                or ".so." in fname
            )
            if not is_binary:
                continue
            full_path = os.path.normpath(os.path.join(sp, fname))
            if os.path.isfile(full_path):
                binaries.append((full_path, "."))
