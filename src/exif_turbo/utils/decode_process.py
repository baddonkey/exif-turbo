from __future__ import annotations

import importlib
import multiprocessing
from typing import Any

from PIL import Image


class DecodeTimeoutError(TimeoutError):
    def __init__(self, message: str, process: multiprocessing.Process) -> None:
        super().__init__(message)
        self.process_id = process.pid or -1
        self._process = process

    @property
    def process_is_alive(self) -> bool:
        return self._process.is_alive()


def _run_child(
    connection: Any, module_name: str, function_name: str, args: tuple[Any, ...]
) -> None:
    try:
        function = getattr(importlib.import_module(module_name), function_name)
        result = function(*args)
        if isinstance(result, Image.Image):
            result.load()
            connection.send(("image", result.mode, result.size, result.tobytes()))
        else:
            connection.send(("value", result))
    except BaseException as exc:  # noqa: BLE001
        try:
            connection.send(("error", type(exc).__name__, str(exc)))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _stop_process(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
    if process.is_alive():
        process.kill()
        process.join(timeout=1.0)
    else:
        process.join()


def run_decode_process(
    module_name: str,
    function_name: str,
    args: tuple[Any, ...],
    *,
    timeout_s: float,
) -> Any:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_child,
        args=(child, module_name, function_name, args),
        daemon=True,
    )
    process.start()
    child.close()
    try:
        if not parent.poll(timeout_s):
            raise DecodeTimeoutError(
                f"Decode of {args[0] if args else function_name!r} timed out "
                f"after {timeout_s:g} s",
                process,
            )
        try:
            message = parent.recv()
        except EOFError as exc:
            raise RuntimeError("Decoder subprocess exited without a result") from exc
    finally:
        parent.close()
        _stop_process(process)

    if message[0] == "error":
        exception_types = {
            "FileNotFoundError": FileNotFoundError,
            "OSError": OSError,
            "PermissionError": PermissionError,
            "TimeoutError": TimeoutError,
            "ValueError": ValueError,
        }
        exception_type = exception_types.get(message[1], RuntimeError)
        raise exception_type(message[2])
    if message[0] == "image":
        _, mode, size, pixels = message
        return Image.frombytes(mode, size, pixels)
    return message[1]
