#Requires -Version 7
# tag_release.ps1 — Create and push a git tag for the current version.
#
# Usage:
#   pwsh scripts\tag_release.ps1              # tag vX.Y.Z and push
#   pwsh scripts\tag_release.ps1 -DryRun      # show what would happen, don't execute
#
# To bump the version first, edit src\exif_turbo\__init__.py and pyproject.toml,
# commit the change, then run this script.

param(
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# ── Read version ───────────────────────────────────────────────────────────────
$initFile = 'src\exif_turbo\__init__.py'
$match = Select-String -Path $initFile -Pattern '__version__\s*=\s*[''"]([^''"]+)[''"]'
if (-not $match) {
    Write-Error "Could not read __version__ from $initFile"
    exit 1
}
$VERSION = $match.Matches[0].Groups[1].Value
$TAG = "v$VERSION"

Write-Host "Version : $VERSION"
Write-Host "Tag     : $TAG"

# ── Check for uncommitted changes ──────────────────────────────────────────────
$status = git status --porcelain
if ($status) {
    Write-Warning "Working tree has uncommitted changes:"
    Write-Warning $status
    $confirm = Read-Host "Tag anyway? [y/N]"
    if ($confirm -ne 'y') {
        Write-Host "Aborted."
        exit 0
    }
}

# ── Check tag doesn't already exist ───────────────────────────────────────────
$existing = git tag --list $TAG
if ($existing) {
    Write-Error "Tag '$TAG' already exists. Delete it first: git tag -d $TAG"
    exit 1
}

# ── Create annotated tag ───────────────────────────────────────────────────────
if ($DryRun) {
    Write-Host "[DRY RUN] Would run: git tag -a $TAG -m `"Release $TAG`""
    Write-Host "[DRY RUN] Would run: git push origin $TAG"
} else {
    git tag -a $TAG -m "Release $TAG"
    Write-Host "  Created tag: $TAG"

    $push = Read-Host "Push tag to origin? [Y/n]"
    if ($push -ne 'n') {
        git push origin $TAG
        Write-Host "  Pushed tag $TAG to origin."
    } else {
        Write-Host "  Tag created locally. Push manually: git push origin $TAG"
    }
}
