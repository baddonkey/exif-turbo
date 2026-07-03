---
description: "Cut a new release: bump version, tag, and build Windows/macOS installers"
name: "Release exif-turbo"
argument-hint: "new version, e.g. 0.2.0"
agent: "agent"
---

Cut a new release of exif-turbo.

## Inputs

The user has provided (or will confirm) a release target: **$ARGUMENTS**

Accepted values:
- `patch`, `minor`, `major` (auto-increment from current `__version__`)
- explicit version `x.y.z`
- explicit triplet `major minor patch`

## Steps

1. **Verify working tree is clean**
   - Run `git status --short`. If there are uncommitted changes, ask the user to commit or stash first.

2. **Prepare release PR (Windows)**
   - Run the PR-prep stage with the provided release target:
     - `python scripts/release_windows.py $ARGUMENTS --stage prepare-pr`
   - This stage bumps version metadata, commits, pushes the current branch, and opens/reuses a PR to `main`.
   - It must not run on `main`.

3. **Stop and wait for merge**
   - Tell the user to merge the PR through the normal review process.
   - Do not push `main` directly.

4. **Publish after merge (Windows)**
   - After the PR is merged and local `main` is up to date, run:
     - `python scripts/release_windows.py <resolved-version> --stage publish`
   - Publish requires an explicit resolved version (`x.y.z` or `major minor patch`), not `patch/minor/major`.

5. **macOS/Linux asset updates (optional)**
   - macOS: `python scripts/update_macos_release.py` (or `--tag v<version>` if needed)
   - Linux: `python scripts/update_linux_release.py --tag v<version>`

6. **Summary**
   - Confirm PR URL, merged state, pushed tag, release URL, and uploaded artifacts.
