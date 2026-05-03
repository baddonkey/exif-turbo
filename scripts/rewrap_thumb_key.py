"""Re-wrap the thumb-cache master key under a new password.

Use this if the SQLCipher database password is out of sync with the thumb
cache (e.g. after manual rekey).  This rewraps `.thumb_key` only; no
encrypted thumbnails are touched, so all existing thumbs remain valid.

    python scripts/rewrap_thumb_key.py
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

from exif_turbo.utils.thumb_crypto import ThumbCrypto, WrongPasswordError


def main() -> None:
    cache_dir = Path.home() / ".exif-turbo" / "data" / "index" / "thumbs"
    key_file = cache_dir / ".thumb_key"
    if not key_file.exists():
        raise SystemExit(f"No .thumb_key found at {key_file}")
    print(f"Cache dir: {cache_dir}")
    print(f"Key file:  {key_file} ({key_file.stat().st_size} bytes)\n")
    old_pw = getpass.getpass("Current thumb-cache password (the one set when you last clicked Change Password in the GUI): ")
    new_pw = getpass.getpass("New password (must match the DB password): ")
    confirm = getpass.getpass("Confirm new password: ")
    if new_pw != confirm:
        raise SystemExit("New password and confirmation do not match.")
    try:
        ThumbCrypto.change_password(cache_dir, old_pw, new_pw)
    except WrongPasswordError:
        print("\nFAILED — current thumb-cache password is wrong.", file=sys.stderr)
        raise SystemExit(2)
    print("\nThumb-cache key successfully re-wrapped. Existing thumbs are preserved.")


if __name__ == "__main__":
    main()
