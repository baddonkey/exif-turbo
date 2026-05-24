from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

# Guard: refuse to run outside the project venv to prevent hard-to-diagnose
# failures (e.g. missing optional deps like PyAV).
_venv = Path(__file__).resolve().parents[1] / ".venv"
if not Path(sys.executable).resolve().is_relative_to(_venv):
    pytest.exit(
        f"Tests must be run inside the project venv.\n"
        f"  Expected: {_venv / 'Scripts' / 'python.exe'} (Windows) "
        f"or {_venv / 'bin' / 'python'} (Unix)\n"
        f"  Got:      {sys.executable}\n"
        f"Activate the venv first:  .venv\\Scripts\\Activate.ps1",
        returncode=1,
    )

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
