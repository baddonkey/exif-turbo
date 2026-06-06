from __future__ import annotations

import os
import sys
from pathlib import Path

# OpenMP conflict guard — see src/exif_turbo/app.py.  torch and faiss each bundle
# their own libomp.dylib; under pytest they are imported during collection,
# before the app entry point runs, so the guard must also be set here (before any
# import that transitively pulls in torch or faiss) to avoid a macOS SIGABRT.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import pytest
from PIL import Image

# Guard: refuse to run outside the project venv to prevent hard-to-diagnose
# failures (e.g. missing optional deps like PyAV).  Compare via ``sys.prefix``
# rather than ``Path(sys.executable).resolve()`` — on macOS the venv ``python``
# symlink chain ends in ``/Library/Frameworks/...`` so resolving the executable
# escapes the venv root, while ``sys.prefix`` always points at the venv itself.
_venv = Path(__file__).resolve().parents[1] / ".venv"
if Path(sys.prefix).resolve() != _venv.resolve():
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


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(
    session: pytest.Session, exitstatus: int
) -> None:
    """Bypass the Python interpreter teardown to avoid a Qt/WebEngine segfault.

    After all tests have finished, the interpreter destroys module-level
    globals in undefined order.  In a process that has loaded QtWebEngine,
    this teardown races with Chromium's worker shutdown and aborts with
    SIGSEGV/SIGABRT on macOS — long after the test results have already
    been reported.

    Calling ``os._exit`` here exits immediately with the recorded test
    result, skipping the broken teardown.  Safe because pytest has already
    written its summary and we have no remaining work to do.

    Only triggered when QtWebEngine has actually been loaded into the
    process — pure non-UI runs are not affected.
    """
    if "PySide6.QtWebEngineCore" not in sys.modules:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exitstatus)
