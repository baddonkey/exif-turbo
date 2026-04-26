#Requires -Version 7
# build_windows.ps1 — Build a self-contained Windows distribution for exif-turbo.
#
# Produces:
#   dist\exif-turbo\                         — unified onedir bundle (GUI + CLI indexer)
#   dist\exif-turbo-<version>-windows.msi    — distributable MSI installer
#
# Requirements:
#   pip install pyinstaller
#   dotnet tool install --global wix          (WiX Toolset v4)
#
# Optional:
#   assets\icon.ico   — application icon (embedded in EXE and shown in installer)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# ── Verify required tools ──────────────────────────────────────────────────────
foreach ($tool in @('pyinstaller', 'wix')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Error "Required tool '$tool' not found. See script header for install instructions."
        exit 1
    }
}

# ── Read version ───────────────────────────────────────────────────────────────
$initFile = 'src\exif_turbo\__init__.py'
$match = Select-String -Path $initFile -Pattern '__version__\s*=\s*[''"]([^''"]+)[''"]'
if (-not $match) {
    Write-Error "Could not read __version__ from $initFile"
    exit 1
}
$VERSION = $match.Matches[0].Groups[1].Value
Write-Host "Building exif-turbo $VERSION for Windows ..."

# ── Build with PyInstaller ─────────────────────────────────────────────────────
pyinstaller exif-turbo.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }
Write-Host "  PyInstaller build complete."

# ── Commit auto-generated version_info.py ─────────────────────────────────────
# The spec regenerates version_info.py at build time; stage it so it stays in sync.
$gitStatus = git status --short version_info.py 2>&1
if ($gitStatus) {
    git add version_info.py
    git commit -m "chore: update version_info.py to $VERSION"
    Write-Host "  Committed version_info.py ($VERSION)."
}

# ── Build MSI with WiX ────────────────────────────────────────────────────────
$AppDir  = (Resolve-Path "dist\exif-turbo").Path
$MsiOut  = "dist\exif-turbo-$VERSION-windows.msi"

# ── Generate icon.ico from logo.png if not already present ───────────────────
$IconFile = Join-Path $RepoRoot "assets\icon.ico"
$LogoPng  = Join-Path $RepoRoot "src\exif_turbo\assets\logo.png"
if (-not (Test-Path $IconFile) -and (Test-Path $LogoPng)) {
    Write-Host "  Generating assets\icon.ico from logo.png ..."
    New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "assets") | Out-Null
    python -c @"
from PIL import Image
import pathlib
img = Image.open(r'$LogoPng').convert('RGBA')
img.save(r'$IconFile', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('icon.ico generated')
"@
}
if (-not (Test-Path $IconFile)) {
    Write-Warning "Icon file not found: $IconFile"
    Write-Warning "The MSI will be built without a custom icon."
    Write-Warning "To add an icon, place a 256x256 .ico file at: $IconFile"
    # Create a minimal placeholder so WiX doesn't fail
    # (WiX requires $(var.IconFile) to resolve — copy the EXE as fallback)
    $IconFile = Join-Path $AppDir "exif-turbo.exe"
}

wix build installer\exif-turbo.wxs `
    -d Version=$VERSION `
    -d AppDir=$AppDir `
    -d IconFile=$IconFile `
    -out $MsiOut

if ($LASTEXITCODE -ne 0) { Write-Error "WiX build failed"; exit 1 }

Write-Host ""
Write-Host "Done! Artifacts:"
Write-Host "  dist\exif-turbo\"
Write-Host "  $MsiOut"
