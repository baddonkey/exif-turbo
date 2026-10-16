from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .selected_image_snapshot import SelectedImageSnapshot


class SelectedImagePort(Protocol):
    """Port used by the MCP layer to read/mutate the UI selection."""

    def get_selected_image(self) -> SelectedImageSnapshot | None:
        """Return the current selection, or ``None`` when nothing is selected."""

    def load_preview_jpeg(self) -> bytes | None:
        """Return a JPEG preview of the current selection, or ``None``."""

    def add_custom_tags(self, tags: Sequence[str]) -> tuple[str, ...]:
        """Add custom tags to the selected image and return the resulting set."""
