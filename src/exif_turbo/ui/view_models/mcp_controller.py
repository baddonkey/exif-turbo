from __future__ import annotations

import io
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image
from PySide6.QtCore import Property, QObject, Signal

from ...i18n import _
from ...mcp.mcp_server_factory import McpServerFactory
from ...mcp.mcp_server_runtime import McpServerRuntime
from ...mcp.mcp_session_service import McpSessionError, McpSessionService
from ...mcp.selected_image_snapshot import SelectedImageSnapshot
from .main_thread_dispatcher import MainThreadDispatcher

if TYPE_CHECKING:
    from ...tagging.tagging_service import TaggingService
    from ..models.settings_model import SettingsModel

_log = logging.getLogger(__name__)


class McpController(QObject):
    """Owns MCP server lifecycle and exposes status to QML settings."""

    mcpStatusChanged = Signal()

    def __init__(
        self,
        *,
        settings: SettingsModel | None,
        is_locked: Callable[[], bool],
        selected_path: Callable[[], str | None],
        selected_image_id: Callable[[], int | None],
        selected_metadata_json: Callable[[], str | None],
        selected_has_preview: Callable[[], bool],
        selected_free_tags: Callable[[], tuple[str, ...]],
        load_preview_image: Callable[[], Image.Image | None],
        get_tagging_service: Callable[[], TaggingService | None],
        tagging_available: Callable[[], bool],
        refresh_after_mutation: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._is_locked = is_locked
        self._selected_path = selected_path
        self._selected_image_id = selected_image_id
        self._selected_metadata_json = selected_metadata_json
        self._selected_has_preview = selected_has_preview
        self._selected_free_tags = selected_free_tags
        self._load_preview_image = load_preview_image
        self._get_tagging_service = get_tagging_service
        self._tagging_available = tagging_available
        self._refresh_after_mutation = refresh_after_mutation
        self._dispatcher = MainThreadDispatcher(self)
        self._runtime = McpServerRuntime()
        self._status_message = ""
        if self._settings is not None:
            self._settings.mcpSettingsChanged.connect(self.sync_from_settings)

    @property
    def is_running(self) -> bool:
        return self._runtime.is_running and not self._runtime.error

    @property
    def url(self) -> str:
        endpoint = self._runtime.endpoint
        if endpoint is None:
            if self._settings is None:
                return ""
            return f"http://{self._settings.mcp_host}:{self._settings.mcp_port}/mcp"
        return endpoint.url

    @property
    def status_message(self) -> str:
        return self._status_message

    @Property(bool, notify=mcpStatusChanged)
    def mcpRunning(self) -> bool:
        return self.is_running

    @Property(str, notify=mcpStatusChanged)
    def mcpUrl(self) -> str:
        return self.url

    @Property(str, notify=mcpStatusChanged)
    def mcpStatusMessage(self) -> str:
        return self.status_message

    def sync_from_settings(self) -> None:
        """Start or stop the MCP server to match settings + lock state."""
        if self._settings is None or not self._settings.mcp_enabled:
            self._stop_with_message("")
            return
        if self._is_locked():
            self._stop_with_message(_("Unlock the database to start the MCP server."))
            return
        host = self._settings.mcp_host
        port = self._settings.mcp_port
        try:
            session = McpSessionService(self)
            factory = McpServerFactory(session)
            server = factory.create()
            self._runtime.start(server, host=host, port=port)
        except Exception as exc:  # noqa: BLE001
            _log.exception("Failed to start MCP server")
            self._status_message = _("MCP server failed to start: {error}").format(
                error=exc
            )
            self.mcpStatusChanged.emit()
            return
        if self._runtime.error:
            self._status_message = _("MCP server failed to start: {error}").format(
                error=self._runtime.error
            )
            self.mcpStatusChanged.emit()
            return
        self._status_message = _("MCP server listening on {url}").format(
            url=self.url
        )
        self.mcpStatusChanged.emit()

    def stop(self) -> None:
        self._runtime.stop()
        self._status_message = ""
        self.mcpStatusChanged.emit()

    def close(self) -> None:
        if self._settings is not None:
            try:
                self._settings.mcpSettingsChanged.disconnect(self.sync_from_settings)
            except (RuntimeError, TypeError):
                pass
        self.stop()

    # ── SelectedImagePort (invoked from MCP worker thread) ────────────────

    def get_selected_image(self) -> SelectedImageSnapshot | None:
        return self._dispatcher.call(self._get_selected_image_main)

    def load_preview_jpeg(self) -> bytes | None:
        return self._dispatcher.call(self._load_preview_jpeg_main)

    def add_custom_tags(self, tags: Sequence[str]) -> tuple[str, ...]:
        labels = list(tags)
        return self._dispatcher.call(lambda: self._add_custom_tags_main(labels))

    def _get_selected_image_main(self) -> SelectedImageSnapshot | None:
        path = self._selected_path()
        if not path:
            return None
        return SelectedImageSnapshot(
            path=path,
            filename=Path(path).name,
            image_id=self._selected_image_id(),
            free_tags=self._selected_free_tags(),
            has_preview=self._selected_has_preview(),
            metadata_json=self._selected_metadata_json(),
        )

    def _load_preview_jpeg_main(self) -> bytes | None:
        image = self._load_preview_image()
        if image is None:
            return None
        buf = io.BytesIO()
        rgb = image.convert("RGB")
        rgb.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    def _add_custom_tags_main(self, tags: list[str]) -> tuple[str, ...]:
        if not self._tagging_available():
            raise McpSessionError(
                "Custom tagging is disabled. Enable it in Settings before adding tags."
            )
        path = self._selected_path()
        if not path:
            raise McpSessionError("No image is currently selected in exif-turbo.")
        service = self._get_tagging_service()
        if service is None:
            raise McpSessionError("Tagging service is not available.")
        for label in tags:
            service.add_free_tag(path, label)
        self._refresh_after_mutation()
        state = service.get_image_tagging_state(path)
        return state.free_tags

    def _stop_with_message(self, message: str) -> None:
        self._runtime.stop()
        self._status_message = message
        self.mcpStatusChanged.emit()
