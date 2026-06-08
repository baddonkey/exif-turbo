"""Wheel-scroll fix for QML ListView / Flickable items (all platforms).

Qt's ``QQuickFlickable`` does not guarantee exactly one row of scroll per
mouse-wheel notch.  On Linux/X11 it may take the ``pixelDelta`` branch and
scroll only a few pixels; on Windows and macOS the Flickable's own inertia
and deceleration can over- or under-shoot row boundaries.

This module provides :class:`ListScrollFix`, an ``eventFilter`` installed on
the ``QQuickWindow``.  It intercepts wheel events that land inside a named
``ListView``, computes the correct row-based scroll delta, sets ``contentY``
directly, and returns ``True`` so that the ``Flickable`` never sees the event.

Sub-notch events (e.g. Wayland/libinput high-resolution scroll, where one
physical notch arrives as several events each carrying a small ``angleDelta``)
are batched in an accumulator until they sum to ±120 before advancing the list.

For trackpad events where ``angleDelta`` is zero, the raw ``pixelDelta`` is
used as a fallback so smooth trackpad scrolling is preserved.

Usage::

    fix = ListScrollFix(window, "resultsList")
    window.installEventFilter(fix)
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtQuick import QQuickItem


class ListScrollFix(QObject):
    """Event filter that intercepts wheel events over a named QML ListView.

    Parameters
    ----------
    window:
        The ``QQuickWindow`` (or ``QQuickView``) that owns the ListView.
    list_object_name:
        The ``objectName`` of the target QML ``ListView`` item.
    """

    #: Height of one delegate row in pixels — must match the QML delegate.
    ROW_HEIGHT: int = 210
    #: ``angleDelta.y`` units that constitute one full mouse-wheel notch.
    NOTCH: int = 120

    def __init__(
        self,
        window: QObject,
        list_object_name: str,
        row_height: int | None = None,
        on_wheel_down_at_bottom: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._name = list_object_name
        self._row_height = row_height if row_height is not None else self.ROW_HEIGHT
        self._on_wheel_down_at_bottom = on_wheel_down_at_bottom
        self._accumulated: float = 0.0
        self._last_content_y: float | None = None

    # ------------------------------------------------------------------
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel:
            return False

        lst: QQuickItem | None = self._window.findChild(QQuickItem, self._name)
        if lst is None:
            return False

        # Skip lists that are not actually visible on screen (e.g. the
        # Search-tab resultsList while the user is on the Browse tab).
        # Otherwise an invisible list whose layout geometry happens to
        # overlap the cursor would silently consume the wheel event and
        # scroll its hidden contentY, with no visible effect.
        if not lst.isVisible():
            return False

        # Is the cursor inside this list?
        local = lst.mapFromScene(event.position())  # type: ignore[attr-defined]
        if not lst.boundingRect().contains(local):
            return False

        content_y = float(lst.property("contentY") or 0)
        # Programmatic jumps (positionViewAtIndex/contentY assignment) can
        # happen between wheel events during cross-tab navigation. If a stale
        # fractional accumulator from before the jump is kept, the first wheel
        # notch after returning may be swallowed. Reset on large discontinuity.
        if self._last_content_y is not None:
            if abs(content_y - self._last_content_y) > (self._row_height * 0.5):
                self._accumulated = 0.0
        self._last_content_y = content_y

        angle_y: int = event.angleDelta().y()  # type: ignore[attr-defined]
        pixel_y: int = event.pixelDelta().y()  # type: ignore[attr-defined]

        if angle_y != 0:
            self._accumulated += angle_y
            rows = int(self._accumulated / self.NOTCH)
            if rows == 0:
                # Accumulate sub-notch events; consume so Flickable stays quiet.
                return True
            self._accumulated -= rows * self.NOTCH
            delta = -rows * self._row_height
        elif pixel_y != 0:
            # Wayland/trackpad: angleDelta absent, use pixelDelta directly.
            delta = -pixel_y
        else:
            return True  # nothing to scroll; consume to keep Flickable quiet

        content_height = float(lst.property("contentHeight") or 0)
        list_height = float(lst.property("height") or 0)
        max_y = max(0.0, content_height - list_height)
        new_y = max(0.0, min(content_y + delta, max_y))
        lst.setProperty("contentY", new_y)

        # If a wheel-down occurs while already pinned at the bottom, contentY
        # does not change and QML onContentYChanged cannot trigger prefetch.
        # Invoke the optional callback to request more rows explicitly (Browse
        # list pagination path). Do this on every down-notch at bottom so a
        # first attempt that races with in-flight loading can recover on the
        # next notch without requiring an opposite-direction scroll.
        if delta > 0 and content_y >= max_y and new_y >= max_y:
            if self._on_wheel_down_at_bottom is not None:
                self._on_wheel_down_at_bottom()

        self._last_content_y = new_y
        return True  # consumed — Flickable will not process this event
