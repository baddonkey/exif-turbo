from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from .selected_image_snapshot import SelectedImageSnapshot


class SelectedImagePort(Protocol):
    """Port used by the MCP layer to read/mutate the UI selection."""

    def get_selected_image(self) -> SelectedImageSnapshot | None:
        """Return the current selection, or ``None`` when nothing is selected."""
        ...

    def load_preview_jpeg(self) -> bytes | None:
        """Return a JPEG preview of the current selection, or ``None``."""
        ...

    def add_custom_tags(self, tags: Sequence[str]) -> tuple[str, ...]:
        """Add custom tags to the selected image and return the resulting set."""
        ...

    def list_image_sets(self) -> list[dict[str, Any]]:
        """Return sets available in the active database."""
        ...

    def get_image_set_images(
        self,
        set_id: int,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Return one ordered page of indexed images in a set."""
        ...

    def load_image_preview_jpeg(self, image_id: int) -> bytes | None:
        """Return an indexed image's JPEG preview, or ``None`` if unavailable."""
        ...

    def set_image_custom_tags(
        self,
        image_id: int,
        path: str,
        tags: Sequence[str],
        mode: str,
    ) -> tuple[str, ...]:
        """Apply custom tags to an indexed image after verifying its identity."""
        ...

    def set_image_description(
        self, image_id: int, path: str, description: str, mode: str
    ) -> tuple[str, bool]:
        """Update a verified indexed image; return its description and changed flag."""
        ...

    def set_image_description_excluded(
        self, image_id: int, path: str, excluded: bool
    ) -> tuple[bool, bool]:
        """Set the independent embedded-description exclusion flag."""
        ...

    def set_image_embedded_tag_excluded(
        self, image_id: int, path: str, tag: str, excluded: bool
    ) -> tuple[tuple[str, ...], bool, bool]:
        """Return individual exclusions, ignore-all flag, and changed flag."""
        ...

    def set_image_all_embedded_tags_excluded(
        self, image_id: int, path: str, excluded: bool
    ) -> tuple[tuple[str, ...], bool, bool]:
        """Toggle ignore-all without clearing individual exclusions."""
        ...
