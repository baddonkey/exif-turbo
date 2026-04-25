from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from exif_turbo.data.image_index_repository import ImageIndexRepository


@pytest.fixture
def repo(tmp_path: Path) -> ImageIndexRepository:
    db = ImageIndexRepository(tmp_path / "test.db", key="")
    yield db
    db.close()


def make_jpeg(path: Path, width: int = 8, height: int = 8) -> Path:
    """Write a minimal valid JPEG file and return its Path."""
    img = Image.new("RGB", (width, height), color=(100, 149, 237))
    img.save(str(path), format="JPEG")
    return path


def make_png(path: Path, width: int = 8, height: int = 8) -> Path:
    """Write a minimal valid PNG file and return its Path."""
    img = Image.new("RGB", (width, height), color=(34, 139, 34))
    img.save(str(path), format="PNG")
    return path
