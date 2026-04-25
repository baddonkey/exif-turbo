from __future__ import annotations

from pathlib import Path

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".tif", ".tiff", ".png", ".bmp", ".gif", ".webp",
    # Canon RAW
    ".cr2", ".cr3",
    # Nikon RAW
    ".nef", ".nrw",
    # Sony RAW
    ".arw", ".srf", ".sr2",
    # Adobe DNG
    ".dng",
    # Other RAW
    ".orf", ".rw2", ".pef", ".raf", ".rwl", ".srw",
}


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS
