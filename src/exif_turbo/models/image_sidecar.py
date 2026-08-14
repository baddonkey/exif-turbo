from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import unicodedata

from .image_tag import ImageTag, SidecarValidationError, require_string, validate_utc_timestamp


def normalize_free_tag(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise SidecarValidationError("free tags must be non-empty strings")
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise SidecarValidationError("free tags must not contain control characters")
    return normalized


@dataclass(frozen=True)
class SidecarSource:
    filename: str
    size: int | None = None
    mtime_ns: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.filename.strip():
            raise SidecarValidationError("source.filename must be a non-empty string")
        for field_name, value in (("source.size", self.size), ("source.mtime_ns", self.mtime_ns)):
            if value is not None and (isinstance(value, bool) or value < 0):
                raise SidecarValidationError(f"{field_name} must be a non-negative integer")

    @classmethod
    def from_dict(cls, data: object) -> SidecarSource:
        if not isinstance(data, dict):
            raise SidecarValidationError("source must be an object")
        size = data.get("size")
        mtime_ns = data.get("mtime_ns")
        if size is not None and (isinstance(size, bool) or not isinstance(size, int)):
            raise SidecarValidationError("source.size must be an integer or null")
        if mtime_ns is not None and (
            isinstance(mtime_ns, bool) or not isinstance(mtime_ns, int)
        ):
            raise SidecarValidationError("source.mtime_ns must be an integer or null")
        known = {"filename", "size", "mtime_ns"}
        return cls(
            filename=require_string(data, "filename", "source.filename"),
            size=size,
            mtime_ns=mtime_ns,
            extra={key: value for key, value in data.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {**self.extra, "filename": self.filename}
        if self.size is not None:
            result["size"] = self.size
        if self.mtime_ns is not None:
            result["mtime_ns"] = self.mtime_ns
        return result


@dataclass(frozen=True)
class ImageSidecar:
    source: SidecarSource
    updated_at: str
    tags: tuple[ImageTag, ...] = ()
    free_tags: tuple[str, ...] = ()
    schema_version: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise SidecarValidationError(
                f"unsupported sidecar schema version: {self.schema_version}"
            )
        validate_utc_timestamp(self.updated_at, "updated_at")
        concept_ids = [tag.concept_id for tag in self.tags]
        if len(concept_ids) != len(set(concept_ids)):
            raise SidecarValidationError("tags must be unique by concept_id")
        normalized_free_tags = tuple(normalize_free_tag(tag) for tag in self.free_tags)
        normalized_keys = [tag.casefold() for tag in normalized_free_tags]
        if len(normalized_keys) != len(set(normalized_keys)):
            raise SidecarValidationError("free tags must be unique ignoring case")
        object.__setattr__(self, "free_tags", normalized_free_tags)

    @classmethod
    def from_dict(cls, data: object) -> ImageSidecar:
        if not isinstance(data, dict):
            raise SidecarValidationError("sidecar must be a JSON object")
        schema_version = data.get("schema_version")
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise SidecarValidationError("schema_version must be an integer")
        raw_tags = data.get("tags")
        if not isinstance(raw_tags, list):
            raise SidecarValidationError("tags must be an array")
        raw_free_tags = data.get("free_tags", [])
        if not isinstance(raw_free_tags, list) or not all(
            isinstance(tag, str) for tag in raw_free_tags
        ):
            raise SidecarValidationError("free_tags must be an array of strings")
        known = {"schema_version", "source", "updated_at", "tags", "free_tags"}
        return cls(
            schema_version=schema_version,
            source=SidecarSource.from_dict(data.get("source")),
            updated_at=require_string(data, "updated_at", "updated_at"),
            tags=tuple(ImageTag.from_dict(tag) for tag in raw_tags),
            free_tags=tuple(raw_free_tags),
            extra={key: value for key, value in data.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        ordered_tags = sorted(
            self.tags,
            key=lambda tag: (tag.label.casefold(), tag.concept_id),
        )
        ordered_free_tags = sorted(
            self.free_tags,
            key=lambda tag: (tag.casefold(), tag),
        )
        return {
            **self.extra,
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "updated_at": self.updated_at,
            "tags": [tag.to_dict() for tag in ordered_tags],
            "free_tags": ordered_free_tags,
        }