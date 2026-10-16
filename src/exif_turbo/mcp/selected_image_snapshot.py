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
