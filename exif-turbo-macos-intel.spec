# -*- mode: python ; coding: utf-8 -*-
# Intel (x86_64) macOS PyInstaller spec — produces a .app bundle.
# Run via: python scripts/build_macos.py --arch intel
import re
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

_version_match = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']',
    Path('src/exif_turbo/__init__.py').read_text(encoding='utf-8'),
    re.MULTILINE,
)
VERSION = _version_match.group(1) if _version_match else '0.0.0'

_icon_icns = Path('assets/icon.icns')
_icon_arg = str(_icon_icns) if _icon_icns.exists() else None

a = Analysis(
    ['src/exif_turbo/app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('src/exif_turbo/ui/qml', 'exif_turbo/ui/qml'),
        ('src/exif_turbo/assets', 'exif_turbo/assets'),
        ('THIRD-PARTY-LICENSES.md', 'exif_turbo/assets'),
        ('docs/user-manual.pdf', 'exif_turbo/assets'),
        ('src/exif_turbo/i18n/locales', 'exif_turbo/i18n/locales'),
        *collect_data_files('open_clip', includes=['model_configs/*.json']),
    ],
    hiddenimports=[
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
        'faiss',
        'certifi',
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt3D modules are not used by this app; excluding avoids a PyInstaller
        # bug where it tries to copy framework binaries into non-existent dirs.
        'PySide6.QtQuick3D',
        'PySide6.QtQuick3DAssetImport',
        'PySide6.QtQuick3DAssetUtils',
        'PySide6.QtQuick3DEffects',
        'PySide6.QtQuick3DGlslParser',
        'PySide6.QtQuick3DHelpers',
        'PySide6.QtQuick3DHelpersImpl',
        'PySide6.QtQuick3DIblBaker',
        'PySide6.QtQuick3DParticleEffects',
        'PySide6.QtQuick3DParticles',
        'PySide6.QtQuick3DRuntimeRender',
        'PySide6.QtQuick3DSpatialAudio',
        'PySide6.QtQuick3DUtils',
        'PySide6.QtQuick3DXr',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,        # onedir: Qt libs live inside the .app bundle
    name='exif-turbo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_arg,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='exif-turbo',
)

# ── .app bundle ───────────────────────────────────────────────────────────────
app = BUNDLE(
    coll,
    name='exif-turbo.app',
    icon=_icon_arg,
    bundle_identifier='com.exif-turbo.app',
    info_plist={
        'CFBundleName': 'exif-turbo',
        'CFBundleDisplayName': 'exif-turbo',
        'CFBundleExecutable': 'exif-turbo',
        'CFBundleVersion': VERSION,
        'CFBundleShortVersionString': VERSION,
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': '????',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
        'NSPrincipalClass': 'NSApplication',
        'NSRequiresAquaSystemAppearance': False,  # supports Dark Mode
        # Declare supported languages so macOS uses the correct language for
        # native Cocoa menu items (Quit, Hide, …). Both CFBundleDevelopmentRegion
        # and physical .lproj directories (created by build_macos.py) are needed;
        # CFBundleLocalizations alone is not sufficient.
        'CFBundleDevelopmentRegion': 'en',
        'CFBundleLocalizations': ['en', 'de', 'fr', 'it', 'rm'],
    },
)
