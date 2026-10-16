from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from PySide6.QtCore import QObject, QThread, Qt, Slot

T = TypeVar("T")


class MainThreadDispatcher(QObject):
    """Run callables on the Qt thread that owns this object."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._gate = threading.Lock()
        self._fn: Callable[[], object] | None = None
        self._result: object | None = None
        self._error: BaseException | None = None

    def call(self, fn: Callable[[], T]) -> T:
        if QThread.currentThread() is self.thread():
            return fn()
        with self._gate:
            self._fn = fn
            self._result = None
            self._error = None
            invoked = QMetaObject_invoke(self)
            if not invoked:
                raise RuntimeError("Failed to dispatch work to the UI thread.")
            if self._error is not None:
                raise self._error
            return self._result  # type: ignore[return-value]

    @Slot()
    def _execute(self) -> None:
        assert self._fn is not None
        try:
            self._result = self._fn()
        except BaseException as exc:  # noqa: BLE001 — re-raise on caller thread
            self._error = exc


def QMetaObject_invoke(dispatcher: MainThreadDispatcher) -> bool:
    from PySide6.QtCore import QMetaObject

    return bool(
        QMetaObject.invokeMethod(
            dispatcher,
            "_execute",
            Qt.ConnectionType.BlockingQueuedConnection,
        )
    )
