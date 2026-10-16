from __future__ import annotations

from collections.abc import Sequence

import pytest

from exif_turbo.mcp.mcp_session_service import McpSessionError, McpSessionService
from exif_turbo.mcp.selected_image_snapshot import SelectedImageSnapshot


class _FakePort:
    def __init__(
        self,
        snapshot: SelectedImageSnapshot | None = None,
        preview: bytes | None = None,
        resulting_tags: tuple[str, ...] = (),
    ) -> None:
        self._snapshot = snapshot
        self._preview = preview
        self._resulting_tags = resulting_tags
        self.added: list[str] = []

    def get_selected_image(self) -> SelectedImageSnapshot | None:
        return self._snapshot

    def load_preview_jpeg(self) -> bytes | None:
        return self._preview

    def add_custom_tags(self, tags: Sequence[str]) -> tuple[str, ...]:
        self.added.extend(list(tags))
        return self._resulting_tags


def test_mcp_session_service_get_selected_image_without_selection_raises() -> None:
    # Arrange
    service = McpSessionService(_FakePort())

    # Act / Assert
    with pytest.raises(McpSessionError, match="No image is currently selected"):
        service.get_selected_image()


def test_mcp_session_service_get_selected_image_includes_preview_base64() -> None:
    # Arrange
    snapshot = SelectedImageSnapshot(
        path="/photos/a.jpg",
        filename="a.jpg",
        image_id=7,
        free_tags=("sunset",),
        has_preview=True,
        metadata_json='{"Make":"Canon"}',
    )
    service = McpSessionService(_FakePort(snapshot=snapshot, preview=b"jpeg-bytes"))

    # Act
    payload = service.get_selected_image(include_preview=True)

    # Assert
    assert payload.path == "/photos/a.jpg"
    assert payload.filename == "a.jpg"
    assert payload.image_id == 7
    assert payload.free_tags == ("sunset",)
    assert payload.metadata == {"Make": "Canon"}
    assert payload.preview_jpeg_base64 is not None
    assert payload.to_dict()["preview_jpeg_base64"] == payload.preview_jpeg_base64


def test_mcp_session_service_add_custom_tags_rejects_empty_and_returns_result() -> None:
    # Arrange
    snapshot = SelectedImageSnapshot(
        path="/photos/a.jpg",
        filename="a.jpg",
        image_id=1,
        free_tags=(),
        has_preview=False,
        metadata_json=None,
    )
    port = _FakePort(snapshot=snapshot, resulting_tags=("alpha", "beta"))
    service = McpSessionService(port)

    # Act / Assert
    with pytest.raises(McpSessionError, match="at least one"):
        service.add_custom_tags(["  ", ""])

    result = service.add_custom_tags([" alpha ", "beta"])
    assert result == {
        "path": "/photos/a.jpg",
        "added": ["alpha", "beta"],
        "free_tags": ["alpha", "beta"],
    }
    assert port.added == ["alpha", "beta"]
