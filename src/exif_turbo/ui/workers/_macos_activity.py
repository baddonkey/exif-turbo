"""macOS App Nap suppression for long-running background workers."""

from __future__ import annotations

import sys


class AppNapAssertion:
    """Holds an NSProcessInfo activity assertion to suppress macOS App Nap.

    Instantiating this class immediately begins the assertion.  Call
    :meth:`release` when the activity ends, or use the instance as a
    context manager with ``with``.

    On non-macOS platforms every operation is a silent no-op.
    """

    # NSActivityUserInitiated = 0x00FFFFFF
    # Tells macOS the work was explicitly started by the user and must not
    # be throttled by App Nap even when the display sleeps or screen locks.
    _ACTIVITY_FLAGS: int = 0x00FFFFFF

    def __init__(self, reason: str) -> None:
        self._state: object = self._begin(reason)

    # ── context manager protocol ──────────────────────────────────────────

    def __enter__(self) -> "AppNapAssertion":
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

    # ── explicit API ─────────────────────────────────────────────────────

    def release(self) -> None:
        """End the activity assertion."""
        self._end(self._state)
        self._state = None

    # ── private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _begin(reason: str) -> object:
        if sys.platform != "darwin":
            return None
        try:
            import ctypes

            lib = ctypes.CDLL("libobjc.A.dylib", use_errno=True)
            _id = ctypes.c_void_p

            get_class = ctypes.CFUNCTYPE(_id, ctypes.c_char_p)(("objc_getClass", lib))
            reg_sel   = ctypes.CFUNCTYPE(_id, ctypes.c_char_p)(("sel_registerName", lib))
            msg0      = ctypes.CFUNCTYPE(_id, _id, _id)(("objc_msgSend", lib))
            msg_str   = ctypes.CFUNCTYPE(_id, _id, _id, ctypes.c_char_p)(
                ("objc_msgSend", lib)
            )
            msg_begin = ctypes.CFUNCTYPE(_id, _id, _id, ctypes.c_uint64, _id)(
                ("objc_msgSend", lib)
            )

            process_info = msg0(
                get_class(b"NSProcessInfo"),
                reg_sel(b"processInfo"),
            )
            ns_reason = msg_str(
                get_class(b"NSString"),
                reg_sel(b"stringWithUTF8String:"),
                reason.encode("utf-8"),
            )
            token = msg_begin(
                process_info,
                reg_sel(b"beginActivityWithOptions:reason:"),
                AppNapAssertion._ACTIVITY_FLAGS,
                ns_reason,
            )
            return (process_info, token, lib)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _end(state: object) -> None:
        if state is None:
            return
        try:
            import ctypes

            process_info, token, lib = state  # type: ignore[misc]
            _id = ctypes.c_void_p
            reg_sel = ctypes.CFUNCTYPE(_id, ctypes.c_char_p)(("sel_registerName", lib))
            msg_end = ctypes.CFUNCTYPE(None, _id, _id, _id)(("objc_msgSend", lib))
            msg_end(process_info, reg_sel(b"endActivity:"), token)
        except Exception:  # noqa: BLE001
            pass
