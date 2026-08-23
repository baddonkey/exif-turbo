from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

from scripts.fetch_wikidata_entities import (
    WikidataEntityFetchError,
    WikidataEntityFetcher,
)


class _FakeResponse(BytesIO):
    status = 200


class _FakeOpener:
    def __init__(
        self,
        response_factory: Callable[[Request], dict[str, object] | Exception],
    ) -> None:
        self.requests: list[Request] = []
        self._response_factory = response_factory

    def __call__(self, request: Request, *, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        response = self._response_factory(request)
        if isinstance(response, Exception):
            raise response
        return _FakeResponse(json.dumps(response, ensure_ascii=False).encode("utf-8"))


def _write_manifest(path: Path, qids: tuple[str, ...]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_version": 1,
                "created_at": "2026-08-23T00:00:00+00:00",
                "source": {
                    "name": "Wikidata",
                    "dump_uri": "file:///reviewed-wikidata.jsonl",
                    "dump_sha256": "0" * 64,
                    "license_id": "CC0-1.0",
                },
                "concepts": [
                    {"qid": qid, "category": "subject"} for qid in qids
                ],
            }
        ),
        encoding="utf-8",
    )


def _entity(qid: str) -> dict[str, object]:
    labels = {
        "en": {"language": "en", "value": "Forest"},
        "de": {"language": "de", "value": "Wald"},
        "fr": {"language": "fr", "value": "Forêt"},
        "it": {"language": "it", "value": "Foresta"},
    }
    aliases = {
        locale: [{"language": locale, "value": f"{label['value']} alias"}]
        for locale, label in labels.items()
    }
    descriptions = {
        locale: {"language": locale, "value": f"{label['value']} description"}
        for locale, label in labels.items()
    }
    return {
        "id": qid,
        "type": "item",
        "pageid": int(qid[1:]),
        "ns": 0,
        "title": qid,
        "lastrevid": 123456,
        "modified": "2026-08-23T12:34:56Z",
        "labels": labels,
        "aliases": aliases,
        "descriptions": descriptions,
    }


def _requested_qids(request: Request) -> list[str]:
    query = parse_qs(urlparse(request.full_url).query)
    return query["ids"][0].split("|")


def test_wikidata_fetcher_repeated_fetch_emits_deterministic_localized_json_lines(
    tmp_path: Path,
) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ("Q8502", "Q4421"))

    def response_factory(request: Request) -> dict[str, object]:
        qids = _requested_qids(request)
        return {"entities": {qid: _entity(qid) for qid in reversed(qids)}}

    opener = _FakeOpener(response_factory)
    fetcher = WikidataEntityFetcher(opener=opener)
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"

    # Act
    fetcher.fetch(manifest_path, first_path)
    fetcher.fetch(manifest_path, second_path)

    # Assert
    assert first_path.read_bytes() == second_path.read_bytes()
    entities = [json.loads(line) for line in first_path.read_text(encoding="utf-8").splitlines()]
    assert [entity["id"] for entity in entities] == ["Q4421", "Q8502"]
    assert entities[0]["labels"] == _entity("Q4421")["labels"]
    assert entities[0]["aliases"] == _entity("Q4421")["aliases"]
    assert entities[0]["descriptions"] == _entity("Q4421")["descriptions"]
    assert entities[0]["lastrevid"] == 123456
    assert entities[0]["modified"] == "2026-08-23T12:34:56Z"
    query = parse_qs(urlparse(opener.requests[0].full_url).query)
    assert query == {
        "action": ["wbgetentities"],
        "format": ["json"],
        "formatversion": ["2"],
        "ids": ["Q4421|Q8502"],
        "languages": ["en|de|fr|it"],
        "props": ["info|labels|aliases|descriptions"],
    }
    assert opener.requests[0].get_header("User-agent")


def test_wikidata_fetcher_more_than_api_limit_requests_multiple_batches(
    tmp_path: Path,
) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, tuple(f"Q{number}" for number in range(51, 0, -1)))

    def response_factory(request: Request) -> dict[str, object]:
        return {
            "entities": {
                qid: _entity(qid) for qid in _requested_qids(request)
            }
        }

    opener = _FakeOpener(response_factory)

    # Act
    WikidataEntityFetcher(opener=opener).fetch(
        manifest_path, tmp_path / "entities.jsonl"
    )

    # Assert
    assert [_requested_qids(request) for request in opener.requests] == [
        [f"Q{number}" for number in range(1, 51)],
        ["Q51"],
    ]


def test_wikidata_fetcher_include_claims_requests_graph_data(
    tmp_path: Path,
) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ("Q4421",))
    opener = _FakeOpener(
        lambda _request: {
            "entities": {"Q4421": {**_entity("Q4421"), "claims": {}}}
        }
    )

    # Act
    WikidataEntityFetcher(opener=opener, include_claims=True).fetch(
        manifest_path,
        tmp_path / "entities.jsonl",
    )

    # Assert
    query = parse_qs(urlparse(opener.requests[0].full_url).query)
    assert query["props"] == ["info|labels|aliases|descriptions|claims"]


def test_wikidata_fetcher_include_claims_rejects_claims_free_response(
    tmp_path: Path,
) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ("Q4421",))
    opener = _FakeOpener(
        lambda _request: {"entities": {"Q4421": _entity("Q4421")}}
    )

    # Act / Assert
    with pytest.raises(WikidataEntityFetchError, match="claims-free entity"):
        WikidataEntityFetcher(opener=opener, include_claims=True).fetch(
            manifest_path,
            tmp_path / "entities.jsonl",
        )


def test_wikidata_fetcher_excludes_qids_in_existing_export(
    tmp_path: Path,
) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ("Q1", "Q2"))
    existing_path = tmp_path / "existing.jsonl"
    existing_path.write_text(json.dumps(_entity("Q1")) + "\n", encoding="utf-8")
    opener = _FakeOpener(
        lambda request: {
            "entities": {
                qid: _entity(qid) for qid in _requested_qids(request)
            }
        }
    )
    output_path = tmp_path / "missing.jsonl"

    # Act
    WikidataEntityFetcher(opener=opener).fetch(
        manifest_path,
        output_path,
        exclude_entity_paths=(existing_path,),
    )

    # Assert
    assert [_requested_qids(request) for request in opener.requests] == [["Q2"]]
    entities = [
        json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [entity["id"] for entity in entities] == ["Q2"]


def test_wikidata_fetcher_include_claims_refetches_claims_free_entity(
    tmp_path: Path,
) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ("Q1",))
    existing_path = tmp_path / "existing.jsonl"
    existing_path.write_text(json.dumps(_entity("Q1")) + "\n", encoding="utf-8")
    fetched_entity = {**_entity("Q1"), "claims": {}}
    opener = _FakeOpener(
        lambda _request: {"entities": {"Q1": fetched_entity}}
    )
    output_path = tmp_path / "missing.jsonl"

    # Act
    WikidataEntityFetcher(opener=opener, include_claims=True).fetch(
        manifest_path,
        output_path,
        exclude_entity_paths=(existing_path,),
    )

    # Assert
    assert [_requested_qids(request) for request in opener.requests] == [["Q1"]]
    assert json.loads(output_path.read_text(encoding="utf-8"))["claims"] == {}


def test_wikidata_fetcher_http_error_preserves_existing_output(tmp_path: Path) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "entities.jsonl"
    _write_manifest(manifest_path, ("Q1",))
    output_path.write_text("reviewed data\n", encoding="utf-8")
    error = HTTPError("https://example.test/api.php", 503, "unavailable", {}, None)
    opener = _FakeOpener(lambda _request: error)

    # Act / Assert
    with pytest.raises(WikidataEntityFetchError, match="HTTP.*503"):
        WikidataEntityFetcher(opener=opener).fetch(manifest_path, output_path)
    assert output_path.read_text(encoding="utf-8") == "reviewed data\n"


def test_wikidata_fetcher_api_error_raises_fetch_error(tmp_path: Path) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ("Q1",))
    opener = _FakeOpener(
        lambda _request: {
            "error": {"code": "badvalue", "info": "Invalid entity ID"}
        }
    )

    # Act / Assert
    with pytest.raises(WikidataEntityFetchError, match="badvalue.*Invalid entity ID"):
        WikidataEntityFetcher(opener=opener).fetch(
            manifest_path, tmp_path / "entities.jsonl"
        )


def test_wikidata_fetcher_missing_entity_raises_fetch_error(tmp_path: Path) -> None:
    # Arrange
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ("Q1", "Q2"))
    opener = _FakeOpener(lambda _request: {"entities": {"Q1": _entity("Q1")}})

    # Act / Assert
    with pytest.raises(WikidataEntityFetchError, match="missing QIDs: Q2"):
        WikidataEntityFetcher(opener=opener).fetch(
            manifest_path, tmp_path / "entities.jsonl"
        )