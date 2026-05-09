---
description: "Rebuild the macOS DMG and upload it to an existing GitHub release"
name: "Update DMG on existing release"
argument-hint: "version tag, e.g. 1.8.1"
agent: "agent"
---

Rebuild the macOS DMG for an existing release and upload it, replacing any
previous macOS asset.

## Inputs

Target version (tag): **$ARGUMENTS**

## Steps

1. **Verify the release exists**
   - Retrieve release metadata via the GitHub API using the token from the
     macOS keychain (`security find-internet-password -s github.com -w`).
   - `curl -s -H "Authorization: token $TOKEN" "https://api.github.com/repos/baddonkey/exif-turbo/releases/tags/v<version>"`
   - Capture the release ID and upload URL for later steps.
   - If the release is not found, stop and tell the user.

2. **Compile .mo translation files** — do NOT touch .po files.
   - Run: `pybabel compile -d src/exif_turbo/i18n/locales -D exif_turbo`

3. **Build the macOS app bundle and DMG**
   - Run: `python scripts/build_macos.py`
   - The expected output artifact is `dist/exif-turbo-<version>-macos.dmg`.
   - If the build fails, stop and show the error.

4. **Delete any existing macOS DMG asset on the release**
   - List current assets: parse the `assets` array from the release metadata
     fetched in step 1.
   - For each asset whose name ends with `-macos.dmg`, delete it:
     `curl -X DELETE -H "Authorization: token $TOKEN" "https://api.github.com/repos/baddonkey/exif-turbo/releases/assets/<asset_id>"`

5. **Upload the new DMG**
   - Use the upload URL from step 1 (strip the `{?name,label}` template suffix).
   - Upload **without** a `label` parameter — the filename must be the display name.
   - Asset name: `exif-turbo-<version>-macos.dmg`
   ```
   curl -H "Authorization: token $TOKEN" \
        -H "Content-Type: application/octet-stream" \
        --data-binary @dist/exif-turbo-<version>-macos.dmg \
        "<upload_url>?name=exif-turbo-<version>-macos.dmg"
   ```
   - Verify the response is HTTP 201.

6. **Summary**
   - Confirm the asset name and size visible on the release page.
   - Print: `https://github.com/baddonkey/exif-turbo/releases/tag/v<version>`
