from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA512
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Legacy (v1) layout — password directly derives the file-encryption key
# via PBKDF2 over a per-cache-dir salt in ``.salt``.  Caches in this layout
# are migrated on next unlock by deleting the encrypted thumbs (which are
# regenerable) and switching to v2.
_LEGACY_SALT_FILE = ".salt"

# v2 layout — a random 32-byte "master key" encrypts thumbnails.  The
# master key is itself stored, password-wrapped, in ``.thumb_key``.  This
# means changing the user's password only re-wraps the master key; the
# thumbs themselves never have to be rewritten.
_KEY_FILE = ".thumb_key"
_KEY_FILE_MAGIC = b"ETK1"  # 4-byte format identifier
_SALT_LEN = 16
_KEY_LEN = 32
_NONCE_LEN = 12
_GCM_TAG_LEN = 16
_PBKDF2_ITERATIONS = 100_000
_KEY_FILE_LEN = (
    len(_KEY_FILE_MAGIC) + _SALT_LEN + 4 + _NONCE_LEN + _KEY_LEN + _GCM_TAG_LEN
)


class WrongPasswordError(ValueError):
    """Raised when the supplied password fails to unwrap the thumb master key."""


class ThumbCrypto:
    """AES-256-GCM encrypt/decrypt for thumbnail files.

    Uses a random per-cache-dir master key that is itself stored
    password-wrapped on disk in ``cache_dir/.thumb_key``.  This decouples
    file encryption from the user's password so that a password change
    only needs to re-wrap the master key — the thumbnail files never have
    to be re-encrypted.

    When ``key`` is the empty string the instance is a no-op:
    ``encrypt`` / ``decrypt`` return the input unchanged and
    ``is_active`` is ``False``.

    Migration: caches created by an earlier version (with a ``.salt`` file
    and no ``.thumb_key``) are migrated transparently on first instantiation
    by removing the legacy encrypted thumbs (regenerable) and creating a
    fresh ``.thumb_key``.
    """

    def __init__(self, key: str, cache_dir: Path) -> None:
        self._active = bool(key)
        if not self._active:
            self._aesgcm: AESGCM | None = None
            return
        cache_dir.mkdir(parents=True, exist_ok=True)
        master_key = self._load_or_create_master_key(cache_dir, key)
        self._aesgcm = AESGCM(master_key)

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

    # -- master-key wrapping ------------------------------------------------

    @classmethod
    def _load_or_create_master_key(cls, cache_dir: Path, password: str) -> bytes:
        key_path = cache_dir / _KEY_FILE
        if key_path.exists():
            return cls._unwrap_key_file(key_path, password)
        # Legacy v1 cache?  Drop encrypted thumbs (they're regenerable) and
        # the old salt, then bootstrap a v2 key file.
        legacy_salt = cache_dir / _LEGACY_SALT_FILE
        if legacy_salt.exists():
            cls._purge_legacy_cache(cache_dir)
        master_key = os.urandom(_KEY_LEN)
        cls._write_key_file(key_path, master_key, password)
        return master_key

    @staticmethod
    def _purge_legacy_cache(cache_dir: Path) -> None:
        for entry in cache_dir.iterdir():
            if entry.is_file() and (
                entry.suffix == ".enc"
                or entry.name == _LEGACY_SALT_FILE
                or entry.name == "thumbs_skipped.log"
                or entry.suffix == ".skip"
            ):
                try:
                    entry.unlink()
                except OSError:
                    pass

    @staticmethod
    def _derive_wrapper_key(password: str, salt: bytes, iterations: int) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=SHA512(),
            length=_KEY_LEN,
            salt=salt,
            iterations=iterations,
        )
        return kdf.derive(password.encode("utf-8"))

    @classmethod
    def _write_key_file(cls, key_path: Path, master_key: bytes, password: str) -> None:
        salt = os.urandom(_SALT_LEN)
        wrapper = AESGCM(cls._derive_wrapper_key(password, salt, _PBKDF2_ITERATIONS))
        nonce = os.urandom(_NONCE_LEN)
        wrapped = wrapper.encrypt(nonce, master_key, None)
        payload = (
            _KEY_FILE_MAGIC
            + salt
            + _PBKDF2_ITERATIONS.to_bytes(4, "big")
            + nonce
            + wrapped
        )
        # Atomic write
        tmp = key_path.with_suffix(key_path.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, key_path)

    @classmethod
    def _unwrap_key_file(cls, key_path: Path, password: str) -> bytes:
        data = key_path.read_bytes()
        if len(data) != _KEY_FILE_LEN or data[: len(_KEY_FILE_MAGIC)] != _KEY_FILE_MAGIC:
            raise ValueError(f"Corrupt thumb key file: {key_path}")
        offset = len(_KEY_FILE_MAGIC)
        salt = data[offset : offset + _SALT_LEN]
        offset += _SALT_LEN
        iterations = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
        nonce = data[offset : offset + _NONCE_LEN]
        offset += _NONCE_LEN
        wrapped = data[offset:]
        wrapper = AESGCM(cls._derive_wrapper_key(password, salt, iterations))
        try:
            return wrapper.decrypt(nonce, wrapped, None)
        except InvalidTag as exc:
            raise WrongPasswordError("Incorrect thumb-cache password") from exc

    @classmethod
    def change_password(
        cls, cache_dir: Path, old_password: str, new_password: str
    ) -> None:
        """Re-wrap the thumb master key with *new_password*.

        No thumbnail files are touched — only ``.thumb_key`` is rewritten.
        Raises :class:`WrongPasswordError` when *old_password* is wrong.
        If the cache has no ``.thumb_key`` yet (no encrypted thumbs ever
        written, or v1 cache that hasn't been migrated), a fresh master key
        is bootstrapped under *new_password*.
        """
        if not new_password:
            raise ValueError("new_password must not be empty")
        cache_dir.mkdir(parents=True, exist_ok=True)
        key_path = cache_dir / _KEY_FILE
        if key_path.exists():
            master_key = cls._unwrap_key_file(key_path, old_password)
        else:
            legacy_salt = cache_dir / _LEGACY_SALT_FILE
            if legacy_salt.exists():
                cls._purge_legacy_cache(cache_dir)
            master_key = os.urandom(_KEY_LEN)
        cls._write_key_file(key_path, master_key, new_password)
