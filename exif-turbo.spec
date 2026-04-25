# -*- mode: python ; coding: utf-8 -*-
# Windows PyInstaller spec — produces a onedir bundle with GUI + CLI indexer.
# Run via: scripts\build_windows.ps1
import re
from pathlib import Path

# Read version from the single source of truth
_version_match = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']',
    Path('src/exif_turbo/__init__.py').read_text(encoding='utf-8'),
    re.MULTILINE,
)
VERSION = _version_match.group(1) if _version_match else '0.0.0'
_major, _minor, _patch = (VERSION.split('.') + ['0', '0', '0'])[:3]
VERSION_TUPLE = (int(_major), int(_minor), int(_patch), 0)

# Generate version_info.py for Windows exe metadata
Path('version_info.py').write_text(
    f'''\
# Auto-generated from exif-turbo.spec — do not edit manually.
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers={VERSION_TUPLE},
        prodvers={VERSION_TUPLE},
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "exif-turbo"),
                        StringStruct("FileDescription", "exif-turbo — Image EXIF metadata search and indexing tool"),
                        StringStruct("FileVersion", "{VERSION}"),
                        StringStruct("InternalName", "exif-turbo"),
                        StringStruct("LegalCopyright", "Copyright (c) 2025 exif-turbo contributors"),
                        StringStruct("OriginalFilename", "exif-turbo.exe"),
                        StringStruct("ProductName", "exif-turbo"),
                        StringStruct("ProductVersion", "{VERSION}"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
''',
    encoding='utf-8',
)

_icon_path = Path('assets\\icon.ico')
_icon_args = [str(_icon_path)] if _icon_path.exists() else []

_common_datas = [
    ('src\\exif_turbo\\ui\\qml', 'exif_turbo\\ui\\qml'),
    ('src\\exif_turbo\\assets', 'exif_turbo\\assets'),
    ('THIRD-PARTY-LICENSES.md', 'exif_turbo\\assets'),
    ('docs\\user-manual.pdf', 'exif_turbo\\assets'),
    ('src\\exif_turbo\\i18n\\locales', 'exif_turbo\\i18n\\locales'),
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
]

# ── GUI executable ─────────────────────────────────────────────────────────────
a_gui = Analysis(
    ['src\\exif_turbo\\app.py'],
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

# ── CLI indexer ────────────────────────────────────────────────────────────────
a_cli = Analysis(
    ['src\\exif_turbo\\indexer.py'],
    pathex=['src'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'exif_turbo.indexing',
        'exif_turbo.indexing.cli',
        'exif_turbo.indexing.indexer_service',
        'rawpy',
        'sqlcipher3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)

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

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    exclude_binaries=True,
    name='exif-turbo-index',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,                 # CLI tool — keep console
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
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='exif-turbo',
)
