from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .selected_image_port import SelectedImagePort
from .selected_image_snapshot import SelectedImageSnapshot


class McpSessionError(RuntimeError):
    """Raised when an MCP session operation cannot complete."""


@dataclass(frozen=True)
class SelectedImagePayload:
    """Structured payload returned to MCP clients for the current selection."""

    path: str
    filename: str
    image_id: int | None
    free_tags: tuple[str, ...]
    has_preview: bool
    metadata: dict[str, Any] | None
    preview_jpeg_base64: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "image_id": self.image_id,
            "free_tags": list(self.free_tags),
            "has_preview": self.has_preview,
            "metadata": self.metadata,
            "preview_jpeg_base64": self.preview_jpeg_base64,
        }


class McpSessionService:
    """Application service backing MCP tools for the current selection."""

    def __init__(self, port: SelectedImagePort) -> None:
        self._port = port

    def get_selected_image(self, *, include_preview: bool = True) -> SelectedImagePayload:
        snapshot = self._require_selection()
        preview_b64: str | None = None
        if include_preview:
            jpeg = self._port.load_preview_jpeg()
            if jpeg:
                preview_b64 = base64.b64encode(jpeg).decode("ascii")
        return SelectedImagePayload(
            path=snapshot.path,
            filename=snapshot.filename,
            image_id=snapshot.image_id,
            free_tags=snapshot.free_tags,
            has_preview=snapshot.has_preview,
            metadata=self._parse_metadata(snapshot.metadata_json),
            preview_jpeg_base64=preview_b64,
        )

    def add_custom_tags(self, tags: Sequence[str]) -> dict[str, Any]:
        cleaned = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        if not cleaned:
            raise McpSessionError("Provide at least one non-empty custom tag.")
        snapshot = self._require_selection()
        resulting = self._port.add_custom_tags(cleaned)
        return {
            "path": snapshot.path,
            "added": cleaned,
            "free_tags": list(resulting),
        }

    def _require_selection(self) -> SelectedImageSnapshot:
        snapshot = self._port.get_selected_image()
        if snapshot is None:
            raise McpSessionError("No image is currently selected in exif-turbo.")
        return snapshot

    @staticmethod
    def _parse_metadata(raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else {"value": parsed}
