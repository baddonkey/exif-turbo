from __future__ import annotations

import os
import sys

# ── OpenMP conflict guard (macOS) ─────────────────────────────────────────
# PyTorch and FAISS each bundle their own libomp.dylib.  On macOS, loading
# two OpenMP runtimes in the same process causes the OMP worker threads to
# corrupt each other's barrier state, resulting in a SIGSEGV.
# KMP_DUPLICATE_LIB_OK lets both runtimes coexist; OMP_NUM_THREADS=1 keeps
# them single-threaded so they never race on shared global OMP state.
# These must be set before either library is loaded (i.e. before any import
# that transitively pulls in torch or faiss).
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")


def _ensure_standard_streams() -> None:
    """Provide dummy stdio streams for windowed Windows builds."""
    if sys.stdin is None:
        sys.stdin = open(os.devnull, "r", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


_ensure_standard_streams()

from exif_turbo.ui.app_main import main
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.view_models.app_controller import AppController
from exif_turbo.ui.workers.index_worker import IndexWorker
from exif_turbo.ui.workers.thumb_worker import ThumbWorker

__all__ = [
    "main",
    "AppController",
    "ExifListModel",
    "SearchListModel",
    "IndexWorker",
    "ThumbWorker",
]


if __name__ == "__main__":
    main()
