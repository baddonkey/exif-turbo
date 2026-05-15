# -*- mode: python ; coding: utf-8 -*-
# RPM PyInstaller spec — produces a GUI onedir bundle for RPM packaging.
# Run via: python scripts/build_linux.py --rpm-only
import re
from pathlib import Path

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
    ('docs/user-manual.pdf', 'exif_turbo/assets'),
    ('src/exif_turbo/i18n/locales', 'exif_turbo/i18n/locales'),
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
    hookspath=[],
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
