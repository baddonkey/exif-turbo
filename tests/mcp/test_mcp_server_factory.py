from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from exif_turbo.mcp.mcp_server_factory import McpServerFactory
from exif_turbo.mcp.mcp_session_service import McpSessionService
from exif_turbo.mcp.selected_image_snapshot import SelectedImageSnapshot


class _FakePort:
    def __init__(self, snapshot: SelectedImageSnapshot | None) -> None:
        self._snapshot = snapshot

    def get_selected_image(self) -> SelectedImageSnapshot | None:
        return self._snapshot

    def load_preview_jpeg(self) -> bytes | None:
        return b"\xff\xd8fakejpeg"

    def add_custom_tags(self, tags: Sequence[str]) -> tuple[str, ...]:
        return tuple(tags)


def _tool_fn(server: Any, name: str):
    for tool in server._tool_manager.list_tools():  # noqa: SLF001
        if tool.name == name:
            return tool.fn
    raise AssertionError(f"tool not found: {name}")


def test_mcp_server_factory_get_selected_image_tool_returns_payload() -> None:
    # Arrange
    snapshot = SelectedImageSnapshot(
        path="/tmp/x.jpg",
        filename="x.jpg",
        image_id=3,
        free_tags=("tag-a",),
        has_preview=True,
        metadata_json='{"A":1}',
    )
    factory = McpServerFactory(McpSessionService(_FakePort(snapshot)))
    server = factory.create()
    tool = _tool_fn(server, "get_selected_image")

    # Act
    result = tool(include_preview=True)

    # Assert
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["path"] == "/tmp/x.jpg"
    assert result.structured_content["free_tags"] == ["tag-a"]
    assert any(getattr(c, "type", None) == "image" for c in result.content)


def test_mcp_server_factory_get_selected_image_tool_reports_no_selection() -> None:
    # Arrange
    factory = McpServerFactory(McpSessionService(_FakePort(None)))
    server = factory.create()
    tool = _tool_fn(server, "get_selected_image")

    # Act
    result = tool()

    # Assert
    assert result.is_error is True
    assert "No image is currently selected" in result.content[0].text


def test_mcp_server_factory_add_custom_tags_tool_returns_tags() -> None:
    # Arrange
    snapshot = SelectedImageSnapshot(
        path="/tmp/x.jpg",
        filename="x.jpg",
        image_id=3,
        free_tags=(),
        has_preview=False,
        metadata_json=None,
    )
    factory = McpServerFactory(McpSessionService(_FakePort(snapshot)))
    server = factory.create()
    tool = _tool_fn(server, "add_custom_tags")

    # Act
    result = tool(tags=["one", "two"])

    # Assert
    assert result.is_error is False
    assert result.structured_content == {
        "path": "/tmp/x.jpg",
        "added": ["one", "two"],
        "free_tags": ["one", "two"],
    }
