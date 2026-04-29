from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

# RAW formats that require rawpy or exiftool for thumbnail extraction —
# Qt cannot decode them natively.
RAW_EXTENSIONS = {
    ".cr2", ".cr3",          # Canon
    ".nef", ".nrw",          # Nikon
    ".arw", ".srf", ".sr2",  # Sony
    ".dng",                   # Adobe DNG
    ".orf",                   # Olympus
    ".rw2",                   # Panasonic
    ".pef",                   # Pentax
    ".raf",                   # Fujifilm
    ".rwl",                   # Leica
    ".srw",                   # Samsung
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".tif", ".tiff", ".png", ".bmp", ".gif", ".webp",
    *RAW_EXTENSIONS,
}


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


# LibRaw flip field values → Pillow transpose operations.
# The flip field in rawpy's raw.sizes.flip encodes the orientation of the
# RAW sensor data / embedded JPEG relative to the correct display orientation.
# Canon CR2, Nikon NEF and others store rotation here rather than (or in
# addition to) the embedded JPEG's own EXIF Orientation tag.
#
#   0 → no rotation needed
#   3 → rotate 180°
#   5 → rotate 90° counter-clockwise
#   6 → rotate 90° clockwise  (most common: portrait photo from landscape camera)
_LIBRAW_FLIP_TO_TRANSPOSE: dict[int, int] = {
    3: 3,   # Image.Transpose.ROTATE_180
    5: 2,   # Image.Transpose.ROTATE_90  (90° CCW)
    6: 4,   # Image.Transpose.ROTATE_270 (90° CW)
}


def orient_raw_thumb(img: "Image.Image", raw_flip: int) -> "Image.Image":
    """Apply orientation to an extracted RAW thumbnail.

    Uses the RAW file's *flip* field (from ``rawpy.RawPy.sizes.flip``) as the
    authoritative orientation source.  Many cameras (Canon CR2, etc.) store
    rotation in the outer RAW IFD and leave the embedded JPEG's Orientation
    tag at 1, so ``ImageOps.exif_transpose()`` alone is insufficient.

    Falls back to ``ImageOps.exif_transpose()`` when flip == 0, in case the
    embedded JPEG carries a non-trivial Orientation tag of its own.
    """
    from PIL import Image, ImageOps

    op = _LIBRAW_FLIP_TO_TRANSPOSE.get(raw_flip)
    if op is not None:
        return img.transpose(op)
    # flip == 0: RAW says no rotation — still honour the JPEG's EXIF tag.
    return ImageOps.exif_transpose(img)
