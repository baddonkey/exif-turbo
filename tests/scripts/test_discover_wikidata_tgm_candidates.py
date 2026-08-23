from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

from scripts.discover_wikidata_tgm_candidates import (
    WikidataTgmCandidateDiscoverer,
)


class _FakeResponse(BytesIO):
    status = 200


class _FakeOpener:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request, *, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        query = parse_qs(urlparse(request.full_url).query)["query"][0]
        if "wdt:P5160" in query and "VALUES ?item" not in query:
            bindings = (
                [
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q2"},
                        "popularity": {"value": "25"},
                    },
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q3"},
                        "popularity": {"value": "50"},
                    },
                ]
                if "FILTER(STR(?item) >" not in query
                else []
            )
        else:
            bindings = [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q2"},
                    "root": {"value": "http://www.wikidata.org/entity/Q1"},
                }
            ]
        payload = {"results": {"bindings": bindings}}
        return _FakeResponse(json.dumps(payload).encode("utf-8"))


def test_tgm_discoverer_maps_candidates_and_audits_unmapped_qids(
    tmp_path: Path,
) -> None:
    # Arrange
    roots_path = tmp_path / "roots.json"
    roots_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_version": 3,
                "created_at": "2026-08-23T00:00:00+00:00",
                "domains": [
                    {
                        "name": "animals",
                        "category": "subject",
                        "target_count": 1,
                        "max_depth": 5,
                        "root_qids": ["Q1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    opener = _FakeOpener()
    output_path = tmp_path / "tgm-discovery.json"

    # Act
    document = WikidataTgmCandidateDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
    ).discover(
        roots_path,
        output_path,
        page_size=2,
        classification_batch_size=2,
    )

    # Assert
    assert document["complete"] is True
    assert document["concepts"] == [
        {
            "qid": "Q2",
            "category": "subject",
            "domain": "animals",
            "popularity": 25,
            "priority": 1,
        }
    ]
    assert document["unmapped_qids"] == ["Q3"]
    assert len(opener.requests) == 3
    classification_query = parse_qs(
        urlparse(opener.requests[-1].full_url).query
    )["query"][0]
    assert "?item wdt:P171* ?root" in classification_query
    assert json.loads(output_path.read_text(encoding="utf-8")) == document


def test_tgm_discoverer_complete_checkpoint_avoids_network(
    tmp_path: Path,
) -> None:
    # Arrange
    roots_path = tmp_path / "roots.json"
    roots_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_version": 3,
                "created_at": "2026-08-23T00:00:00+00:00",
                "domains": [
                    {
                        "name": "animals",
                        "category": "subject",
                        "target_count": 1,
                        "max_depth": 5,
                        "root_qids": ["Q1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    opener = _FakeOpener()
    output_path = tmp_path / "tgm-discovery.json"
    discoverer = WikidataTgmCandidateDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
    )
    first = discoverer.discover(
        roots_path,
        output_path,
        page_size=2,
        classification_batch_size=2,
    )
    opener.requests.clear()

    # Act
    second = discoverer.discover(
        roots_path,
        output_path,
        page_size=2,
        classification_batch_size=2,
    )

    # Assert
    assert second == first
    assert opener.requests == []