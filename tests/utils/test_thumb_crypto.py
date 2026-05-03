from __future__ import annotations

from pathlib import Path

import pytest

from exif_turbo.utils.thumb_crypto import ThumbCrypto, WrongPasswordError


# ── basic round-trip ─────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip_returns_original_bytes(tmp_path: Path) -> None:
    # Arrange
    crypto = ThumbCrypto("hunter2", tmp_path)
    payload = b"the quick brown fox" * 100

    # Act
    decrypted = crypto.decrypt(crypto.encrypt(payload))

    # Assert
    assert decrypted == payload


def test_empty_key_is_inactive_passthrough(tmp_path: Path) -> None:
    # Arrange
    crypto = ThumbCrypto("", tmp_path)

    # Act / Assert
    assert crypto.is_active is False
    assert crypto.encrypt(b"hello") == b"hello"
    assert crypto.decrypt(b"hello") == b"hello"


def test_init_creates_thumb_key_file(tmp_path: Path) -> None:
    # Act
    ThumbCrypto("hunter2", tmp_path)

    # Assert
    assert (tmp_path / ".thumb_key").exists()


# ── persistence across instances ─────────────────────────────────────────────


def test_second_instance_with_same_password_decrypts_existing_thumbs(tmp_path: Path) -> None:
    # Arrange
    first = ThumbCrypto("hunter2", tmp_path)
    blob = first.encrypt(b"thumbnail bytes")

    # Act — fresh instance reading the same cache_dir + password
    second = ThumbCrypto("hunter2", tmp_path)

    # Assert
    assert second.decrypt(blob) == b"thumbnail bytes"


def test_wrong_password_on_existing_cache_raises(tmp_path: Path) -> None:
    # Arrange
    ThumbCrypto("hunter2", tmp_path)

    # Act / Assert
    with pytest.raises(WrongPasswordError):
        ThumbCrypto("wrong", tmp_path)


# ── change_password ──────────────────────────────────────────────────────────


def test_change_password_keeps_existing_thumbs_decryptable(tmp_path: Path) -> None:
    # Arrange — encrypt a thumb under the old password
    crypto = ThumbCrypto("old-pw", tmp_path)
    blob = crypto.encrypt(b"jpeg bytes")

    # Act
    ThumbCrypto.change_password(tmp_path, "old-pw", "new-pw")
    new_crypto = ThumbCrypto("new-pw", tmp_path)

    # Assert — same master key, so old thumb file decrypts
    assert new_crypto.decrypt(blob) == b"jpeg bytes"


def test_change_password_old_password_no_longer_works(tmp_path: Path) -> None:
    # Arrange
    ThumbCrypto("old-pw", tmp_path)

    # Act
    ThumbCrypto.change_password(tmp_path, "old-pw", "new-pw")

    # Assert
    with pytest.raises(WrongPasswordError):
        ThumbCrypto("old-pw", tmp_path)


def test_change_password_wrong_old_raises(tmp_path: Path) -> None:
    # Arrange
    ThumbCrypto("right-pw", tmp_path)

    # Act / Assert
    with pytest.raises(WrongPasswordError):
        ThumbCrypto.change_password(tmp_path, "wrong-pw", "new-pw")


def test_change_password_empty_new_raises(tmp_path: Path) -> None:
    # Arrange
    ThumbCrypto("old-pw", tmp_path)

    # Act / Assert
    with pytest.raises(ValueError):
        ThumbCrypto.change_password(tmp_path, "old-pw", "")


# ── legacy v1 cache migration ────────────────────────────────────────────────


def test_legacy_salt_cache_is_migrated_on_init(tmp_path: Path) -> None:
    # Arrange — simulate a v1 cache: a .salt file and some .enc thumbs
    (tmp_path / ".salt").write_bytes(b"x" * 16)
    (tmp_path / "abc123.enc").write_bytes(b"old encrypted thumb")

    # Act
    ThumbCrypto("any-pw", tmp_path)

    # Assert — legacy artefacts removed, new key file created
    assert not (tmp_path / ".salt").exists()
    assert not (tmp_path / "abc123.enc").exists()
    assert (tmp_path / ".thumb_key").exists()
