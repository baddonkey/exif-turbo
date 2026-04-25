---
description: "Cut a new release: bump version, tag, and build Windows/macOS installers"
name: "Release exif-turbo"
argument-hint: "new version, e.g. 0.2.0"
agent: "agent"
---

Cut a new release of exif-turbo.

## Inputs

The user has provided (or will confirm) the new version: **$ARGUMENTS**

## Steps

1. **Verify working tree is clean**
   - Run `git status --short`. If there are uncommitted changes, ask the user to commit them first.

2. **Bump the version**
   - Update `__version__` in [src/exif_turbo/__init__.py](../src/exif_turbo/__init__.py)
   - Update `version` under `[project]` in [pyproject.toml](../pyproject.toml)
   - Both must match the new version.

3. **Commit the version bump**
   - Stage and commit: `git commit -am "chore: bump version to <version>"`
   - Do NOT push yet — wait for the user's explicit approval.

4. **Create the annotated git tag**
   - Run: `git tag -a v<version> -m "Release v<version>"`
   - Show the tag details to the user.

5. **Confirm before building**
   - Ask the user: "Ready to build the binaries? This will run PyInstaller and (on Windows) WiX."

6. **Build the release binaries**
   - On **Windows**: run `pwsh scripts\build_windows.ps1`
   - On **macOS**: run `bash scripts/build_macos.sh`
   - Report the output artifacts from `dist\`.

7. **Summary**
   - List all artifacts produced (`.msi`, `.dmg`, onedir folder).
   - Remind the user to push the tag and commit:
     ```
     git push origin main
     git push origin v<version>
     ```
   - Optionally link the GitHub Releases page to upload the artifacts manually.
