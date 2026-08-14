# -*- mode: python ; coding: utf-8 -*-
# Windows PyInstaller spec — produces a onedir bundle with the GUI.
# Run via: scripts\build_windows.ps1
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# Make the shared version_info generator importable (cwd is the repo root).
sys.path.insert(0, str(Path('scripts').resolve()))
from gen_version_info import write_version_info  # noqa: E402
from stage_runtime_licenses import stage_runtime_licenses  # noqa: E402

_license_dir = stage_runtime_licenses()

# Read version from the single source of truth
_version_match = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']',
    Path('src/exif_turbo/__init__.py').read_text(encoding='utf-8'),
    re.MULTILINE,
)
VERSION = _version_match.group(1) if _version_match else '0.0.0'

# Generate version_info.py for Windows exe metadata
write_version_info(VERSION, Path('version_info.py'))

_icon_path = Path('assets\\icon.ico')
_icon_args = [str(_icon_path)] if _icon_path.exists() else []

_common_datas = [
    ('src\\exif_turbo\\ui\\qml', 'exif_turbo\\ui\\qml'),
    ('src\\exif_turbo\\assets', 'exif_turbo\\assets'),
    ('THIRD-PARTY-LICENSES.md', 'exif_turbo\\assets'),
    (str(_license_dir), 'licenses'),
    ('docs\\user-manual.pdf', 'exif_turbo\\assets'),
    ('src\\exif_turbo\\i18n\\locales', 'exif_turbo\\i18n\\locales'),
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
    ['src\\exif_turbo\\app.py'],
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
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_args,
    version='version_info.py',
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='exif-turbo',
)
