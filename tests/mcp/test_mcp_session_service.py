from __future__ import annotations

import logging
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
        self.image_sets: list[dict[str, object]] = []
        self.image_set_images: list[dict[str, object]] = []
        self.previews: dict[int, bytes] = {}
        self.image_tag_updates: list[tuple[int, str, tuple[str, ...], str]] = []
        self.tag_exclusions: tuple[str, ...] = ()
        self.exclude_all = False

    def get_selected_image(self) -> SelectedImageSnapshot | None:
        return self._snapshot

    def load_preview_jpeg(self) -> bytes | None:
        return self._preview

    def add_custom_tags(self, tags: Sequence[str]) -> tuple[str, ...]:
        self.added.extend(list(tags))
        return self._resulting_tags

    def list_image_sets(self) -> list[dict[str, object]]:
        return self.image_sets

    def get_image_set_images(
        self,
        set_id: int,
        limit: int,
        offset: int,
    ) -> list[dict[str, object]]:
        return self.image_set_images[offset : offset + limit]

    def load_image_preview_jpeg(self, image_id: int) -> bytes | None:
        return self.previews.get(image_id)

    def set_image_custom_tags(
        self,
        image_id: int,
        path: str,
        tags: Sequence[str],
        mode: str,
    ) -> tuple[str, ...]:
        self.image_tag_updates.append((image_id, path, tuple(tags), mode))
        if path == "/photos/fail.jpg":
            raise RuntimeError("sidecar conflict")
        return tuple(tags)

    def set_image_description(
        self, image_id: int, path: str, description: str, mode: str
    ) -> tuple[str, bool]:
        if path == "/photos/fail.jpg":
            raise RuntimeError("sidecar conflict")
        return description, True

    def set_image_description_excluded(
        self, image_id: int, path: str, excluded: bool
    ) -> tuple[bool, bool]:
        return excluded, True

    def set_image_embedded_tag_excluded(
        self, image_id: int, path: str, tag: str, excluded: bool
    ) -> tuple[tuple[str, ...], bool, bool]:
        self.tag_exclusions = (tag,) if excluded else ()
        return self.tag_exclusions, self.exclude_all, True

    def set_image_all_embedded_tags_excluded(
        self, image_id: int, path: str, excluded: bool
    ) -> tuple[tuple[str, ...], bool, bool]:
        self.exclude_all = excluded
        return self.tag_exclusions, self.exclude_all, True


@pytest.mark.parametrize("all_tags", [False, True])
@pytest.mark.parametrize("arguments", [
    {"image_id": True, "path": "/photos/a.jpg", "excluded": True},
    {"image_id": 0, "path": "/photos/a.jpg", "excluded": True},
    {"image_id": 1, "path": "", "excluded": True},
    {"image_id": 1, "path": "/photos/a.jpg", "excluded": "false"},
])
def test_mcp_tag_exclusion_invalid_input_rejected(all_tags: bool, arguments: dict[str, object]) -> None:
    # Arrange
    port = _FakePort()
    service = McpSessionService(port)
    operation = (
        service.set_image_all_embedded_tags_excluded if all_tags
        else service.set_image_embedded_tag_excluded
    )
    if not all_tags:
        arguments = {**arguments, "tag": "Keyword"}

    # Act / Assert
    with pytest.raises(McpSessionError):
        operation(**arguments)  # type: ignore[arg-type]
    assert port.tag_exclusions == () and not port.exclude_all


@pytest.mark.parametrize("tag", ["", "  ", "\x00", 42])
def test_mcp_individual_tag_exclusion_invalid_tag_rejected(tag: object) -> None:
    # Arrange
    service = McpSessionService(_FakePort())

    # Act / Assert
    with pytest.raises(McpSessionError):
        service.set_image_embedded_tag_excluded(1, "/photos/a.jpg", tag, True)  # type: ignore[arg-type]


def test_mcp_tag_exclusions_readback_and_state_are_independent() -> None:
    # Arrange
    snapshot = SelectedImageSnapshot(
        path="/photos/a.jpg", filename="a.jpg", image_id=1, free_tags=(),
        has_preview=False, metadata_json=None,
        excluded_embedded_tags=("Keyword",), exclude_all_embedded_tags=True,
    )
    service = McpSessionService(_FakePort(snapshot))

    # Act
    individual = service.set_image_embedded_tag_excluded(1, snapshot.path, " Keyword ", True)
    all_tags = service.set_image_all_embedded_tags_excluded(1, snapshot.path, True)
    restored = service.set_image_all_embedded_tags_excluded(1, snapshot.path, False)
    payload = service.get_selected_image(include_preview=False).to_dict()

    # Assert
    assert individual["excluded_embedded_tags"] == ["Keyword"]
    assert all_tags["exclude_all_embedded_tags"] is True
    assert restored["excluded_embedded_tags"] == ["Keyword"]
    assert restored["exclude_all_embedded_tags"] is False
    assert payload["excluded_embedded_tags"] == ["Keyword"]
    assert payload["exclude_all_embedded_tags"] is True


def test_mcp_session_service_get_selected_image_without_selection_raises() -> None:
    # Arrange
    service = McpSessionService(_FakePort())

    # Act / Assert
    with pytest.raises(McpSessionError, match="No image is currently selected"):
        service.get_selected_image()


def test_mcp_description_readback_includes_saved_text() -> None:
    # Arrange
    snapshot = SelectedImageSnapshot(
        path="/photos/a.jpg", filename="a.jpg", image_id=1, free_tags=(),
        has_preview=False, metadata_json=None, description="Saved caption",
    )
    service = McpSessionService(_FakePort(snapshot))

    # Act / Assert
    assert service.get_selected_image(include_preview=False).to_dict()["description"] == "Saved caption"


def test_mcp_description_batch_reports_mixed_success_and_failure() -> None:
    # Arrange
    service = McpSessionService(_FakePort())

    # Act
    result = service.set_image_descriptions_batch([
        {"image_id": 1, "path": "/photos/a.jpg", "description": "Caption", "mode": "append"},
        {"image_id": 2, "path": "/photos/fail.jpg", "description": "Caption", "mode": "replace"},
        {"image_id": 3, "path": "/photos/a.jpg", "description": "Caption"},
        {"image_id": 4, "path": "/photos/a.jpg", "description": "", "mode": "replace"},
    ])

    # Assert
    assert result["succeeded"] == 2
    assert result["failed"] == 2
    assert result["results"][0]["description"] == "Caption"
    assert result["results"][0]["changed"] is True
    assert result["results"][1]["error"] == "sidecar conflict"
    assert "mode" in result["results"][2]["error"]
    assert result["results"][3]["description"] == ""


@pytest.mark.parametrize(
    "update",
    [
        {"image_id": True, "path": "/photos/a.jpg", "description": "Caption", "mode": "replace"},
        {"image_id": 1, "path": "", "description": "Caption", "mode": "replace"},
        {"image_id": 1, "path": "/photos/a.jpg", "description": "", "mode": "append"},
        {"image_id": 1, "path": "/photos/a.jpg", "description": None, "mode": "replace"},
        {"image_id": 1, "path": "/photos/a.jpg", "description": "Bad\x00text", "mode": "replace"},
    ],
)
def test_mcp_description_invalid_batch_input_returns_explicit_error(update: dict[str, object]) -> None:
    # Arrange
    service = McpSessionService(_FakePort())

    # Act
    result = service.set_image_descriptions_batch([update])

    # Assert
    assert result["failed"] == 1
    assert result["results"][0]["ok"] is False
    assert result["results"][0]["error"]


def test_mcp_description_batch_limit_is_exactly_one_hundred() -> None:
    # Arrange
    service = McpSessionService(_FakePort())
    update = {"image_id": 1, "path": "/photos/a.jpg", "description": "Caption", "mode": "replace"}

    # Act / Assert
    assert service.set_image_descriptions_batch([update] * 100)["succeeded"] == 100
    with pytest.raises(McpSessionError, match="at most 100"):
        service.set_image_descriptions_batch([update] * 101)


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


def test_mcp_session_service_get_image_set_page_includes_preview_data() -> None:
    # Arrange
    port = _FakePort()
    port.image_set_images = [
        {"id": 5, "path": "/photos/a.jpg", "metadata": {"Make": "Canon"}}
    ]
    port.previews[5] = b"jpeg"
    service = McpSessionService(port)

    # Act
    page = service.get_image_set_images(2, limit=1, include_previews=True)

    # Assert
    image = page["images"][0]
    assert image["preview_uri"] == "exif-turbo://images/5/preview"
    assert image["preview_jpeg_base64"] == "anBlZw=="
    assert image["metadata"] == {"Make": "Canon"}


def test_mcp_session_service_inline_previews_enforce_small_page_limit() -> None:
    # Arrange
    service = McpSessionService(_FakePort())

    # Act / Assert
    with pytest.raises(McpSessionError, match="limited to 5 images"):
        service.get_image_set_images(1, limit=6, include_previews=True)


@pytest.mark.parametrize(("include_previews", "expected_limit"), [(False, 25), (True, 5)])
def test_mcp_session_service_image_set_default_limit_matches_preview_mode(
    include_previews: bool,
    expected_limit: int,
) -> None:
    # Arrange
    port = _FakePort()
    port.image_set_images = [
        {"id": image_id, "free_tags": ["Oberkulm"]}
        for image_id in range(1, 31)
    ]
    port.previews = {image_id: b"jpeg" for image_id in range(1, 31)}
    service = McpSessionService(port)

    # Act
    page = service.get_image_set_images(1, include_previews=include_previews)

    # Assert
    assert page["limit"] == expected_limit
    assert len(page["images"]) == expected_limit
    assert page["next_offset"] == expected_limit
    assert all(image["free_tags"] == ["Oberkulm"] for image in page["images"])
    assert all(
        image["preview_jpeg_base64"] == ("anBlZw==" if include_previews else None)
        for image in page["images"]
    )


def test_mcp_session_service_tag_batch_continues_after_image_failure() -> None:
    # Arrange
    port = _FakePort()
    service = McpSessionService(port)
    updates = [
        {"image_id": 1, "path": "/photos/a.jpg", "tags": [" alpha "]},
        {"image_id": 2, "path": "/photos/fail.jpg", "tags": ["beta"]},
        {"image_id": 3, "path": "/photos/c.jpg", "tags": [], "mode": "replace"},
    ]

    # Act
    result = service.set_custom_tags_batch(updates)

    # Assert
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert [item["ok"] for item in result["results"]] == [True, False, True]
    assert port.image_tag_updates == [
        (1, "/photos/a.jpg", ("alpha",), "append"),
        (2, "/photos/fail.jpg", ("beta",), "append"),
        (3, "/photos/c.jpg", (), "replace"),
    ]


def test_mcp_session_service_tag_batch_reports_malformed_items_individually() -> None:
    # Arrange
    service = McpSessionService(_FakePort())

    # Act
    result = service.set_custom_tags_batch(["invalid", {
        "image_id": 4,
        "path": "/photos/ok.jpg",
        "tags": ["tag"],
    }])

    # Assert
    assert result["failed"] == 1
    assert result["succeeded"] == 1
    assert result["results"][0]["error"] == "Each update must be an object."


def test_mcp_session_service_add_custom_tags_success_logs_target_and_tags(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    snapshot = SelectedImageSnapshot(
        path="/photos/a.jpg",
        filename="a.jpg",
        image_id=7,
        free_tags=("existing",),
        has_preview=False,
        metadata_json=None,
    )
    service = McpSessionService(
        _FakePort(snapshot=snapshot, resulting_tags=("existing", "new"))
    )

    # Act
    with caplog.at_level(logging.INFO, logger="exif_turbo.mcp.mcp_session_service"):
        service.add_custom_tags([" new "])

    # Assert
    assert caplog.record_tuples == [
        (
            "exif_turbo.mcp.mcp_session_service",
            logging.INFO,
            "MCP add_custom_tags succeeded: image_id=7 path='/photos/a.jpg' "
            "mode=append requested_tags=['new'] free_tags=['existing', 'new']",
        )
    ]


def test_mcp_session_service_tag_batch_logs_each_success_not_failed_updates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    service = McpSessionService(_FakePort())
    updates = [
        {"image_id": 1, "path": "/photos/a.jpg", "tags": [" alpha "]},
        {"image_id": 2, "path": "/photos/fail.jpg", "tags": ["beta"]},
        {"image_id": 3, "path": "/photos/c.jpg", "tags": [], "mode": "replace"},
        {"image_id": 4, "path": "/photos/invalid.jpg", "tags": []},
    ]

    # Act
    with caplog.at_level(logging.INFO, logger="exif_turbo.mcp.mcp_session_service"):
        result = service.set_custom_tags_batch(updates)

    # Assert
    assert result["succeeded"] == 2
    assert result["failed"] == 2
    assert caplog.record_tuples == [
        (
            "exif_turbo.mcp.mcp_session_service",
            logging.INFO,
            "MCP set_custom_tags_batch succeeded: image_id=1 path='/photos/a.jpg' "
            "mode=append requested_tags=['alpha'] free_tags=['alpha']",
        ),
        (
            "exif_turbo.mcp.mcp_session_service",
            logging.INFO,
            "MCP set_custom_tags_batch succeeded: image_id=3 path='/photos/c.jpg' "
            "mode=replace requested_tags=[] free_tags=[]",
        ),
    ]


def test_mcp_session_service_add_custom_tags_without_selection_does_not_log_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    service = McpSessionService(_FakePort())

    # Act / Assert
    with caplog.at_level(logging.INFO, logger="exif_turbo.mcp.mcp_session_service"):
        with pytest.raises(McpSessionError, match="No image is currently selected"):
            service.add_custom_tags(["new"])
    assert caplog.records == []
