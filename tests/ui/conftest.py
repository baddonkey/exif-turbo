from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWebEngineQuick import QtWebEngineQuick

# Disable the NSProcessInfo App-Nap activity assertion that IndexWorker /
# ThumbWorker take when they start.  The assertion is a power-management
# hint with no functional impact, but invoking the Objective-C runtime via
# ctypes from many concurrent QThreads has been observed to abort the
# process on Apple Silicon during heavy test runs.
os.environ.setdefault("EXIF_TURBO_DISABLE_APPNAP_ASSERTION", "1")


def pytest_configure(config: pytest.Config) -> None:
    """Called before QApplication is created — required for WebEngine init."""
    QQuickStyle.setStyle("Material")
    QtWebEngineQuick.initialize()


@pytest.fixture(autouse=True)
def _drain_qthreads_after_test() -> None:
    """Stop any running QThread leaked by a UI test before the next one starts.

    Many UI tests build an ``AppController`` directly without calling
    ``close()`` on teardown, leaking ``IndexWorker`` / ``ThumbWorker``
    background threads.  When the next test enters ``pytest_runtest_setup``
    a leaked worker may still be inside ``ImageIndexRepository.__init__``
    opening a SQLCipher connection, racing with the new test's own DB I/O
    on shared OpenSSL state — which crashes the process with SIGABRT.

    After each test, walk every child of the live QApplication, request
    interruption on any running ``QThread``, then wait for it to finish.
    """
    yield
    app = QCoreApplication.instance()
    if app is None:
        return
    import gc
    threads: list[QThread] = []
    for obj in gc.get_objects():
        if isinstance(obj, QThread):
            try:
                if obj.isRunning():
                    threads.append(obj)
            except RuntimeError:
                # Underlying C++ object already deleted.
                continue
    for thread in threads:
        cancel = getattr(thread, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass
        try:
            thread.requestInterruption()
            thread.quit()
        except RuntimeError:
            pass
    for thread in threads:
        try:
            thread.wait(5000)
        except RuntimeError:
            pass
