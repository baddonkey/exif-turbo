from __future__ import annotations

import threading

import pytest
from pytestqt.qtbot import QtBot

from exif_turbo.ui.view_models.main_thread_dispatcher import MainThreadDispatcher


def test_main_thread_dispatcher_same_thread_call_returns_result(qtbot: QtBot) -> None:
    # Arrange
    dispatcher = MainThreadDispatcher()

    # Act
    result = dispatcher.call(lambda: "ok")

    # Assert
    assert result == "ok"


def test_main_thread_dispatcher_same_thread_call_reraises(qtbot: QtBot) -> None:
    # Arrange
    dispatcher = MainThreadDispatcher()

    def boom() -> None:
        raise ValueError("dispatch-fail")

    # Act / Assert
    with pytest.raises(ValueError, match="dispatch-fail"):
        dispatcher.call(boom)


def test_main_thread_dispatcher_cross_thread_call_runs_on_owner_thread(
    qtbot: QtBot,
) -> None:
    # Arrange
    dispatcher = MainThreadDispatcher()
    main_ident = threading.get_ident()
    observed: list[int] = []
    result_box: list[str] = []
    error_box: list[BaseException] = []

    def work() -> str:
        observed.append(threading.get_ident())
        return "ok"

    def worker() -> None:
        try:
            result_box.append(dispatcher.call(work))
        except BaseException as exc:  # noqa: BLE001
            error_box.append(exc)

    # Act — BlockingQueuedConnection needs the owner thread event loop.
    thread = threading.Thread(target=worker)
    thread.start()
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=5000)

    # Assert
    assert error_box == []
    assert result_box == ["ok"]
    assert observed == [main_ident]
