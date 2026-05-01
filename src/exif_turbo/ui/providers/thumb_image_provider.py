from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from ...utils.thumb_crypto import ThumbCrypto

_log = logging.getLogger(__name__)


class ThumbnailImageProvider(QQuickImageProvider):
    """QML image provider for encrypted thumbnail files.

    Serves ``image://thumb/<sha1_hex>`` URIs.  For each request:

    1. Reads ``cache_dir/<sha1_hex>.enc``
    2. Decrypts with AES-256-GCM via :class:`ThumbCrypto`
    3. Decodes PNG bytes → QImage via Qt's built-in PNG decoder

    Thread-safe: ``set_key`` is called once on unlock from the main thread;
    subsequent ``requestImage`` calls arrive on Qt's async image-provider
    pool threads.

    The provider ID is ``"thumb"``.
    """

    def __init__(self) -> None:
        super().__init__(
            QQuickImageProvider.ImageType.Image,
            QQuickImageProvider.Flag.ForceAsynchronousImageLoading,
        )
        self._lock = threading.Lock()
        self._crypto: ThumbCrypto | None = None
        self._cache_dir: Path | None = None

    def set_key(self, key: str, cache_dir: Path) -> None:
        """Configure encryption key and cache directory.  Call on unlock."""
        crypto = ThumbCrypto(key, cache_dir) if key else None
        with self._lock:
            self._crypto = crypto
            self._cache_dir = cache_dir

    def requestImage(  # type: ignore[override]
        self, id: str, size: QSize, requestedSize: QSize
    ) -> QImage:
        with self._lock:
            crypto = self._crypto
            cache_dir = self._cache_dir
        if crypto is None or cache_dir is None:
            return QImage()
        enc_path = cache_dir / f"{id}.enc"
        try:
            raw = enc_path.read_bytes()
            png_bytes = crypto.decrypt(raw)
            qimg = QImage()
            if qimg.loadFromData(png_bytes, "PNG"):
                size.setWidth(qimg.width())
                size.setHeight(qimg.height())
                return qimg
        except Exception:
            _log.debug("Failed to load encrypted thumb %s", enc_path, exc_info=True)
        return QImage()
