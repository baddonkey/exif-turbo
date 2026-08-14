# -*- mode: python ; coding: utf-8 -*-
# RPM PyInstaller spec — produces a GUI onedir bundle for RPM packaging.
# Run via: python scripts/build_linux.py --rpm-only
import re
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

sys.path.insert(0, str(Path('scripts').resolve()))
from stage_runtime_licenses import stage_runtime_licenses  # noqa: E402

_license_dir = stage_runtime_licenses()

_version_match = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']',
    Path('src/exif_turbo/__init__.py').read_text(encoding='utf-8'),
    re.MULTILINE,
)
VERSION = _version_match.group(1) if _version_match else '0.0.0'

_common_datas = [
    ('src/exif_turbo/ui/qml', 'exif_turbo/ui/qml'),
    ('src/exif_turbo/assets', 'exif_turbo/assets'),
    ('THIRD-PARTY-LICENSES.md', 'exif_turbo/assets'),
    (str(_license_dir), 'licenses'),
    ('docs/user-manual.pdf', 'exif_turbo/assets'),
    ('src/exif_turbo/i18n/locales', 'exif_turbo/i18n/locales'),
    *collect_data_files('open_clip', includes=['model_configs/*.json']),
]

_common_hiddenimports = [
    'exif_turbo.ui',
    'exif_turbo.ui.app_main',
    'exif_turbo.ui.view_models.app_controller',
    'exif_turbo.ui.models.search_list_model',
    'exif_turbo.ui.models.exif_list_model',
    'exif_turbo.ui.workers.index_worker',
    'exif_turbo.ui.workers.thumb_worker',
    'exif_turbo.ui.providers.raw_image_provider',
    'rawpy',
    'pyvips',
    'sqlcipher3',
    'markdown',
    'markdown.extensions.tables',
    'av',
]

a_gui = Analysis(
    ['src/exif_turbo/app.py'],
    pathex=['src'],
    binaries=[],
    datas=_common_datas,
    hiddenimports=_common_hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Exclude GCC runtime libs so the system versions are used at runtime.
# Bundling them causes GLIBCXX version mismatches on distros newer than the
# build container (e.g. Fedora with GCC 13 vs AlmaLinux 9 with GCC 11).
a_gui.binaries = [b for b in a_gui.binaries
                  if not b[0].startswith(('libstdc++', 'libgcc_s'))]

pyz_gui = PYZ(a_gui.pure)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    exclude_binaries=True,        # onedir: Qt libs stay on disk, fast startup
    name='exif-turbo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                # GUI app — no console window
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='exif-turbo-rpm',
)
