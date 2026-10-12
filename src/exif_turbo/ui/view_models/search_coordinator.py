from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PendingSearch:
    """Latest normal-search request waiting for the active worker to finish."""

    params: dict[str, Any]
    show_busy_ui: bool


@dataclass(frozen=True)
class SearchRequest:
    """A search request tagged with the serial used to reject stale results."""

    params: dict[str, Any]
    show_busy_ui: bool
    serial: int


class SearchCoordinator:
    """Coordinate search serials and coalesce requests while a worker is active.

    The controller remains responsible for Qt worker ownership, result
    hydration, GUI signals, and thread shutdown. This object owns only the
    request-state rules shared by normal and AI search paths.
    """

    def __init__(self) -> None:
        self._serial = 0
        self._pending: PendingSearch | None = None

    @property
    def serial(self) -> int:
        return self._serial

    def request(
        self, params: dict[str, Any], *, show_busy_ui: bool, worker_active: bool
    ) -> SearchRequest | None:
        """Start a request or retain only the latest request behind a worker."""
        self._serial += 1
        if worker_active:
            self._pending = PendingSearch(dict(params), show_busy_ui)
            return None
        return SearchRequest(dict(params), show_busy_ui, self._serial)

    def begin_secondary_search(self) -> int:
        """Invalidate older results when an AI/page search starts."""
        self._serial += 1
        return self._serial

    def take_pending(self) -> SearchRequest | None:
        """Consume the coalesced request using the newest serial."""
        pending = self._pending
        self._pending = None
        if pending is None:
            return None
        return SearchRequest(pending.params, pending.show_busy_ui, self._serial)

    def is_current(self, serial: int) -> bool:
        return serial == self._serial

    def clear(self) -> None:
        self._pending = None