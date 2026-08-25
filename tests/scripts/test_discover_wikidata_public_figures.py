from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

from scripts.discover_wikidata_public_figures import (
    WikidataPublicFigureDiscoverer,
)


class _FakeResponse(BytesIO):
    status = 200


class _FakeOpener:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request, *, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        query = parse_qs(urlparse(request.full_url).query)["query"][0]
        if "SELECT DISTINCT ?classification" in query:
            root = "Q116" if "wd:Q116" in query else "Q82955"
            payload = {
                "results": {
                    "bindings": [
                        {
                            "classification": {
                                "value": f"http://www.wikidata.org/entity/{root}"
                            }
                        }
                    ]
                }
            }
            return _FakeResponse(json.dumps(payload).encode("utf-8"))
        if "wikibase:sitelinks ?candidateLinks" in query:
            rows = [("Q2", 75), ("Q1", 120)]
            if "?item wdt:P39 ?classification" in query:
                rows = [("Q3", 90), ("Q2", 80)]
            payload = {
                "results": {
                    "bindings": [
                        {
                            "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
                            "popularity": {"value": str(popularity)},
                        }
                        for qid, popularity in rows
                    ]
                }
            }
            return _FakeResponse(json.dumps(payload).encode("utf-8"))
        rows = [
            ("Q2", 75, "example-b.jpg"),
            ("Q1", 120, "example-a.jpg"),
        ]
        if "VALUES ?item { wd:Q3 wd:Q2 }" in query:
            rows = [
                ("Q3", 90, "example-c.jpg"),
                ("Q2", 80, "example-b-new.jpg"),
            ]
        payload = {
            "results": {
                "bindings": [
                    {
                        "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
                        "popularity": {"value": str(popularity)},
                        "referenceImage": {
                            "value": f"https://commons.wikimedia.org/{image}"
                        },
                    }
                    for qid, popularity, image in rows
                ]
            }
        }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))


def test_public_figure_discoverer_merges_groups_into_ranked_fetch_ready_manifest(
    tmp_path: Path,
) -> None:
    # Arrange
    criteria_path = tmp_path / "criteria.json"
    criteria_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "identity_snapshot_version": 1,
                "created_at": "2026-08-24T00:00:00+00:00",
                "earliest_life_date": "1826-01-01T00:00:00Z",
                "min_sitelinks": 10,
                "required_locales": ["en", "de", "fr", "it"],
                "groups": [
                    {
                        "name": "politicians",
                        "target_count": 5000,
                        "occupation_root_qids": ["Q82955"],
                    },
                    {
                        "name": "monarchs",
                        "target_count": 500,
                        "position_root_qids": ["Q116"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    opener = _FakeOpener()
    output_path = tmp_path / "public-figures.json"

    # Act
    document = WikidataPublicFigureDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
        request_interval_seconds=0,
    ).discover(criteria_path, output_path)

    # Assert
    assert [concept["qid"] for concept in document["concepts"]] == [
        "Q1",
        "Q3",
        "Q2",
    ]
    assert document["concepts"][2]["identity_types"] == [
        "politicians",
        "monarchs",
    ]
    assert document["concepts"][2]["popularity"] == 80
    assert [concept["priority"] for concept in document["concepts"]] == [1, 2, 3]
    assert document["group_counts"] == {"politicians": 2, "monarchs": 2}
    queries = [
        parse_qs(urlparse(request.full_url).query)["query"][0]
        for request in opener.requests
    ]
    assert "VALUES ?classification { wd:Q82955 }" in queries[0]
    assert "?item wdt:P106 ?classification" in queries[0]
    assert "VALUES ?item { wd:Q2 wd:Q1 }" in queries[1]
    assert "?classification wdt:P279* ?classificationRoot" in queries[2]
    assert "VALUES ?classification { wd:Q116 }" in queries[3]
    assert "?item wdt:P39 ?classification" in queries[3]
    assert "VALUES ?item { wd:Q3 wd:Q2 }" in queries[4]
    assert "?classification wdt:P279* ?classificationRoot" in queries[5]
    assert "LIMIT 20000" in queries[0]
    assert "LIMIT 2000" in queries[3]
    assert all("?item wdt:P31 wd:Q5" in query for query in (queries[1], queries[4]))
    assert len(opener.requests) == 6
    assert json.loads(output_path.read_text(encoding="utf-8")) == document


def test_public_figure_discoverer_direct_matches_fill_target_skips_subclasses(
    tmp_path: Path,
) -> None:
    # Arrange
    criteria_path = tmp_path / "criteria.json"
    criteria_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "identity_snapshot_version": 1,
                "created_at": "2026-08-24T00:00:00+00:00",
                "earliest_life_date": "1826-01-01T00:00:00Z",
                "min_sitelinks": 10,
                "required_locales": ["en", "de", "fr", "it"],
                "groups": [
                    {
                        "name": "politicians",
                        "target_count": 2,
                        "occupation_root_qids": ["Q82955"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    opener = _FakeOpener()

    # Act
    document = WikidataPublicFigureDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
        request_interval_seconds=0,
    ).discover(criteria_path, tmp_path / "public-figures.json")

    # Assert
    assert document["group_counts"] == {"politicians": 2}
    assert len(opener.requests) == 2


def test_public_figure_discoverer_checkpoint_resumes_completed_group(
    tmp_path: Path,
) -> None:
    # Arrange
    criteria = {
        "schema_version": 1,
        "identity_snapshot_version": 1,
        "created_at": "2026-08-24T00:00:00+00:00",
        "earliest_life_date": "1826-01-01T00:00:00Z",
        "min_sitelinks": 10,
        "required_locales": ["en", "de", "fr", "it"],
        "groups": [
            {
                "name": "politicians",
                "target_count": 2,
                "occupation_root_qids": ["Q82955"],
            }
        ],
    }
    criteria_path = tmp_path / "criteria.json"
    criteria_path.write_text(json.dumps(criteria), encoding="utf-8")
    output_path = tmp_path / "public-figures.json"
    checkpoint_path = output_path.with_suffix(".checkpoint.json")
    checkpoint_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "criteria": criteria,
                "groups": {
                    "politicians": [
                        ["Q1", 120, "https://commons.wikimedia.org/example-a.jpg"],
                        ["Q2", 75, "https://commons.wikimedia.org/example-b.jpg"],
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    opener = _FakeOpener()

    # Act
    document = WikidataPublicFigureDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
        request_interval_seconds=0,
    ).discover(criteria_path, output_path)

    # Assert
    assert document["group_counts"] == {"politicians": 2}
    assert opener.requests == []
    assert not checkpoint_path.exists()


def test_public_figure_discoverer_queries_direct_roots_independently(
    tmp_path: Path,
) -> None:
    # Arrange
    criteria_path = tmp_path / "criteria.json"
    criteria_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "identity_snapshot_version": 1,
                "created_at": "2026-08-24T00:00:00+00:00",
                "earliest_life_date": "1826-01-01T00:00:00Z",
                "min_sitelinks": 10,
                "required_locales": ["en", "de", "fr", "it"],
                "groups": [
                    {
                        "name": "artists_writers",
                        "target_count": 2,
                        "occupation_root_qids": ["Q483501", "Q36180"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    opener = _FakeOpener()

    # Act
    WikidataPublicFigureDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
        request_interval_seconds=0,
    ).discover(criteria_path, tmp_path / "public-figures.json")

    # Assert
    queries = [
        parse_qs(urlparse(request.full_url).query)["query"][0]
        for request in opener.requests
    ]
    candidate_queries = [
        query for query in queries if "wikibase:sitelinks ?candidateLinks" in query
    ]
    assert len(candidate_queries) == 2
    assert "VALUES ?classification { wd:Q483501 }" in candidate_queries[0]
    assert "VALUES ?classification { wd:Q36180 }" in candidate_queries[1]


def test_public_figure_discoverer_rate_limit_honors_retry_after() -> None:
    # Arrange
    payload = json.dumps({"results": {"bindings": []}}).encode("utf-8")
    outcomes: list[HTTPError | _FakeResponse] = [
        HTTPError(
            "https://example.test/sparql",
            429,
            "rate limited",
            {"Retry-After": "7"},
            None,
        ),
        _FakeResponse(payload),
    ]
    sleeps: list[float] = []
    current_time = 0.0

    def opener(request: Request, *, timeout: float) -> _FakeResponse:
        outcome = outcomes.pop(0)
        if isinstance(outcome, HTTPError):
            raise outcome
        return outcome

    def sleep(seconds: float) -> None:
        nonlocal current_time
        sleeps.append(seconds)
        current_time += seconds

    discoverer = WikidataPublicFigureDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
        sleeper=sleep,
        monotonic=lambda: current_time,
        jitter=lambda: 0.0,
    )

    # Act
    bindings = discoverer._request_bindings("SELECT * WHERE {}")

    # Assert
    assert bindings == []
    assert sleeps == [7.0]


def test_public_figure_discoverer_paces_successive_requests() -> None:
    # Arrange
    payload = json.dumps({"results": {"bindings": []}}).encode("utf-8")
    sleeps: list[float] = []
    current_time = 0.0

    def opener(request: Request, *, timeout: float) -> _FakeResponse:
        return _FakeResponse(payload)

    def sleep(seconds: float) -> None:
        nonlocal current_time
        sleeps.append(seconds)
        current_time += seconds

    discoverer = WikidataPublicFigureDiscoverer(
        endpoint="https://example.test/sparql",
        opener=opener,
        sleeper=sleep,
        monotonic=lambda: current_time,
        jitter=lambda: 0.0,
    )

    # Act
    discoverer._request_bindings("SELECT * WHERE {}")
    discoverer._request_bindings("SELECT * WHERE {}")

    # Assert
    assert sleeps == [2.0]