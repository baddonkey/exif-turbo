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
                "custom free-text tags to that image. Use list_image_sets and "
                "get_image_set_images to inspect indexed sets, then "
                "set_custom_tags_batch to add or replace tags on indexed images."
            ),
        )

        @server.tool(
            name="get_selected_image",
            description=(
                "Return the image currently selected in exif-turbo, including "
                "path, filename, free tags, EXIF/metadata JSON, and a JPEG "
                "preview when available. Uses the tagging drawer's selection: "
                "the selected set member in Sets, otherwise the Search/Browse "
                "selection. No selection is returned when a set is active "
                "without a selected member."
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
                "selected in the exif-turbo tagging drawer, not every image "
                "in a set. Use get_selected_image to verify the target path "
                "first. For a batch, use set_custom_tags_batch with explicit "
                "image IDs and paths. Tags are stored in the sidecar and "
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

        @server.tool(
            name="list_image_sets",
            description=(
                "List named image sets in the currently open database, with "
                "member counts and saved-filter availability."
            ),
        )
        def list_image_sets() -> CallToolResult:
            try:
                result = self._session.list_image_sets()
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
                structured_content={"sets": result},
            )

        @server.tool(
            name="get_image_set_images",
            description=(
                "Return one bounded page of images from a set, including paths, "
                "metadata, custom tags, and per-image preview resource URIs. "
                "Previews can optionally be included inline. The default limit "
                "is 5 with inline previews, otherwise 25. Maximum limits are "
                "5 with inline previews and 50 otherwise. Use next_offset "
                "to fetch subsequent pages."
            ),
        )
        def get_image_set_images(
            set_id: int,
            offset: int = 0,
            limit: int | None = None,
            include_previews: bool = False,
        ) -> CallToolResult:
            try:
                result = self._session.get_image_set_images(
                    set_id,
                    offset=offset,
                    limit=limit,
                    include_previews=include_previews,
                )
            except Exception as exc:  # noqa: BLE001 — surface to MCP clients
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))],
                    is_error=True,
                )
            content: list[ContentBlock] = [
                TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2),
                )
            ]
            for image in result["images"]:
                preview = image.get("preview_jpeg_base64")
                if preview:
                    content.append(
                        ImageContent(
                            type="image",
                            data=preview,
                            mime_type="image/jpeg",
                        )
                    )
            return CallToolResult(content=content, structured_content=result)

        @server.tool(
            name="set_custom_tags_batch",
            description=(
                "Apply append or replace custom-tag updates to indexed images. "
                "Each update contains image_id, path, tags, and optional mode "
                "(append by default). Results are reported per image."
            ),
        )
        def set_custom_tags_batch(
            updates: list[dict[str, Any]],
        ) -> CallToolResult:
            try:
                result = self._session.set_custom_tags_batch(updates)
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
            "exif-turbo://images/{image_id}/preview",
            name="indexed-image-preview",
            title="Indexed image preview",
            description="JPEG preview for an indexed image ID in the active database.",
            mime_type="image/jpeg",
        )
        def indexed_image_preview(image_id: int) -> bytes:
            return self._session.get_image_preview(image_id)

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
        _ = (
            get_selected_image,
            add_custom_tags,
            list_image_sets,
            get_image_set_images,
            set_custom_tags_batch,
            indexed_image_preview,
            selected_image_preview,
            selected_image_metadata,
        )
        return server
