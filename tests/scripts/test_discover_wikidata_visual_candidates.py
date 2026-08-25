from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

from scripts.discover_wikidata_visual_candidates import (
    WikidataVisualCandidateDiscoverer,
)


class _FakeResponse(BytesIO):
    status = 200


class _FakeOpener:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request, *, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        payload = {
            "results": {
                "bindings": [
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q2"},
                        "popularity": {"value": "25"},
                    },
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q1"},
                        "popularity": {"value": "50"},
                    },
                ]
            }
        }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))


def test_wikidata_visual_discoverer_ranks_multilingual_domain_candidates(
    tmp_path: Path,
) -> None:
    # Arrange
    roots_path = tmp_path / "roots.json"
    roots_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_version": 2,
                "created_at": "2026-08-23T00:00:00+00:00",
                "target_count": 2,
                "domains": [
                    {
                        "name": "objects",
                        "category": "subject",
                        "target_count": 2,
                        "max_depth": 2,
                        "root_qids": ["Q1"],
                        "traversal_properties": ["P279", "P171"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    opener = _FakeOpener()
    output_path = tmp_path / "discovery.json"

    # Act
    document = WikidataVisualCandidateDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
    ).discover(roots_path, output_path, candidate_multiplier=2)

    # Assert
    assert [concept["qid"] for concept in document["concepts"]] == ["Q1", "Q2"]
    assert [concept["priority"] for concept in document["concepts"]] == [1, 2]
    assert document["completed_domains"] == ["objects"]
    query = parse_qs(urlparse(opener.requests[0].full_url).query)["query"][0]
    assert "VALUES ?traversalProperty { wdt:P279 wdt:P171 }" in query
    assert "?item ?traversalProperty ?parent" in query
    assert 'FILTER(REGEX(STR(?item), "/Q[1-9][0-9]*$"))' in query
    assert (
        'ORDER BY DESC(?popularity) xsd:integer(STRAFTER(STR(?item), "/Q"))'
        in query
    )
    assert "LIMIT 4" in query
    assert len(opener.requests) == 2
    assert json.loads(output_path.read_text(encoding="utf-8")) == document


def test_wikidata_visual_discoverer_matching_checkpoint_skips_completed_domain(
    tmp_path: Path,
) -> None:
    # Arrange
    roots_path = tmp_path / "roots.json"
    roots_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_version": 2,
                "created_at": "2026-08-23T00:00:00+00:00",
                "target_count": 1,
                "domains": [
                    {
                        "name": "objects",
                        "category": "subject",
                        "target_count": 1,
                        "max_depth": 1,
                        "root_qids": ["Q1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    opener = _FakeOpener()
    output_path = tmp_path / "discovery.json"
    discoverer = WikidataVisualCandidateDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
    )
    first = discoverer.discover(roots_path, output_path, candidate_multiplier=1)
    opener.requests.clear()

    # Act
    second = discoverer.discover(roots_path, output_path, candidate_multiplier=1)

    # Assert
    assert second == first
    assert opener.requests == []