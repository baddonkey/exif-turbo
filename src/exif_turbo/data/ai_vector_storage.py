from __future__ import annotations

import os
from pathlib import Path
import struct
import tempfile

from ..utils.thumb_crypto import ThumbCrypto, WrongPasswordError


class AiVectorAuthenticationError(ValueError):
    """Encrypted AI storage could not be authenticated; never rebuild silently."""


class AiVectorStorage:
    """Publish an authenticated, atomic snapshot without plaintext staging files."""

    _MAGIC = b"ETAI1"
    _LENGTHS = struct.Struct(">QQ")

    def __init__(self, index_path: Path, key: str) -> None:
        self.path = index_path.with_name(index_path.name + ".enc")
        self.key_dir = index_path.with_name(index_path.name + ".keys")
        self._key = key

    def _crypto(self) -> ThumbCrypto:
        if not self._key:
            raise AiVectorAuthenticationError("A password is required for the AI index")
        if self.path.exists() and not (self.key_dir / ".thumb_key").exists():
            raise AiVectorAuthenticationError("The AI index encryption key is missing")
        try:
            return ThumbCrypto(self._key, self.key_dir)
        except (WrongPasswordError, ValueError) as exc:
            pending = self.key_dir / "password.pending"
            if pending.exists():
                try:
                    ThumbCrypto._unwrap_key_file(pending, self._key)
                except (WrongPasswordError, ValueError):
                    pass
                else:
                    os.replace(pending, self.key_dir / ".thumb_key")
                    return ThumbCrypto(self._key, self.key_dir)
            raise AiVectorAuthenticationError("Cannot unlock the AI index encryption key") from exc

    def load(self) -> tuple[bytes, bytes, bytes]:
        crypto = self._crypto()
        return self._decode(self.path.read_bytes(), crypto)

    def migrate(self, index_path: Path, map_path: Path, metadata_path: Path) -> None:
        """Encrypt legacy artifacts before removing their plaintext copies."""
        paths = (index_path, map_path, metadata_path)
        if self.path.exists():
            self.load()
        elif any(path.exists() for path in paths):
            parts = tuple(path.read_bytes() if path.exists() else b"" for path in paths)
            self.save(*parts)
        else:
            self._crypto()
        (self.key_dir / "password.pending").unlink(missing_ok=True)
        for path in paths:
            path.unlink(missing_ok=True)
            for temporary in path.parent.glob(f".{path.name}.*.tmp"):
                temporary.unlink()

    def save(self, index: bytes, mapping: bytes, metadata: bytes) -> None:
        crypto = self._crypto()
        payload = (
            self._MAGIC
            + self._LENGTHS.pack(len(mapping), len(metadata))
            + mapping
            + metadata
            + index
        )
        encrypted = crypto.encrypt(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            if self._decode(temporary.read_bytes(), crypto) != (index, mapping, metadata):
                raise ValueError("AI snapshot verification failed")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _decode(cls, encrypted: bytes, crypto: ThumbCrypto) -> tuple[bytes, bytes, bytes]:
        try:
            payload = crypto.decrypt(encrypted)
        except Exception as exc:
            raise AiVectorAuthenticationError("AI snapshot authentication failed") from exc
        offset = len(cls._MAGIC) + cls._LENGTHS.size
        if len(payload) < offset or not payload.startswith(cls._MAGIC):
            raise ValueError("Unsupported AI snapshot format")
        mapping_length, metadata_length = cls._LENGTHS.unpack_from(payload, len(cls._MAGIC))
        mapping_end = offset + mapping_length
        metadata_end = mapping_end + metadata_length
        if metadata_end > len(payload):
            raise ValueError("Incomplete AI snapshot")
        return payload[metadata_end:], payload[offset:mapping_end], payload[mapping_end:metadata_end]

    def change_password(self, new_password: str) -> None:
        self.stage_password_change(new_password)
        self.finish_password_change(new_password)

    def stage_password_change(self, new_password: str) -> None:
        """Retain the current wrapper until the database rekey has succeeded."""
        if not new_password:
            raise ValueError("new_password must not be empty")
        self._crypto()
        master_key = ThumbCrypto._unwrap_key_file(self.key_dir / ".thumb_key", self._key)
        pending = self.key_dir / "password.pending"
        ThumbCrypto._write_key_file(pending, master_key, new_password)
        with pending.open("r+b") as stream:
            os.fsync(stream.fileno())

    def finish_password_change(self, new_password: str) -> None:
        self._key = new_password
        self._crypto()
        (self.key_dir / "password.pending").unlink(missing_ok=True)