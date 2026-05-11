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
    """QML image provider for thumbnail files (encrypted or plain).

    Serves ``image://thumb/<sha1_hex>`` URIs.  An optional ``?t=<n>`` cache-
    bust query is stripped from the id, so callers can force QML's pixmap
    cache to refetch a regenerated thumbnail without changing the underlying
    filename.

    For each request:

    1. If a key is configured, reads ``<cache>/<sha1>.enc`` and decrypts with
       AES-256-GCM via :class:`ThumbCrypto`.
    2. Otherwise reads ``<cache>/<sha1>.png`` directly from disk.
    3. Decodes PNG bytes → QImage via Qt's built-in PNG decoder.

    Routing all thumbs (encrypted or not) through this provider guarantees
    that ``recreateThumbnail`` busts QML's pixmap cache: the same filename
    always loads fresh pixels because the provider re-reads the file each
    request.

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
        if cache_dir is None:
            return QImage()
        # Strip optional ?t=<n> cache-bust query.
        sha1 = id.split("?", 1)[0]
        if crypto is not None:
            enc_path = cache_dir / f"{sha1}.enc"
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
        # Unencrypted mode — read .png directly.
        png_path = cache_dir / f"{sha1}.png"
        try:
            qimg = QImage()
            if qimg.load(str(png_path), "PNG"):
                size.setWidth(qimg.width())
                size.setHeight(qimg.height())
                return qimg
        except Exception:
            _log.debug("Failed to load plain thumb %s", png_path, exc_info=True)
        return QImage()
