from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA512
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_SALT_FILE = ".salt"
_SALT_LEN = 16
_KEY_LEN = 32
_NONCE_LEN = 12
_PBKDF2_ITERATIONS = 100_000


class ThumbCrypto:
    """AES-256-GCM encrypt/decrypt for thumbnail files.

    A per-cache-dir salt is persisted in ``cache_dir/.salt`` (16 bytes,
    random on first use).  The AES key is derived once per instance via
    PBKDF2-HMAC-SHA512 (100 000 iterations).

    When ``key`` is the empty string the instance is a no-op:
    ``encrypt`` / ``decrypt`` return the input unchanged and
    ``is_active`` is ``False``.
    """

    def __init__(self, key: str, cache_dir: Path) -> None:
        self._active = bool(key)
        if not self._active:
            self._aesgcm: AESGCM | None = None
            return
        salt = self._load_or_create_salt(cache_dir)
        kdf = PBKDF2HMAC(
            algorithm=SHA512(),
            length=_KEY_LEN,
            salt=salt,
            iterations=_PBKDF2_ITERATIONS,
        )
        raw_key = kdf.derive(key.encode("utf-8"))
        self._aesgcm = AESGCM(raw_key)

    @property
    def is_active(self) -> bool:
        return self._active

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt *data* → nonce (12 B) || GCM ciphertext+tag."""
        if not self._active or self._aesgcm is None:
            return data
        nonce = os.urandom(_NONCE_LEN)
        return nonce + self._aesgcm.encrypt(nonce, data, None)

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt nonce (12 B) || GCM ciphertext+tag → plaintext."""
        if not self._active or self._aesgcm is None:
            return data
        nonce, ciphertext = data[:_NONCE_LEN], data[_NONCE_LEN:]
        return self._aesgcm.decrypt(nonce, ciphertext, None)

    @staticmethod
    def _load_or_create_salt(cache_dir: Path) -> bytes:
        salt_path = cache_dir / _SALT_FILE
        if salt_path.exists():
            data = salt_path.read_bytes()
            if len(data) == _SALT_LEN:
                return data
        salt = os.urandom(_SALT_LEN)
        cache_dir.mkdir(parents=True, exist_ok=True)
        salt_path.write_bytes(salt)
        return salt
