from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

from pytestqt.qtbot import QtBot

from exif_turbo.ui.view_models.mcp_controller import McpController


def test_mcp_controller_set_operations_dispatch_to_owner_thread(
    qtbot: QtBot,
) -> None:
    # Arrange
    owner_thread = threading.get_ident()
    observed_threads: list[int] = []
    results: list[object] = []

    def observe(value: object) -> object:
        observed_threads.append(threading.get_ident())
        return value

    controller = McpController(
        settings=None,
        is_locked=lambda: False,
        selected_path=lambda: None,
        selected_image_id=lambda: None,
        selected_metadata_json=lambda: None,
        selected_has_preview=lambda: False,
        selected_free_tags=lambda: (),
        selected_description=lambda: "",
        selected_description_excluded=lambda: False,
        selected_tag_exclusions=lambda: ((), False),
        load_preview_image=lambda: None,
        get_tagging_service=lambda: None,
        tagging_available=lambda: False,
        refresh_after_mutation=lambda: None,
        list_image_sets=lambda: observe([{"id": 1, "name": "Family"}]),
        get_image_set_images=lambda set_id, limit, offset: observe(
            [{"id": set_id, "limit": limit, "offset": offset}]
        ),
        load_indexed_preview_image=lambda image_id: observe(None),
        set_image_custom_tags=lambda image_id, path, tags, mode: observe(
            tuple(tags)
        ),
        set_image_description=lambda image_id, path, description, mode: observe(
            (description, True)
        ),
        set_image_description_excluded=lambda image_id, path, excluded: observe((excluded, True)),
        set_image_embedded_tag_excluded=lambda image_id, path, tag, excluded: observe(((tag,), False, True)),
        set_image_all_embedded_tags_excluded=lambda image_id, path, excluded: observe(((), excluded, True)),
    )

    def call_mcp_operations() -> None:
        try:
            results.extend(
                [
                    controller.list_image_sets(),
                    controller.get_image_set_images(7, 10, 20),
                    controller.load_image_preview_jpeg(7),
                    controller.set_image_custom_tags(
                        7, "/photos/a.jpg", ["family"], "append"
                    ),
                    controller.set_image_description(7, "/photos/a.jpg", "Caption", "append"),
                    controller.set_image_description_excluded(7, "/photos/a.jpg", True),
                    controller.set_image_embedded_tag_excluded(7, "/photos/a.jpg", "Keyword", True),
                    controller.set_image_all_embedded_tags_excluded(7, "/photos/a.jpg", True),
                ]
            )
        except BaseException as exc:  # noqa: BLE001
            results.append(exc)

    thread = threading.Thread(target=call_mcp_operations)

    # Act
    thread.start()
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=5000)
    controller.close()

    # Assert
    assert len(results) == 8
    assert not isinstance(results[0], BaseException)
    assert results[0] == [{"id": 1, "name": "Family"}]
    assert results[1] == [{"id": 7, "limit": 10, "offset": 20}]
    assert results[2] is None
    assert results[3] == ("family",)
    assert results[4] == ("Caption", True)
    assert results[5] == (True, True)
    assert results[6] == (("Keyword",), False, True)
    assert results[7] == ((), True, True)
    assert observed_threads == [owner_thread] * 8