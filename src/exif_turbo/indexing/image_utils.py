from __future__ import annotations

from pathlib import Path

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
