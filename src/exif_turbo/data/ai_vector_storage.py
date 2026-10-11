from __future__ import annotations

import os
import hashlib
import io
from pathlib import Path
import struct
import tempfile
from collections.abc import Callable
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..utils.thumb_crypto import ThumbCrypto, WrongPasswordError


class AiVectorAuthenticationError(ValueError):
    """Encrypted AI storage could not be authenticated; never rebuild silently."""


class AiVectorStorage:
    """Publish an authenticated, atomic snapshot without plaintext staging files."""

    _MAGIC = b"ETAI1"
    _LENGTHS = struct.Struct(">QQ")
    _CHUNK_SIZE = 1024 * 1024

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
        header_size = len(self._MAGIC) + self._LENGTHS.size
        header = bytearray()
        destinations = (io.BytesIO(), io.BytesIO(), io.BytesIO())
        lengths: list[int | None] = []
        position = 0

        def consume(chunk: bytes) -> None:
            nonlocal position
            view = memoryview(chunk)
            if len(header) < header_size:
                count = min(header_size - len(header), len(view))
                header.extend(view[:count])
                view = view[count:]
                if len(header) == header_size:
                    if not header.startswith(self._MAGIC):
                        raise ValueError("Unsupported AI snapshot format")
                    lengths.extend(self._LENGTHS.unpack_from(header, len(self._MAGIC)))
                    lengths.append(None)
            while view:
                remaining = lengths[position]
                if remaining == 0:
                    position += 1
                    continue
                count = len(view) if remaining is None else min(remaining, len(view))
                destinations[position].write(view[:count])
                if remaining is not None:
                    lengths[position] = remaining - count
                view = view[count:]

        with self.path.open("rb") as stream:
            self._decrypt_stream(stream, consume)
        if len(header) != header_size or any(length for length in lengths[:2]):
            raise ValueError("Incomplete AI snapshot")
        mapping, metadata, index = (destination.getvalue() for destination in destinations)
        return index, mapping, metadata

    def verify(self) -> None:
        """Authenticate a snapshot without retaining its plaintext payload."""
        header = bytearray()
        size = 0
        header_size = len(self._MAGIC) + self._LENGTHS.size

        def consume(chunk: bytes) -> None:
            nonlocal size
            size += len(chunk)
            header.extend(chunk[:max(0, header_size - len(header))])

        with self.path.open("rb") as stream:
            self._decrypt_stream(stream, consume)
        if len(header) != header_size or not header.startswith(self._MAGIC):
            raise ValueError("Unsupported AI snapshot format")
        lengths = self._LENGTHS.unpack_from(header, len(self._MAGIC))
        if sum(lengths) > size - header_size:
            raise ValueError("Incomplete AI snapshot")

    def _master_key(self) -> bytes:
        self._crypto()
        return ThumbCrypto._unwrap_key_file(self.key_dir / ".thumb_key", self._key)

    def _decrypt_stream(self, stream: BinaryIO, consume: Callable[[bytes], object]) -> None:
        master_key = self._master_key()
        size = stream.seek(0, os.SEEK_END)
        if size < 28:
            raise AiVectorAuthenticationError("AI snapshot authentication failed")
        stream.seek(0)
        nonce = stream.read(12)
        stream.seek(-16, os.SEEK_END)
        tag = stream.read(16)
        decryptor = Cipher(algorithms.AES(master_key), modes.GCM(nonce, tag)).decryptor()
        stream.seek(12)
        remaining = size - 28
        framing_error: Exception | None = None
        try:
            while remaining:
                chunk = stream.read(min(self._CHUNK_SIZE, remaining))
                if not chunk:
                    raise AiVectorAuthenticationError("Incomplete AI snapshot")
                remaining -= len(chunk)
                plaintext = decryptor.update(chunk)
                if framing_error is None:
                    try:
                        consume(plaintext)
                    except Exception as exc:
                        framing_error = exc
            final = decryptor.finalize()
            if framing_error is not None:
                raise framing_error
            consume(final)
        except InvalidTag as exc:
            raise AiVectorAuthenticationError("AI snapshot authentication failed") from exc

    def migrate(self, index_path: Path, map_path: Path, metadata_path: Path) -> None:
        """Encrypt legacy artifacts before removing their plaintext copies."""
        paths = (index_path, map_path, metadata_path)
        if self.path.exists():
            self.verify()
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

    def save(self, index: bytes | memoryview, mapping: bytes, metadata: bytes) -> None:
        master_key = self._master_key()
        parts = (
            self._MAGIC + self._LENGTHS.pack(len(mapping), len(metadata)),
            mapping, metadata, index,
        )
        nonce = os.urandom(12)
        encryptor = Cipher(algorithms.AES(master_key), modes.GCM(nonce)).encryptor()
        expected_digest = hashlib.sha256()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(nonce)
                for part in parts:
                    view = memoryview(part)
                    for offset in range(0, len(view), self._CHUNK_SIZE):
                        chunk = view[offset:offset + self._CHUNK_SIZE]
                        expected_digest.update(chunk)
                        stream.write(encryptor.update(chunk))
                stream.write(encryptor.finalize())
                stream.write(encryptor.tag)
                stream.flush()
                os.fsync(stream.fileno())
            actual_digest = hashlib.sha256()
            with temporary.open("rb") as stream:
                self._decrypt_stream(stream, actual_digest.update)
            if actual_digest.digest() != expected_digest.digest():
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
        return cls._split_payload(payload)

    @classmethod
    def _split_payload(cls, payload: bytes) -> tuple[bytes, bytes, bytes]:
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