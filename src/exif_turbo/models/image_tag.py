from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any


_TGM_CONCEPT_ID = re.compile(r"^loc-tgm:tgm\d{6}$")
_WIKIDATA_CONCEPT_ID = re.compile(r"^wikidata:Q[1-9]\d*$")
_TAG_CATEGORIES = frozenset({"subject", "genre_format"})
_TAG_METHODS = frozenset({"manual", "clip"})


class SidecarValidationError(ValueError):
    """Raised when sidecar data does not satisfy the supported schema."""


def validate_utc_timestamp(value: str, field_name: str) -> None:
    if not value.endswith("Z"):
        raise SidecarValidationError(f"{field_name} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SidecarValidationError(f"{field_name} must be an RFC 3339 timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise SidecarValidationError(f"{field_name} must be a UTC timestamp")


def require_string(data: dict[str, Any], key: str, field_name: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SidecarValidationError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class TagProvenance:
    method: str
    accepted_at: str
    vocabulary_checksum: str
    confidence: float | None = None
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.method not in _TAG_METHODS:
            raise SidecarValidationError("provenance.method must be manual or clip")
        validate_utc_timestamp(self.accepted_at, "provenance.accepted_at")
        if not self.vocabulary_checksum.startswith("sha256:"):
            raise SidecarValidationError(
                "provenance.vocabulary_checksum must start with sha256:"
            )
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
                raise SidecarValidationError(
                    "provenance.confidence must be between 0 and 1"
                )
        if self.method == "clip" and (self.confidence is None or not self.model):
            raise SidecarValidationError(
                "clip provenance requires confidence and model"
            )

    @classmethod
    def from_dict(cls, data: object) -> TagProvenance:
        if not isinstance(data, dict):
            raise SidecarValidationError("tag.provenance must be an object")
        confidence = data.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool) or not isinstance(confidence, (int, float))
        ):
            raise SidecarValidationError(
                "provenance.confidence must be a number or null"
            )
        model = data.get("model")
        if model is not None and not isinstance(model, str):
            raise SidecarValidationError("provenance.model must be a string or null")
        known = {
            "method",
            "accepted_at",
            "confidence",
            "model",
            "vocabulary_checksum",
        }
        return cls(
            method=require_string(data, "method", "provenance.method"),
            accepted_at=require_string(
                data, "accepted_at", "provenance.accepted_at"
            ),
            confidence=float(confidence) if confidence is not None else None,
            model=model,
            vocabulary_checksum=require_string(
                data,
                "vocabulary_checksum",
                "provenance.vocabulary_checksum",
            ),
            extra={key: value for key, value in data.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extra,
            "method": self.method,
            "accepted_at": self.accepted_at,
            "confidence": self.confidence,
            "model": self.model,
            "vocabulary_checksum": self.vocabulary_checksum,
        }


@dataclass(frozen=True)
class ImageTag:
    concept_id: str
    label: str
    category: str
    provenance: TagProvenance
    vocabulary: str = "loc-tgm"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        valid_identity = (
            self.vocabulary == "loc-tgm"
            and _TGM_CONCEPT_ID.fullmatch(self.concept_id) is not None
        ) or (
            self.vocabulary == "wikidata"
            and _WIKIDATA_CONCEPT_ID.fullmatch(self.concept_id) is not None
        )
        if not valid_identity:
            raise SidecarValidationError(
                "tag.vocabulary and concept_id must be a valid pair: "
                "loc-tgm:tgmNNNNNN or wikidata:Q<positive integer>"
            )
        if not self.label.strip():
            raise SidecarValidationError("tag.label must be a non-empty string")
        if self.category not in _TAG_CATEGORIES:
            raise SidecarValidationError(
                "tag.category must be subject or genre_format"
            )

    @classmethod
    def from_dict(cls, data: object) -> ImageTag:
        if not isinstance(data, dict):
            raise SidecarValidationError("each tag must be an object")
        known = {
            "concept_id",
            "label",
            "vocabulary",
            "category",
            "provenance",
        }
        return cls(
            concept_id=require_string(data, "concept_id", "tag.concept_id"),
            label=require_string(data, "label", "tag.label"),
            vocabulary=require_string(data, "vocabulary", "tag.vocabulary"),
            category=require_string(data, "category", "tag.category"),
            provenance=TagProvenance.from_dict(data.get("provenance")),
            extra={key: value for key, value in data.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extra,
            "concept_id": self.concept_id,
            "label": self.label,
            "vocabulary": self.vocabulary,
            "category": self.category,
            "provenance": self.provenance.to_dict(),
        }