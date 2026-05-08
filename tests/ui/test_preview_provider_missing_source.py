"""Regression test for cached previews on disconnected drives.

Bug: when the source file lives on a drive that is currently unmounted,
``PreviewImageProvider`` failed to locate the cached preview because the
cache filename was hashed from a live ``os.stat`` — which raised, fell
back to a path-only key, and produced a different hash than the one used
when the cache was written (which uses DB-stored mtime/size).  The big
preview pane then showed only the blurry thumbnail.

The fix encodes the DB stamp in the provider URI as ``?m=<mtime>&s=<size>``
so the lookup never touches the source file.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize

from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.utils.preview_cache import preview_cache_name_from_stamp, preview_dir


def test_provider_serves_cached_preview_when_source_file_missing(
    tmp_path: Path,
) -> None:
    # Arrange — seed the cache as if the builder had run while the drive
    # was still mounted, then "disconnect" the drive (path never existed).
    cache_dir = tmp_path / "thumbs"
    preview_dir(cache_dir).mkdir(parents=True, exist_ok=True)
    missing_path = "/Volumes/Detached/photos/sample.jpg"
    mtime, size = 1700000000.0, 12345
    cache_name = preview_cache_name_from_stamp(missing_path, mtime, size)
    cache_path = preview_dir(cache_dir) / cache_name
    Image.new("RGB", (64, 48), color=(10, 200, 30)).save(cache_path, "JPEG")
    assert not Path(missing_path).exists()

    provider = PreviewImageProvider()
    provider.set_cache(cache_dir, key="")  # plain (unencrypted) cache

    # Act — ask for the preview using the stamped URI the controller builds.
    encoded = urllib.parse.quote(missing_path, safe="")
    url_id = f"{encoded}?m={mtime}&s={size}"
    out_size = QSize()
    img = provider.requestImage(url_id, out_size, QSize())

    # Assert — got the cached pixels, not an empty fallback.
    assert not img.isNull(), "Provider returned a null QImage for cached preview"
    assert img.width() == 64
    assert img.height() == 48
