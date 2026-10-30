from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal


SearchFilterKind = Literal["tags", "embedded-tags", "custom-tags", "description"]


@dataclass(frozen=True)
class StructuredSearchFilter:
    kind: SearchFilterKind
    values: tuple[str, ...]


@dataclass(frozen=True)
class ParsedSearchQuery:
    text: str
    filters: tuple[StructuredSearchFilter, ...]


class SearchQueryParseError(ValueError):
    """Raised when a structured search expression is malformed."""


_OPERATOR_PATTERN = re.compile(
    r"(?:embedded-tags|custom-tags|description|tags):=", re.IGNORECASE
)


def parse_search_query(query: str) -> ParsedSearchQuery:
    """Separate structured operators from ordinary FTS query text."""
    filters: list[StructuredSearchFilter] = []
    text_parts: list[str] = []
    position = 0

    while position < len(query):
        character = query[position]
        if character == '"':
            end = _quoted_end(query, position)
            text_parts.append(query[position:end])
            position = end
            continue

        match = _OPERATOR_PATTERN.match(query, position)
        at_token_boundary = (
            position == 0
            or query[position - 1].isspace()
            or query[position - 1] == "("
        )
        if match is None or not at_token_boundary:
            text_parts.append(character)
            position += 1
            continue

        kind = match.group(0)[:-2].lower()
        value_start = match.end()
        while value_start < len(query) and query[value_start].isspace():
            value_start += 1
        if value_start >= len(query) or query[value_start] != '"':
            raise SearchQueryParseError(
                f'{kind}:= requires a quoted value (for example {kind}:="value").'
            )

        raw_value, position = _read_quoted_value(query, value_start)
        values = _normalize_values(kind, raw_value)
        filters.append(StructuredSearchFilter(kind=kind, values=values))
        text_parts.append(" ")

    return ParsedSearchQuery(text="".join(text_parts).strip(), filters=tuple(filters))


def _quoted_end(query: str, start: int) -> int:
    position = start + 1
    while position < len(query):
        if query[position] == "\\" and position + 1 < len(query):
            position += 2
        elif query[position] == '"' and position + 1 < len(query) and query[position + 1] == '"':
            position += 2
        elif query[position] == '"':
            return position + 1
        else:
            position += 1
    return len(query)


def _read_quoted_value(query: str, start: int) -> tuple[str, int]:
    value: list[str] = []
    position = start + 1
    while position < len(query):
        character = query[position]
        if character == '"' and position + 1 < len(query) and query[position + 1] == '"':
            value.append('"')
            position += 2
            continue
        if character == '"':
            return "".join(value), position + 1
        if character == "\\" and position + 1 < len(query):
            following = query[position + 1]
            if following in {'"', "\\"}:
                value.append(following)
                position += 2
                continue
        value.append(character)
        position += 1
    raise SearchQueryParseError("Structured search value is missing its closing quote.")


def _normalize_values(kind: SearchFilterKind, raw_value: str) -> tuple[str, ...]:
    if kind == "description":
        value = unicodedata.normalize("NFC", raw_value)
        if not value:
            raise SearchQueryParseError("description:= requires a non-empty value.")
        return (value,)

    values: list[str] = []
    seen: set[str] = set()
    for raw_tag in raw_value.split(","):
        tag = unicodedata.normalize("NFC", raw_tag.strip())
        if not tag:
            raise SearchQueryParseError("Tag filters must contain non-empty values.")
        normalized = tag.casefold()
        if normalized not in seen:
            seen.add(normalized)
            values.append(tag)
    return tuple(values)