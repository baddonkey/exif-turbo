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
                "set_custom_tags_batch to add or replace tags on indexed images. "
                "Use set_image_description or set_image_descriptions_batch with "
                "explicit image IDs, paths, and append/replace modes for custom descriptions."
                " Use set_image_description_excluded to independently discard embedded "
                "descriptions from exported copies without providing replacement text."
                " Use set_image_embedded_tag_excluded for individual embedded keywords, "
                "or set_image_all_embedded_tags_excluded to ignore all embedded keywords "
                "on exported copies. Set excluded=false to restore inclusion."
            ),
        )

        @server.tool(
            name="get_selected_image",
            description=(
                "Return the image currently selected in exif-turbo, including "
                "path, filename, free tags, custom description, EXIF/metadata JSON, and a JPEG "
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
            except Exception as exc:  # noqa: BLE001 — surface selection/sidecar failures
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
                "metadata, custom tags, descriptions, and per-image preview resource URIs. "
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
            name="set_image_embedded_tag_excluded",
            description=(
                "Ignore or restore one embedded keyword on exported copies using a sidecar "
                "exclusion (case-insensitive). Does not remove custom tags or change original "
                "image bytes or source search metadata. Returns individual exclusions, "
                "ignore-all state, and changed flag. Restoring a keyword does not override "
                "ignore-all; clear that flag separately. image_id and path must match an "
                "indexed image in the active, unlocked database with tagging enabled."
            ),
        )
        def set_image_embedded_tag_excluded(
            image_id: int, path: str, tag: str, excluded: bool
        ) -> CallToolResult:
            try:
                result = self._session.set_image_embedded_tag_excluded(image_id, path, tag, excluded)
            except Exception as exc:  # noqa: BLE001 — surface to MCP clients
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))], is_error=True,
                )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structured_content=result,
            )

        @server.tool(
            name="set_image_all_embedded_tags_excluded",
            description=(
                "Ignore or restore all embedded keywords on exported copies using a sidecar "
                "flag. Preserves individual keyword exclusions, custom tags, descriptions, "
                "original image bytes, and source search metadata. Returns individual exclusions, "
                "ignore-all state, and changed flag. image_id and path must match an "
                "indexed image in the active, unlocked database with tagging enabled."
            ),
        )
        def set_image_all_embedded_tags_excluded(
            image_id: int, path: str, excluded: bool
        ) -> CallToolResult:
            try:
                result = self._session.set_image_all_embedded_tags_excluded(image_id, path, excluded)
            except Exception as exc:  # noqa: BLE001 — surface to MCP clients
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))], is_error=True,
                )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structured_content=result,
            )

        @server.tool(
            name="set_image_description_excluded",
            description=(
                "Set or clear the sidecar flag that removes embedded descriptions from "
                "exported copies. No replacement text is needed. Does not alter custom "
                "description text, source metadata/search, or original image bytes. "
                "image_id and path must match an indexed image in the active database."
            ),
        )
        def set_image_description_excluded(
            image_id: int, path: str, excluded: bool
        ) -> CallToolResult:
            try:
                result = self._session.set_image_description_excluded(image_id, path, excluded)
            except Exception as exc:  # noqa: BLE001 — surface to MCP clients
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))], is_error=True,
                )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structured_content=result,
            )

        @server.tool(
            name="set_image_description",
            description=(
                "Append or replace a custom description for an indexed image. "
                "image_id and path must match in the active database; mode is required "
                "('append' or 'replace'). Append adds a paragraph; empty replace clears "
                "the custom description. Stored in the sidecar and search index, never "
                "in the original image or its embedded metadata."
            ),
        )
        def set_image_description(
            image_id: int, path: str, description: str, mode: str
        ) -> CallToolResult:
            try:
                result = self._session.set_image_description(image_id, path, description, mode)
            except Exception as exc:  # noqa: BLE001 — surface to MCP clients
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))], is_error=True,
                )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structured_content=result,
            )

        @server.tool(
            name="set_image_descriptions_batch",
            description=(
                "Apply up to 100 custom description updates. Each update requires "
                "image_id, path, description, and explicit mode ('append' or 'replace'). "
                "Reports per-image success/error, resulting description and changed flag."
            ),
        )
        def set_image_descriptions_batch(updates: list[dict[str, Any]]) -> CallToolResult:
            try:
                result = self._session.set_image_descriptions_batch(updates)
            except Exception as exc:  # noqa: BLE001 — surface to MCP clients
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))], is_error=True,
                )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structured_content=result,
            )

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
            set_image_description,
            set_image_descriptions_batch,
            set_image_description_excluded,
            set_image_embedded_tag_excluded,
            set_image_all_embedded_tags_excluded,
            indexed_image_preview,
            selected_image_preview,
            selected_image_metadata,
        )
        return server
