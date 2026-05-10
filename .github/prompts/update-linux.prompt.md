---
description: "Rebuild the Linux DEB and RPM packages and upload them to an existing GitHub release"
name: "Update Linux packages on existing release"
argument-hint: "version tag, e.g. 1.8.1"
agent: "agent"
---

Rebuild the Linux DEB and RPM packages for an existing release and upload them,
replacing any previous Linux assets.

## Inputs

Target version (tag): **$ARGUMENTS**

## Steps

1. **Verify the release exists**
   - Run: `gh release view v<version> --repo baddonkey/exif-turbo`
   - If the release is not found, stop and tell the user.

2. **Compile .mo translation files** — do NOT touch .po files.
   - Run: `pybabel compile -d src/exif_turbo/i18n/locales -D exif_turbo`

3. **Build the Linux DEB and RPM packages**
   - Run: `python scripts/build_linux.py`
   - Expected output artifacts:
     - `dist/exif-turbo-<version>-linux.deb`
     - `dist/exif-turbo-<version>-linux.rpm`
   - If the build fails, stop and show the error.

4. **Delete any existing Linux assets on the release**
   - List current assets: `gh release view v<version> --repo baddonkey/exif-turbo --json assets --jq '.assets[].name'`
   - For each asset whose name ends with `-linux.deb` or `-linux.rpm`, delete it:
     `gh release delete-asset v<version> <asset-name> --repo baddonkey/exif-turbo --yes`

5. **Upload the new packages**
   ```
   gh release upload v<version> \
     dist/exif-turbo-<version>-linux.deb \
     dist/exif-turbo-<version>-linux.rpm \
     --repo baddonkey/exif-turbo \
     --clobber
   ```

6. **Summary**
   - Confirm the asset names and sizes visible on the release page.
   - Print: `https://github.com/baddonkey/exif-turbo/releases/tag/v<version>`
