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

    def list_image_sets(self) -> list[dict[str, Any]]:
        return [{"id": 4, "name": "Family", "member_count": 1}]

    def get_image_set_images(
        self,
        set_id: int,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": 3,
                "path": "/tmp/x.jpg",
                "filename": "x.jpg",
                "metadata": {"A": 1},
                "free_tags": ["tag-a"],
            }
        ][offset : offset + limit]

    def load_image_preview_jpeg(self, image_id: int) -> bytes | None:
        return b"\xff\xd8fakejpeg" if image_id == 3 else None

    def set_image_custom_tags(
        self,
        image_id: int,
        path: str,
        tags: Sequence[str],
        mode: str,
    ) -> tuple[str, ...]:
        return tuple(tags)

    def set_image_description(
        self, image_id: int, path: str, description: str, mode: str
    ) -> tuple[str, bool]:
        if path == "/tmp/fail.jpg":
            raise RuntimeError("sidecar conflict")
        return description, True

    def set_image_description_excluded(
        self, image_id: int, path: str, excluded: bool
    ) -> tuple[bool, bool]:
        return excluded, True

    def set_image_embedded_tag_excluded(
        self, image_id: int, path: str, tag: str, excluded: bool
    ) -> tuple[tuple[str, ...], bool, bool]:
        if path == "/tmp/fail.jpg":
            raise RuntimeError("sidecar conflict")
        return ((tag,) if excluded else ()), False, True

    def set_image_all_embedded_tags_excluded(
        self, image_id: int, path: str, excluded: bool
    ) -> tuple[tuple[str, ...], bool, bool]:
        if path == "/tmp/fail.jpg":
            raise RuntimeError("sidecar conflict")
        return (), excluded, True


@pytest.mark.parametrize("all_tags", [False, True])
def test_mcp_embedded_tag_exclusion_tools_expose_schema_and_surface_errors(all_tags: bool) -> None:
    # Arrange
    server = McpServerFactory(McpSessionService(_FakePort(None))).create()
    name = "set_image_all_embedded_tags_excluded" if all_tags else "set_image_embedded_tag_excluded"
    tool = _tool_fn(server, name)
    arguments = {} if all_tags else {"tag": "Keyword"}

    # Act
    result = tool(image_id=3, path="/tmp/x.jpg", excluded=True, **arguments)
    failed = tool(image_id=3, path="/tmp/fail.jpg", excluded=True, **arguments)
    invalid = tool(image_id=3, path="/tmp/x.jpg", excluded="true", **arguments)
    schema = next(tool.parameters for tool in server._tool_manager.list_tools() if tool.name == name)

    # Assert
    assert not result.is_error and result.structured_content is not None
    assert result.structured_content["changed"]
    assert result.structured_content["exclude_all_embedded_tags"] is all_tags
    assert result.structured_content["excluded_embedded_tags"] == ([] if all_tags else ["Keyword"])
    assert failed.is_error and invalid.is_error
    assert set(schema["required"]) == {"image_id", "path", "excluded", *arguments}


def _tool_fn(server: Any, name: str):
    for tool in server._tool_manager.list_tools():  # noqa: SLF001
        if tool.name == name:
            return tool.fn
    raise AssertionError(f"tool not found: {name}")


def test_mcp_description_tools_expose_explicit_modes_and_report_errors() -> None:
    # Arrange
    server = McpServerFactory(McpSessionService(_FakePort(None))).create()
    single = _tool_fn(server, "set_image_description")
    batch = _tool_fn(server, "set_image_descriptions_batch")

    # Act
    saved = single(image_id=3, path="/tmp/x.jpg", description="Caption", mode="replace")
    failed = single(image_id=3, path="/tmp/fail.jpg", description="Caption", mode="append")
    mixed = batch(updates=[
        {"image_id": 3, "path": "/tmp/x.jpg", "description": "Caption", "mode": "replace"},
        {"image_id": 3, "path": "/tmp/fail.jpg", "description": "Caption", "mode": "append"},
    ])
    schema = next(tool.parameters for tool in server._tool_manager.list_tools() if tool.name == "set_image_description")

    # Assert
    assert saved.structured_content is not None
    assert saved.structured_content["description"] == "Caption"
    assert saved.structured_content["changed"] is True
    assert failed.is_error
    assert mixed.structured_content is not None
    assert mixed.structured_content["succeeded"] == 1
    assert mixed.structured_content["failed"] == 1
    assert set(schema["required"]) == {"image_id", "path", "description", "mode"}


def test_mcp_description_exclusion_tool_needs_no_description_text() -> None:
    # Arrange
    server = McpServerFactory(McpSessionService(_FakePort(None))).create()
    tool = _tool_fn(server, "set_image_description_excluded")

    # Act
    result = tool(image_id=3, path="/tmp/x.jpg", excluded=True)
    invalid = tool(image_id=3, path="/tmp/x.jpg", excluded="true")

    # Assert
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["exclude_embedded_description"] is True
    assert invalid.is_error


def test_mcp_server_factory_get_selected_image_tool_returns_payload() -> None:
    # Arrange
    snapshot = SelectedImageSnapshot(
        path="/tmp/x.jpg",
        filename="x.jpg",
        image_id=3,
        free_tags=("tag-a",),
        has_preview=True,
        metadata_json='{"A":1}',
        description="Saved caption",
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
    assert result.structured_content["description"] == "Saved caption"
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


def test_mcp_server_factory_lists_sets_and_returns_paged_images() -> None:
    # Arrange
    factory = McpServerFactory(McpSessionService(_FakePort(None)))
    server = factory.create()
    list_tool = _tool_fn(server, "list_image_sets")
    page_tool = _tool_fn(server, "get_image_set_images")

    # Act
    sets_result = list_tool()
    page_result = page_tool(set_id=4, limit=1, include_previews=True)

    # Assert
    assert sets_result.structured_content == {
        "sets": [{"id": 4, "name": "Family", "member_count": 1}]
    }
    assert page_result.is_error is False
    assert page_result.structured_content["images"][0]["preview_uri"] == (
        "exif-turbo://images/3/preview"
    )
    assert any(getattr(block, "type", None) == "image" for block in page_result.content)


def test_mcp_server_factory_returns_per_image_tag_batch_results() -> None:
    # Arrange
    factory = McpServerFactory(McpSessionService(_FakePort(None)))
    server = factory.create()
    tool = _tool_fn(server, "set_custom_tags_batch")

    # Act
    result = tool(
        updates=[
            {
                "image_id": 3,
                "path": "/tmp/x.jpg",
                "tags": ["family"],
                "mode": "append",
            }
        ]
    )

    # Assert
    assert result.is_error is False
    assert result.structured_content["succeeded"] == 1
    assert result.structured_content["results"][0]["free_tags"] == ["family"]


def test_mcp_server_factory_image_set_previews_without_limit_returns_images() -> None:
    # Arrange
    factory = McpServerFactory(McpSessionService(_FakePort(None)))
    tool = _tool_fn(factory.create(), "get_image_set_images")

    # Act
    result = tool(set_id=4, include_previews=True)

    # Assert
    assert result.is_error is False
    assert result.structured_content["limit"] == 5
    assert result.structured_content["images"][0]["free_tags"] == ["tag-a"]
    assert any(getattr(block, "type", None) == "image" for block in result.content)
