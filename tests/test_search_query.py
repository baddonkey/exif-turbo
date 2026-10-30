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
    ['tags:=forest', 'tags:="forest, "', 'description:="'],
)
def test_parse_search_query_malformed_structured_expression_raises(query: str) -> None:
    with pytest.raises(SearchQueryParseError):
        parse_search_query(query)