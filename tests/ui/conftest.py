from __future__ import annotations

import gc
import os
import sys
import threading
from collections.abc import Iterator

import pytest
from PySide6.QtCore import (
    QCoreApplication, QEvent, QMessageLogContext, QThread, QTimer, Qt, QtMsgType,
    qInstallMessageHandler,
)
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from pytestqt.qtbot import QtBot
from shiboken6 import delete as delete_qobject, isValid

from exif_turbo.ui.view_models.app_controller import AppController

# Disable the NSProcessInfo App-Nap activity assertion that IndexWorker /
# ThumbWorker take when they start.  The assertion is a power-management
# hint with no functional impact, but invoking the Objective-C runtime via
# ctypes from many concurrent QThreads has been observed to abort the
# process on Apple Silicon during heavy test runs.
os.environ.setdefault("EXIF_TURBO_DISABLE_APPNAP_ASSERTION", "1")


def pytest_configure(config: pytest.Config) -> None:
    """Called before QApplication is created — required for WebEngine init."""
    if sys.platform == "win32":
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
    QQuickStyle.setStyle("Material")
    QtWebEngineQuick.initialize()


@pytest.fixture
def qml_engine(
    qtbot: QtBot, request: pytest.FixtureRequest,
) -> Iterator[QQmlApplicationEngine]:
    engine = QQmlApplicationEngine()
    collector = QTimer(engine)

    def collect_garbage() -> None:
        engine.collectGarbage()
        gc.collect()

    collector.timeout.connect(collect_garbage)
    if getattr(request, "param", False):
        collector.start(50)
    try:
        yield engine
    finally:
        collector.stop()
        collector.timeout.disconnect(collect_garbage)
    context = engine.rootContext()
    context_objects = [
        context.contextProperty(name)
        for name in (
            "controller", "searchModel", "filteredSearchModel", "exifModel",
            "folderListModel", "settingsModel",
        )
    ]
    controller = context_objects[0]
    if isinstance(controller, AppController):
        controller.close()
    for root in engine.rootObjects():
        if isinstance(root, QQuickWindow):
            root.close()
    with qtbot.waitSignal(engine.destroyed, timeout=5_000):
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _report_fatal_qt_messages() -> Iterator[None]:
    def report(
        message_type: QtMsgType, context: QMessageLogContext, message: str,
    ) -> None:
        if message_type == QtMsgType.QtFatalMsg:
            os.write(2, f"QT-FATAL: {message}\n".encode("utf-8", errors="replace"))
        if previous_handler is not None:
            previous_handler(message_type, context, message)

    previous_handler = qInstallMessageHandler(report)
    try:
        yield
    finally:
        qInstallMessageHandler(previous_handler)


@pytest.fixture(autouse=True)
def _drain_qthreads_after_test() -> Iterator[None]:
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
        if issubclass(type(obj), QThread):
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


def _retire_controllers(controllers: list[AppController]) -> None:
    retired_on_owner_thread: list[bool] = []
    live_controllers = [controller for controller in controllers if isValid(controller)]
    owner_thread_id = threading.get_ident()
    for controller in reversed(live_controllers):
        controller.destroyed.connect(
            lambda destroyed_object: retired_on_owner_thread.append(
                threading.get_ident() == owner_thread_id
            ),
            Qt.ConnectionType.DirectConnection,
        )
        controller.close()
        if QCoreApplication.instance() is None:
            delete_qobject(controller)
        else:
            controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(retired_on_owner_thread) == len(live_controllers)
    assert all(retired_on_owner_thread)
    gc.collect()


@pytest.fixture(autouse=True)
def _allow_explicit_plaintext_test_databases(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Opt legacy UI fixtures into plaintext explicitly; production defaults closed."""
    original_init = AppController.__init__
    controllers: list[AppController] = []

    def _init_with_plaintext_opt_in(self: AppController, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("allow_plaintext_db", True)
        original_init(self, *args, **kwargs)  # type: ignore[arg-type]
        controllers.append(self)

    monkeypatch.setattr(AppController, "__init__", _init_with_plaintext_opt_in)
    yield
    _retire_controllers(controllers)
