from __future__ import annotations

import json

from exif_turbo.utils.json_export import (
    JsonExportFormat,
    clamp_indent_size,
    dumps_json_export,
    normalize_indent_style,
    render_record,
)


_RECORDS = [
    {"path": "/a.jpg", "filename": "a.jpg", "metadata": {"Make": "Canon"}},
    {"path": "/b.jpg", "filename": "b.jpg", "metadata": {"Make": "Nikon"}},
]


def test_dumps_json_export_default_is_compact_one_record_per_line() -> None:
    # Arrange
    fmt = JsonExportFormat()

    # Act
    text = dumps_json_export(_RECORDS, fmt)

    # Assert
    expected = (
        "[\n"
        + json.dumps(_RECORDS[0], ensure_ascii=False)
        + ",\n"
        + json.dumps(_RECORDS[1], ensure_ascii=False)
        + "\n]\n"
    )
    assert text == expected


def test_dumps_json_export_default_roundtrips_to_original_records() -> None:
    # Arrange
    fmt = JsonExportFormat()

    # Act
    parsed = json.loads(dumps_json_export(_RECORDS, fmt))

    # Assert
    assert parsed == _RECORDS


def test_dumps_json_export_pretty_spaces_indents_with_given_width() -> None:
    # Arrange
    fmt = JsonExportFormat(pretty=True, indent_style="space", indent_size=4)

    # Act
    text = dumps_json_export(_RECORDS[:1], fmt)

    # Assert
    assert '\n        "path": "/a.jpg"' in text  # 4 (array level) + 4 (object level)
    assert json.loads(text) == _RECORDS[:1]


def test_dumps_json_export_pretty_tabs_indents_with_tab_characters() -> None:
    # Arrange
    fmt = JsonExportFormat(pretty=True, indent_style="tab")

    # Act
    text = dumps_json_export(_RECORDS[:1], fmt)

    # Assert
    assert '\n\t\t"path": "/a.jpg"' in text
    assert json.loads(text) == _RECORDS[:1]


def test_dumps_json_export_pretty_ignores_indent_size_for_tabs() -> None:
    # Arrange
    fmt = JsonExportFormat(pretty=True, indent_style="tab", indent_size=4)

    # Act
    text = dumps_json_export(_RECORDS[:1], fmt)

    # Assert
    assert "    " not in text  # no space-based indentation present


def test_render_record_compact_has_no_newlines() -> None:
    # Arrange
    fmt = JsonExportFormat()

    # Act
    rendered = render_record(_RECORDS[0], fmt)

    # Assert
    assert "\n" not in rendered


def test_json_export_format_normalizes_unknown_indent_style_to_space() -> None:
    # Arrange / Act
    fmt = JsonExportFormat(pretty=True, indent_style="weird")

    # Assert
    assert fmt.indent_style == "space"


def test_json_export_format_clamps_indent_size_to_supported_range() -> None:
    # Arrange / Act
    fmt = JsonExportFormat(pretty=True, indent_size=999)

    # Assert
    assert fmt.indent_size == 8


def test_normalize_indent_style_passes_through_valid_value() -> None:
    # Arrange / Act / Assert
    assert normalize_indent_style("tab") == "tab"


def test_clamp_indent_size_floors_below_minimum() -> None:
    # Arrange / Act / Assert
    assert clamp_indent_size(0) == 1
