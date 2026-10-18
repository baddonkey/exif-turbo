from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectedImageSnapshot:
    """Read-only view of the image currently selected in the UI."""

    path: str
    filename: str
    image_id: int | None
    free_tags: tuple[str, ...]
    has_preview: bool
    metadata_json: str | None
    description: str = ""
    exclude_embedded_description: bool = False
    excluded_embedded_tags: tuple[str, ...] = ()
    exclude_all_embedded_tags: bool = False
