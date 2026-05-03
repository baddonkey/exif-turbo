from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository
from ...utils.thumb_crypto import ThumbCrypto


class PasswordChangeWorker(QThread):
    """Re-encrypt the SQLCipher database under a new password.

    SQLCipher's ``PRAGMA rekey`` rewrites every page of the database file —
    on a large index this can take several seconds, so it must run off the
    GUI thread.  The worker opens its own connection with the *old* key,
    issues the rekey, closes, and (if successful) re-wraps the thumb-cache
    master key so existing thumbnails remain decryptable.

    Once :py:attr:`finished` fires the controller is responsible for
    re-opening its long-lived connections under the new key.
    """

    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        old_password: str,
        new_password: str,
        cache_dir: Path | None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._old_password = old_password
        self._new_password = new_password
        self._cache_dir = cache_dir

    def run(self) -> None:  # noqa: D401 — QThread API
        repo: ImageIndexRepository | None = None
        try:
            repo = ImageIndexRepository(self._db_path, key=self._old_password)
            repo.change_password(self._new_password)
        except Exception as exc:  # noqa: BLE001
            if repo is not None:
                try:
                    repo.close()
                except Exception:  # noqa: BLE001
                    pass
            self.failed.emit(str(exc))
            return
        try:
            repo.close()
        except Exception:  # noqa: BLE001
            pass
        if self._cache_dir is not None:
            try:
                ThumbCrypto.change_password(
                    self._cache_dir, self._old_password, self._new_password
                )
            except Exception as exc:  # noqa: BLE001
                # DB rekey already succeeded, so we cannot roll back.  Surface
                # the thumb-key error; the controller will clear the cache.
                self.failed.emit(f"thumb-key rewrap: {exc}")
                return
        self.finished.emit()
