"""Background worker that downloads and installs an optional GPU accelerator.

Runs :func:`exif_turbo.utils.ai_device.install_gpu_backend` off the UI thread —
the download can be several GB and must not block Qt's event loop.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from ...utils import ai_device


class GpuBackendInstallWorker(QThread):
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, backend: str) -> None:
        super().__init__()
        self._backend = backend
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        success, message = ai_device.install_gpu_backend(
            self._backend,
            on_progress=self.progress.emit,
            cancel_check=self._cancel_event.is_set,
        )
        self.finished.emit(success, message)
