from __future__ import annotations

import ast
import json
from typing import Iterable, Mapping


_EMBEDDED_KEYWORD_KEYS = (
    "XMP-dc:Subject",
    "XMP:Subject",
    "IPTC:Keywords",
    "XMP-lr:HierarchicalSubject",
    "XMP:HierarchicalSubject",
)
_EMBEDDED_KEYWORD_KEY_SET = frozenset(_EMBEDDED_KEYWORD_KEYS)


def metadata_text_without_embedded_keywords(
    metadata: Mapping[str, object],
) -> str:
    searchable_metadata = {
        key: value
        for key, value in metadata.items()
        if key not in _EMBEDDED_KEYWORD_KEY_SET
    }
    parts: list[str] = []
    for key, value in searchable_metadata.items():
        parts.extend((key, str(value)))
    parts.append(json.dumps(searchable_metadata, ensure_ascii=False))
    return " ".join(parts)


def merge_keyword_labels(*groups: Iterable[str]) -> tuple[str, ...]:
    labels_by_key: dict[str, str] = {}
    for group in groups:
        for value in group:
            label = value.strip()
            if label:
                labels_by_key.setdefault(label.casefold(), label)
    return tuple(
        sorted(labels_by_key.values(), key=lambda label: (label.casefold(), label))
    )


def extract_embedded_keyword_labels(
    metadata: Mapping[str, object],
) -> tuple[str, ...]:
    labels: list[str] = []
    for key in _EMBEDDED_KEYWORD_KEYS:
        value = metadata.get(key)
        values: object = value
        if isinstance(value, str) and value.strip().startswith(("[", "(")):
            try:
                values = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                values = value
        candidates = values if isinstance(values, (list, tuple)) else (values,)
        labels.extend(str(candidate) for candidate in candidates if candidate is not None)
    return merge_keyword_labels(labels)


def extract_embedded_description(metadata: Mapping[str, object]) -> str:
    descriptions: list[str] = []
    for key, value in metadata.items():
        group, _, name = key.rpartition(":")
        supported = (
            (group in {"IFD0", "IFD1", "EXIF"} and name == "ImageDescription")
            or (group in {"ExifIFD", "EXIF", "XMP-exif", "XMP"} and name == "UserComment")
            or (group == "IPTC" and name == "Caption-Abstract")
            or (
                group in {"XMP-dc", "XMP", "PNG", "QuickTime", "ItemList", "Keys", "UserData"}
                and (name == "Description" or name.startswith("Description-"))
            )
        )
        if not supported:
            continue
        values = value.values() if isinstance(value, dict) else (value,)
        for candidate in values:
            if not isinstance(candidate, str):
                continue
            text = candidate.replace("\r\n", "\n").replace("\r", "\n").strip()
            if text and text not in descriptions:
                descriptions.append(text)
    return "\n\n".join(descriptions)