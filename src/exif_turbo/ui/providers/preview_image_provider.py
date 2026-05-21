from __future__ import annotations

import logging
import urllib.parse
from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, QThread
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from ...utils.preview_cache import (
    preview_cache_name_from_stamp,
    preview_cache_path,
    preview_dir,
)
from ...utils.preview_render import MAX_PREVIEW_PX, render_preview
from ...utils.thumb_crypto import ThumbCrypto

_log = logging.getLogger(__name__)

# Default cap when QML doesn't pass an explicit requested size.
_DEFAULT_TARGET_PX = 2048


class PreviewImageProvider(QQuickImageProvider):
    """Async QML image provider for full-image previews.

    Fast path: if a rendered preview exists in the on-disk preview cache
    (built per-folder via the FoldersPanel "Build Previews" action), the
    cached JPEG is loaded and returned directly — typically <50 ms even
    for huge RAW originals.

    Slow path (cache miss): the source file is decoded live via the shared
    ``render_preview()`` helper; same code path the cache builder uses, so
    the on-screen result is identical.

    QML usage::

        Image { source: "image://preview/" + encodeURIComponent(filePath) }
    """

    def __init__(self) -> None:
        super().__init__(
            QQuickImageProvider.ImageType.Image,
            QQuickImageProvider.Flag.ForceAsynchronousImageLoading,
        )
        self._cache_dir: Path | None = None
        self._crypto: ThumbCrypto | None = None

    # ── Configuration (called from AppController on unlock) ──────────────

    def set_cache(self, cache_dir: Path, key: str) -> None:
        """Configure the on-disk preview cache directory and encryption key."""
        self._cache_dir = cache_dir
        if key:
            preview_dir(cache_dir).mkdir(parents=True, exist_ok=True)
            self._crypto = ThumbCrypto(key, cache_dir)
        else:
            self._crypto = None

    # ── QQuickImageProvider override ─────────────────────────────────────

    def requestImage(  # type: ignore[override]
        self, id: str, size: QSize, requestedSize: QSize
    ) -> QImage:
        QThread.currentThread().setPriority(QThread.Priority.HighPriority)
        path, stamp, pixel_count = _parse_id(id)
        target = _effective_target(requestedSize)
        try:
            img = self._load_cached_or_live(path, stamp, target, pixel_count)
        except Exception as exc:  # noqa: BLE001
            _log.error("Preview failed for %r: %s", path, exc)
            img = QImage()
        size.setWidth(img.width())
        size.setHeight(img.height())
        return img

    # ── Internal ─────────────────────────────────────────────────────────

    def _load_cached_or_live(
        self, path: str, stamp: tuple[float, int] | None, target: int,
        pixel_count: int | None = None,
    ) -> QImage:
        cached = self._try_load_cached(path, stamp)
        if cached is not None:
            return _pil_to_qimage(cached)
        pil_img = render_preview(path, target, known_pixel_count=pixel_count)
        return _pil_to_qimage(pil_img)

    def _try_load_cached(
        self, path: str, stamp: tuple[float, int] | None
    ) -> Image.Image | None:
        if self._cache_dir is None:
            return None
        cache_path = self._resolve_cache_path(path, stamp)
        try:
            if self._crypto is not None and self._crypto.is_active:
                enc_path = cache_path.with_suffix(".jpg.enc")
                if not enc_path.exists():
                    return None
                blob = enc_path.read_bytes()
                data = self._crypto.decrypt(blob)
                img = Image.open(BytesIO(data))
                img.load()
                return img
            if not cache_path.exists():
                return None
            img = Image.open(cache_path)
            img.load()
            return img
        except Exception as exc:  # noqa: BLE001
            _log.warning("Cached preview unreadable for %r: %s", path, exc)
            return None

    def _resolve_cache_path(
        self, path: str, stamp: tuple[float, int] | None
    ) -> Path:
        """Compute the on-disk cache path for *path*.

        When the caller provides DB-stored ``stamp`` (mtime, size), use it
        directly so the lookup works even when the source drive is
        disconnected.  Otherwise fall back to the legacy live-stat path.
        """
        assert self._cache_dir is not None
        if stamp is not None:
            name = preview_cache_name_from_stamp(path, stamp[0], stamp[1])
            return preview_dir(self._cache_dir) / name
        return preview_cache_path(path, self._cache_dir)


# ── helpers ──────────────────────────────────────────────────────────────


def _parse_id(raw_id: str) -> tuple[str, tuple[float, int] | None, int | None]:
    """Split a provider id into ``(path, stamp, pixel_count)``.

    The id format is ``<encoded-path>[?m=<mtime>&s=<size>[&px=<pixel_count>]]``.
    The optional ``px`` parameter carries the DB-stored pixel count (width *
    height from exiftool metadata) so the provider can route large images to
    pyvips without opening the source file.
    """
    qpos = raw_id.find("?")
    if qpos < 0:
        return urllib.parse.unquote(raw_id), None, None
    path = urllib.parse.unquote(raw_id[:qpos])
    params = urllib.parse.parse_qs(raw_id[qpos + 1 :])
    try:
        mtime = float(params["m"][0])
        size_b = int(params["s"][0])
    except (KeyError, IndexError, ValueError):
        return path, None, None
    try:
        px = int(params["px"][0])
    except (KeyError, IndexError, ValueError):
        px = None
    return path, (mtime, size_b), px


def _effective_target(requested: QSize) -> int:
    if requested.isValid() and not requested.isEmpty():
        return min(max(requested.width(), requested.height()), MAX_PREVIEW_PX)
    return _DEFAULT_TARGET_PX


def _pil_to_qimage(pil_img: Image.Image) -> QImage:
    pil_img = pil_img.convert("RGBA")
    data = bytes(pil_img.tobytes("raw", "RGBA"))
    return QImage(
        data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888
    ).copy()
