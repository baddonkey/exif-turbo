---
description: "Remove all uploaded assets (MSI, DMG, etc.) from a specific GitHub release without deleting the release itself. Asks for confirmation before deleting."
name: "Strip Release Assets"
argument-hint: "vX.Y.Z"
agent: "agent"
---

Remove all binary assets from a GitHub release, leaving the release page and its notes intact.

## Inputs

The target release tag is: **$ARGUMENTS**

## Steps

1. **Resolve the release**
   - Run: `gh release view $ARGUMENTS --json tagName,name,assets`
   - Display the release name, tag, and the full list of assets (name + size) to the user.
   - If no tag was provided or the release is not found, ask the user to supply the correct tag.

2. **Ask for confirmation**
   - Show the user exactly which assets will be deleted, e.g.:
     ```
     The following assets will be permanently removed from release $ARGUMENTS:
       • exif-turbo-X.Y.Z-windows.msi  (208 MB)
       • exif-turbo-X.Y.Z-macos.dmg    (195 MB)
     The release page and its notes will NOT be deleted.
     Proceed? (yes / no)
     ```
   - Wait for explicit confirmation. Do NOT proceed if the answer is anything other than "yes".

3. **Delete each asset**
   - For each asset listed in step 1, run:
     `gh release delete-asset $ARGUMENTS "<asset-name>" --yes`
   - Report each deletion as it completes.

4. **Verify**
   - Run: `gh release view $ARGUMENTS --json assets`
   - Confirm the assets list is now empty (or list any that remain).

5. **Summary**
   - Report how many assets were removed and confirm the release page is still live at:
     `https://github.com/baddonkey/exif-turbo/releases/tag/$ARGUMENTS`
