from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from typing import Any

from mcp.server import MCPServer
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent

from .mcp_session_service import McpSessionError, McpSessionService


class McpServerFactory:
    """Build the in-process MCP server for the current selection."""

    def __init__(self, session_service: McpSessionService) -> None:
        self._session = session_service

    def create(self) -> MCPServer[Any]:
        server = MCPServer(
            name="exif-turbo",
            title="Exif Turbo",
            instructions=(
                "Local MCP interface for the running exif-turbo desktop app. "
                "Use get_selected_image to inspect the current UI selection "
                "(including a JPEG preview). Use add_custom_tags to attach "
                "custom free-text tags to that image."
            ),
        )

        @server.tool(
            name="get_selected_image",
            description=(
                "Return the image currently selected in exif-turbo, including "
                "path, filename, free tags, EXIF/metadata JSON, and a JPEG "
                "preview when available."
            ),
        )
        def get_selected_image(include_preview: bool = True) -> CallToolResult:
            try:
                payload = self._session.get_selected_image(
                    include_preview=include_preview
                )
            except McpSessionError as exc:
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))],
                    is_error=True,
                )
            content: list[ContentBlock] = [
                TextContent(
                    type="text",
                    text=json.dumps(payload.to_dict(), ensure_ascii=False, indent=2),
                )
            ]
            if payload.preview_jpeg_base64:
                content.append(
                    ImageContent(
                        type="image",
                        data=payload.preview_jpeg_base64,
                        mime_type="image/jpeg",
                    )
                )
            return CallToolResult(
                content=content,
                structured_content=payload.to_dict(),
            )

        @server.tool(
            name="add_custom_tags",
            description=(
                "Add one or more custom free-text tags to the image currently "
                "selected in exif-turbo. Tags are stored in the sidecar and "
                "index; originals are never modified."
            ),
        )
        def add_custom_tags(tags: list[str]) -> CallToolResult:
            try:
                result = self._session.add_custom_tags(tags)
            except McpSessionError as exc:
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))],
                    is_error=True,
                )
            except Exception as exc:  # noqa: BLE001 — surface to MCP clients
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))],
                    is_error=True,
                )
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False, indent=2),
                    )
                ],
                structured_content=result,
            )

        @server.resource(
            "exif-turbo://selected-image/preview",
            name="selected-image-preview",
            title="Selected image preview",
            description="JPEG preview of the image currently selected in exif-turbo.",
            mime_type="image/jpeg",
        )
        def selected_image_preview() -> bytes:
            payload = self._session.get_selected_image(include_preview=True)
            if not payload.preview_jpeg_base64:
                raise McpSessionError("No preview is available for the selected image.")
            return base64.b64decode(payload.preview_jpeg_base64)

        @server.resource(
            "exif-turbo://selected-image",
            name="selected-image",
            title="Selected image metadata",
            description="JSON metadata for the image currently selected in exif-turbo.",
            mime_type="application/json",
        )
        def selected_image_metadata() -> str:
            payload = self._session.get_selected_image(include_preview=False)
            return json.dumps(payload.to_dict(), ensure_ascii=False, indent=2)

        # Keep references so closures are not mistaken for unused locals.
        _ = (get_selected_image, add_custom_tags, selected_image_preview, selected_image_metadata)
        return server
