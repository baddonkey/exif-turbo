"""Formatting helpers for the *Export Marked Metadata as JSON* feature.

The export is streamed one record at a time so the GUI progress bar can advance
while a large database is written.  These helpers keep the formatting logic pure
and testable, independent of the Qt worker that drives the streaming.

The default format (``JsonExportFormat()``) reproduces the historical output
byte-for-byte: a top-level array with each record serialised compactly on its
own line.  Users can opt in to pretty-printed output and choose the indentation
style (tabs or spaces) and, for spaces, the indentation width.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Iterator

INDENT_STYLE_SPACE = "space"
INDENT_STYLE_TAB = "tab"
_VALID_INDENT_STYLES = {INDENT_STYLE_SPACE, INDENT_STYLE_TAB}

_MIN_INDENT_SIZE = 1
_MAX_INDENT_SIZE = 8


def normalize_indent_style(value: str) -> str:
    """Return *value* if it is a supported indent style, else ``"space"``."""
    return value if value in _VALID_INDENT_STYLES else INDENT_STYLE_SPACE


def clamp_indent_size(value: int) -> int:
    """Clamp *value* to the supported indentation width range."""
    return max(_MIN_INDENT_SIZE, min(_MAX_INDENT_SIZE, value))


@dataclass(frozen=True)
class JsonExportFormat:
    """Formatting options for a marked-metadata JSON export.

    - ``pretty`` — when ``False`` (default) records are written compactly, one
      per line, preserving the historical output.  When ``True`` each record is
      indented for human readability.
    - ``indent_style`` — ``"space"`` or ``"tab"``; only relevant when *pretty*.
    - ``indent_size`` — number of spaces per indent level; only relevant when
      *pretty* and *indent_style* is ``"space"``.
    """

    pretty: bool = False
    indent_style: str = INDENT_STYLE_SPACE
    indent_size: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "indent_style", normalize_indent_style(self.indent_style))
        object.__setattr__(self, "indent_size", clamp_indent_size(self.indent_size))

    @property
    def indent_unit(self) -> str | None:
        """The string used for one indentation level, or ``None`` when compact."""
        if not self.pretty:
            return None
        if self.indent_style == INDENT_STYLE_TAB:
            return "\t"
        return " " * self.indent_size


def render_record(record: object, fmt: JsonExportFormat) -> str:
    """Serialise a single *record* as it should appear inside the export array.

    For pretty output the record is indented by one level so it nests neatly
    beneath the enclosing ``[`` / ``]``.
    """
    indent = fmt.indent_unit
    if indent is None:
        return json.dumps(record, ensure_ascii=False)
    body = json.dumps(record, ensure_ascii=False, indent=indent)
    return "\n".join(indent + line for line in body.split("\n"))


def iter_json_export(records: Iterable[object], fmt: JsonExportFormat) -> Iterator[str]:
    """Yield the export text in chunks: opening bracket, each record, closing.

    Yielding per record lets callers stream output and report progress.  The
    record chunks already include the trailing comma/newline separators, so the
    concatenation of every yielded chunk is the complete JSON document.
    """
    records = list(records)
    total = len(records)
    yield "[\n"
    for idx, record in enumerate(records):
        chunk = render_record(record, fmt)
        chunk += ",\n" if idx < total - 1 else "\n"
        yield chunk
    yield "]\n"


def dumps_json_export(records: Iterable[object], fmt: JsonExportFormat) -> str:
    """Return the full export document as a single string."""
    return "".join(iter_json_export(records, fmt))
