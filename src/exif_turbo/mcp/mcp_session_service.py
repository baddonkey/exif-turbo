from __future__ import annotations

import base64
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from .selected_image_port import SelectedImagePort
from .selected_image_snapshot import SelectedImageSnapshot

_log = logging.getLogger(__name__)


class McpSessionError(RuntimeError):
    """Raised when an MCP session operation cannot complete."""


MAX_IMAGE_SET_PAGE_SIZE = 50
MAX_INLINE_PREVIEW_IMAGES = 5
MAX_IMAGE_TAG_BATCH_SIZE = 100


@dataclass(frozen=True)
class SelectedImagePayload:
    """Structured payload returned to MCP clients for the current selection."""

    path: str
    filename: str
    image_id: int | None
    free_tags: tuple[str, ...]
    has_preview: bool
    metadata: dict[str, Any] | None
    preview_jpeg_base64: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "image_id": self.image_id,
            "free_tags": list(self.free_tags),
            "has_preview": self.has_preview,
            "metadata": self.metadata,
            "preview_jpeg_base64": self.preview_jpeg_base64,
        }


class McpSessionService:
    """Application service backing MCP tools for the current selection."""

    def __init__(self, port: SelectedImagePort) -> None:
        self._port = port

    def get_selected_image(self, *, include_preview: bool = True) -> SelectedImagePayload:
        snapshot = self._require_selection()
        preview_b64: str | None = None
        if include_preview:
            jpeg = self._port.load_preview_jpeg()
            if jpeg:
                preview_b64 = base64.b64encode(jpeg).decode("ascii")
        return SelectedImagePayload(
            path=snapshot.path,
            filename=snapshot.filename,
            image_id=snapshot.image_id,
            free_tags=snapshot.free_tags,
            has_preview=snapshot.has_preview,
            metadata=self._parse_metadata(snapshot.metadata_json),
            preview_jpeg_base64=preview_b64,
        )

    def add_custom_tags(self, tags: Sequence[str]) -> dict[str, Any]:
        cleaned = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        if not cleaned:
            raise McpSessionError("Provide at least one non-empty custom tag.")
        snapshot = self._require_selection()
        resulting = self._port.add_custom_tags(cleaned)
        _log.info(
            "MCP add_custom_tags succeeded: image_id=%s path=%r mode=append "
            "requested_tags=%r free_tags=%r",
            snapshot.image_id,
            snapshot.path,
            cleaned,
            list(resulting),
        )
        return {
            "path": snapshot.path,
            "added": cleaned,
            "free_tags": list(resulting),
        }

    def list_image_sets(self) -> list[dict[str, Any]]:
        return self._port.list_image_sets()

    def get_image_set_images(
        self,
        set_id: int,
        *,
        offset: int = 0,
        limit: int | None = None,
        include_previews: bool = False,
    ) -> dict[str, Any]:
        if isinstance(set_id, bool) or not isinstance(set_id, int) or set_id < 1:
            raise McpSessionError("set_id must be a positive integer.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise McpSessionError("offset must not be negative.")
        if limit is None:
            limit = MAX_INLINE_PREVIEW_IMAGES if include_previews else 25
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > MAX_IMAGE_SET_PAGE_SIZE:
            raise McpSessionError(
                f"limit must be between 1 and {MAX_IMAGE_SET_PAGE_SIZE}."
            )
        if include_previews and limit > MAX_INLINE_PREVIEW_IMAGES:
            raise McpSessionError(
                "Inline previews are limited to "
                f"{MAX_INLINE_PREVIEW_IMAGES} images per request."
            )
        images = self._port.get_image_set_images(set_id, limit, offset)
        result_images: list[dict[str, Any]] = []
        for image in images:
            payload = dict(image)
            image_id = payload.get("id")
            payload["preview_uri"] = (
                f"exif-turbo://images/{image_id}/preview"
                if isinstance(image_id, int) and not isinstance(image_id, bool)
                else None
            )
            payload["preview_jpeg_base64"] = None
            if include_previews and payload["preview_uri"] is not None:
                preview = self._port.load_image_preview_jpeg(cast(int, image_id))
                if preview:
                    payload["preview_jpeg_base64"] = base64.b64encode(
                        preview
                    ).decode("ascii")
            result_images.append(payload)
        next_offset = offset + len(result_images) if len(result_images) == limit else None
        return {
            "set_id": set_id,
            "offset": offset,
            "limit": limit,
            "images": result_images,
            "next_offset": next_offset,
        }

    def get_image_preview(self, image_id: int) -> bytes:
        if isinstance(image_id, bool) or image_id < 1:
            raise McpSessionError("image_id must be a positive integer.")
        preview = self._port.load_image_preview_jpeg(image_id)
        if not preview:
            raise McpSessionError("No preview is available for this image.")
        return preview

    def set_custom_tags_batch(
        self,
        updates: Sequence[Any],
    ) -> dict[str, Any]:
        if not isinstance(updates, Sequence) or isinstance(updates, (str, bytes)):
            raise McpSessionError("updates must be a list of image tag operations.")
        if len(updates) > MAX_IMAGE_TAG_BATCH_SIZE:
            raise McpSessionError(
                f"A tag batch may contain at most {MAX_IMAGE_TAG_BATCH_SIZE} images."
            )
        results: list[dict[str, Any]] = []
        for update in updates:
            result = self._set_custom_tags_for_image(update)
            results.append(result)
        succeeded = sum(result["ok"] for result in results)
        return {
            "results": results,
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
        }

    def _set_custom_tags_for_image(
        self,
        update: Any,
    ) -> dict[str, Any]:
        if not isinstance(update, Mapping):
            return {"ok": False, "error": "Each update must be an object."}
        image_id = update.get("image_id")
        path = update.get("path")
        tags = update.get("tags")
        mode = update.get("mode", "append")
        if isinstance(image_id, bool) or not isinstance(image_id, int) or image_id < 1:
            return {"image_id": image_id, "path": path, "ok": False, "error": "image_id must be a positive integer."}
        if not isinstance(path, str) or not path:
            return {"image_id": image_id, "path": path, "ok": False, "error": "path is required."}
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            return {"image_id": image_id, "path": path, "ok": False, "error": "tags must be a list of strings."}
        if not isinstance(mode, str) or mode not in {"append", "replace"}:
            return {"image_id": image_id, "path": path, "ok": False, "error": "mode must be 'append' or 'replace'."}
        cleaned = [tag.strip() for tag in tags if tag.strip()]
        if mode == "append" and not cleaned:
            return {"image_id": image_id, "path": path, "ok": False, "error": "append requires at least one non-empty tag."}
        try:
            resulting = self._port.set_image_custom_tags(
                image_id, path, cleaned, mode
            )
        except Exception as exc:  # noqa: BLE001 — report per-image failures
            return {
                "image_id": image_id,
                "path": path,
                "ok": False,
                "error": str(exc),
            }
        _log.info(
            "MCP set_custom_tags_batch succeeded: image_id=%s path=%r mode=%s "
            "requested_tags=%r free_tags=%r",
            image_id,
            path,
            mode,
            cleaned,
            list(resulting),
        )
        return {
            "image_id": image_id,
            "path": path,
            "ok": True,
            "mode": mode,
            "free_tags": list(resulting),
        }

    def _require_selection(self) -> SelectedImageSnapshot:
        snapshot = self._port.get_selected_image()
        if snapshot is None:
            raise McpSessionError("No image is currently selected in exif-turbo.")
        return snapshot

    @staticmethod
    def _parse_metadata(raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else {"value": parsed}
