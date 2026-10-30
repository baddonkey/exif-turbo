from __future__ import annotations

import pytest

from exif_turbo.search_query import SearchQueryParseError, parse_search_query


def test_parse_search_query_mixed_filter_preserves_ordinary_fts_text() -> None:
    parsed = parse_search_query('forest tags:="wildlife, deer" description:="sunset"')

    assert parsed.text == "forest"
    assert [(item.kind, item.values) for item in parsed.filters] == [
        ("tags", ("wildlife", "deer")),
        ("description", ("sunset",)),
    ]


def test_parse_search_query_explicit_and_between_filters_is_consumed() -> None:
    parsed = parse_search_query('tags:="Huba" AND tags:="Bronko"')

    assert parsed.text == ""
    assert [(item.kind, item.values) for item in parsed.filters] == [
        ("tags", ("Huba",)),
        ("tags", ("Bronko",)),
    ]


def test_parse_search_query_text_not_filter_is_structured() -> None:
    parsed = parse_search_query('tags:="Huba" text-not:="huba"')

    assert parsed.text == ""
    assert [(item.kind, item.values) for item in parsed.filters] == [
        ("tags", ("Huba",)),
        ("text-not", ("huba",)),
    ]


def test_parse_search_query_text_filter_is_structured() -> None:
    parsed = parse_search_query('text:="wildlife"')

    assert parsed.text == ""
    assert [(item.kind, item.values) for item in parsed.filters] == [
        ("text", ("wildlife",)),
    ]


def test_parse_search_query_or_between_structured_filters_is_consumed() -> None:
    parsed = parse_search_query('tags:="cat, playing" OR text:="green"')

    assert parsed.text == ""
    assert [(item.kind, item.values) for item in parsed.filters] == [
        ("tags", ("cat", "playing")),
        ("text", ("green",)),
    ]
    assert parsed.filter_operators == ("OR",)


def test_parse_search_query_plain_fts_and_remains_unchanged() -> None:
    query = "forest AND camera"

    parsed = parse_search_query(query)

    assert parsed.text == query
    assert parsed.filters == ()


def test_parse_search_query_and_inside_quoted_phrase_is_preserved_with_filter() -> None:
    parsed = parse_search_query('description:="sun" AND "rock AND roll"')

    assert parsed.text == '"rock AND roll"'
    assert len(parsed.filters) == 1


def test_parse_search_query_operator_inside_quoted_phrase_remains_fts_text() -> None:
    query = '"look for tags:=\"birds\"" forest'

    parsed = parse_search_query(query)

    assert parsed.text == query
    assert parsed.filters == ()


def test_parse_search_query_doubled_quotes_keep_operator_inside_fts_phrase() -> None:
    query = '"look ""inside tags:=birds"" phrase"'

    parsed = parse_search_query(query)

    assert parsed.text == query
    assert parsed.filters == ()


def test_parse_search_query_tag_values_are_trimmed_normalized_and_deduplicated() -> None:
    parsed = parse_search_query('tags:=" Café, Café, BIRD, bird "')

    assert parsed.filters[0].values == ("Café", "BIRD")


def test_parse_search_query_escaped_quote_is_unescaped() -> None:
    parsed = parse_search_query('description:="a \\"quoted\\" phrase"')

    assert parsed.filters[0].values == ('a "quoted" phrase',)


def test_parse_search_query_doubled_quote_is_unescaped() -> None:
    parsed = parse_search_query('description:="a ""quoted"" phrase"')

    assert parsed.filters[0].values == ('a "quoted" phrase',)


@pytest.mark.parametrize(
    "query",
    ['tags:=forest', 'tags:="forest, "', 'description:="', 'text-not:=" "'],
)
def test_parse_search_query_malformed_structured_expression_raises(query: str) -> None:
    with pytest.raises(SearchQueryParseError):
        parse_search_query(query)