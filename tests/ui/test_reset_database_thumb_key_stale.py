"""E2E proof: ``resetDatabase`` leaves the ``ThumbnailImageProvider`` with a
stale in-memory thumb-encryption key.

Bug report (Debian, manual repro):
    1. Reset Database in Settings.
    2. Re-add large folders, wait for index + thumb + preview build to finish.
    3. Search tab: every thumbnail in the result grid stays blank.
    4. Quit and relaunch the app → all thumbnails render correctly.

Hypothesis:
    ``AppController.resetDatabase`` ``rmtree``s the cache directory, which
    deletes ``.thumb_key`` (the password-wrapped AES-256-GCM master key).
    The next ``ThumbWorker`` run instantiates a fresh ``ThumbCrypto`` against
    the now-empty cache dir, generates a *new* random master key, writes a
    *new* ``.thumb_key``, and encrypts new ``.enc`` files with that new key.

    But the live ``ThumbnailImageProvider`` was configured once via
    ``set_key()`` at unlock time and still holds a ``ThumbCrypto`` carrying
    the *old* master key.  Every ``image://thumb/<sha1>`` request decrypts
    with the old key → ``InvalidTag`` → silently swallowed → blank
    ``QImage()`` returned to QML.  Restart fixes it because ``unlock()``
    re-runs ``set_key()`` and reads the new ``.thumb_key`` from disk.

Test layout (single test, three phases):
    A. Happy path — encrypt a thumbnail with the master key created at unlock,
       assert the provider returns a non-null image.
    B. The fix    — ``resetDatabase`` + post-reset re-encryption with a fresh
       master key.  Provider must be re-keyed by ``resetDatabase``, so
       ``requestImage`` must return a non-null image (regression guard).
    C. Idempotence — re-run ``set_key`` after the reset; provider still
       decrypts successfully.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image
from PySide6.QtCore import QSize
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.providers.thumb_image_provider import ThumbnailImageProvider
from exif_turbo.ui.view_models.app_controller import AppController
from exif_turbo.utils.thumb_crypto import ThumbCrypto

_PASSWORD = "correct horse battery staple"
_THUMB_KEY_FILE = ".thumb_key"


def _png_bytes() -> bytes:
    """Return a tiny valid PNG as bytes — content of an encrypted thumb file."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(10, 200, 50)).save(buf, format="PNG")
    return buf.getvalue()


def _write_encrypted_thumb(cache_dir: Path, sha1: str) -> None:
    """Encrypt a tiny PNG with a fresh ``ThumbCrypto`` and write ``<sha1>.enc``.

    Each call mirrors what ``ThumbWorker`` does on a worker thread: it
    instantiates ``ThumbCrypto(password, cache_dir)`` which reads the current
    ``.thumb_key`` (or creates one if absent) and encrypts the PNG with the
    master key wrapped therein.
    """
    crypto = ThumbCrypto(_PASSWORD, cache_dir)
    enc = crypto.encrypt(_png_bytes())
    (cache_dir / f"{sha1}.enc").write_bytes(enc)


@pytest.fixture
def encrypted_db(tmp_path: Path) -> Path:
    """Encrypted SQLCipher DB with one indexed image (no real file needed)."""
    db_path = tmp_path / "index.db"
    repo = ImageIndexRepository(db_path, key=_PASSWORD)
    repo.upsert_image(
        path=str(tmp_path / "img.jpg"),
        filename="img.jpg",
        mtime=1_700_000_000.0,
        size=12_345,
        metadata={"FileName": "img.jpg"},
        metadata_text="img.jpg",
    )
    repo.commit()
    repo.close()
    return db_path


@pytest.fixture
def wired_controller(
    encrypted_db: Path, tmp_path: Path
) -> Generator[tuple[AppController, ThumbnailImageProvider, Path], None, None]:
    """Build an AppController wired to a real ThumbnailImageProvider."""
    cache_dir = tmp_path / "thumbs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    provider = ThumbnailImageProvider()
    ctrl = AppController(
        encrypted_db,
        SearchListModel(cache_dir=cache_dir),
        ExifListModel(),
        FolderListModel(),
        cache_dir=cache_dir,
        thumb_provider=provider,
    )
    yield ctrl, provider, cache_dir
    if ctrl._thumb_worker and ctrl._thumb_worker.isRunning():
        ctrl._thumb_worker.cancel()
        ctrl._thumb_worker.wait(5000)
    if ctrl._index_worker and ctrl._index_worker.isRunning():
        ctrl._index_worker.cancel()
        ctrl._index_worker.wait(5000)
    ctrl.close()


def test_reset_database_leaves_thumb_provider_with_stale_master_key(
    qtbot: QtBot,
    wired_controller: tuple[AppController, ThumbnailImageProvider, Path],
) -> None:
    """resetDatabase rmtrees .thumb_key; provider keeps old key in memory."""
    ctrl, provider, cache_dir = wired_controller

    # Arrange — unlock so the provider receives master key M1 via set_key().
    with qtbot.waitSignal(ctrl.isLockedChanged, timeout=3000):
        ctrl.unlock(_PASSWORD)
    assert not ctrl.isLocked
    thumb_key_path = cache_dir / _THUMB_KEY_FILE
    assert thumb_key_path.exists(), ".thumb_key should be created by set_key"
    master_key_v1 = thumb_key_path.read_bytes()

    # Phase A: let any ThumbWorker started by unlock() finish so it is no
    # longer racing with our test writes against the cache dir.
    qtbot.waitUntil(lambda: not ctrl.isBuildingThumbs, timeout=15_000)

    # ── Phase A — provider decrypts thumbs encrypted under M1 ───────────────
    sha1_a = "a" * 40
    _write_encrypted_thumb(cache_dir, sha1_a)
    qimg_a = provider.requestImage(sha1_a, QSize(), QSize())
    assert not qimg_a.isNull(), (
        "Phase A failed: provider could not decrypt a thumb encrypted with "
        "the master key it was just configured with."
    )

    # ── Phase B — resetDatabase wipes .thumb_key and re-keys the provider ───
    ctrl.resetDatabase()
    # resetDatabase rmtrees the cache dir and immediately calls set_key(),
    # which creates a fresh .thumb_key with a new random master key M2.
    assert thumb_key_path.exists(), (
        "set_key inside resetDatabase should have recreated .thumb_key"
    )
    # Mirror ThumbWorker's behaviour after the reset: a fresh ThumbCrypto
    # reads the new .thumb_key and encrypts a thumbnail with M2.
    sha1_b = "b" * 40
    _write_encrypted_thumb(cache_dir, sha1_b)
    master_key_v2 = thumb_key_path.read_bytes()
    assert master_key_v2 != master_key_v1, (
        "Sanity check: post-reset .thumb_key must wrap a different master key"
    )

    # The fix: resetDatabase now calls set_key after rmtree so the provider
    # holds the new master key.  A thumb encrypted under M2 must decrypt OK.
    qimg_b = provider.requestImage(sha1_b, QSize(), QSize())
    assert not qimg_b.isNull(), (
        "REGRESSION: provider returned a null image for a thumb encrypted "
        "under the post-reset master key.  resetDatabase must call set_key "
        "after recreating the cache dir."
    )

    # ── Phase C — calling set_key again is idempotent ───────────────────────
    provider.set_key(_PASSWORD, cache_dir)
    qimg_c = provider.requestImage(sha1_b, QSize(), QSize())
    assert not qimg_c.isNull(), (
        "Provider failed to decrypt the new thumb even after set_key was "
        "called explicitly — the proposed fix does not work."
    )
