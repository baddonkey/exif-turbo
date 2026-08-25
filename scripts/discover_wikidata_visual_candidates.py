#!/usr/bin/env python3
"""Discover recognizable visual-concept candidates from Wikidata Query Service."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_DEFAULT_ENDPOINT = "https://query.wikidata.org/sparql"
_USER_AGENT = (
    "exif-turbo-wikidata-curator/1.0 "
    "(https://github.com/baddonkey/exif-turbo; build-time curator script)"
)
_QID_PATTERN = re.compile(r"^Q[1-9]\d*$")
_PROPERTY_ID_PATTERN = re.compile(r"^P[1-9]\d*$")
_ENTITY_PREFIX = "http://www.wikidata.org/entity/"
_TIMEOUT_SECONDS = 180.0
_FRONTIER_BATCH_SIZE = 400
_MAX_REQUEST_ATTEMPTS = 4


class WikidataDiscoveryError(RuntimeError):
    """The visual-candidate query or response is invalid."""


class _HttpResponse(Protocol):
    status: int

    def read(self) -> bytes: ...

    def __enter__(self) -> _HttpResponse: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool | None: ...


class _UrlOpener(Protocol):
    def __call__(
        self, request: Request, *, timeout: float
    ) -> _HttpResponse: ...


class WikidataVisualCandidateDiscoverer:
    """Rank multilingual descendants by public prominence within each domain."""

    def __init__(
        self,
        *,
        endpoint: str = _DEFAULT_ENDPOINT,
        opener: _UrlOpener | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._opener = opener or urlopen

    def discover(
        self,
        roots_path: Path,
        output_path: Path,
        *,
        candidate_multiplier: int = 3,
    ) -> dict[str, Any]:
        if candidate_multiplier < 1:
            raise WikidataDiscoveryError("candidate multiplier must be positive")
        roots = json.loads(roots_path.read_text(encoding="utf-8"))
        if not isinstance(roots, dict) or roots.get("schema_version") != 1:
            raise WikidataDiscoveryError("unsupported visual-domain roots schema")
        domains = roots.get("domains")
        if not isinstance(domains, list) or not domains:
            raise WikidataDiscoveryError("visual-domain roots must contain domains")

        roots_sha256 = hashlib.sha256(roots_path.read_bytes()).hexdigest()
        concepts: list[dict[str, str | int]] = []
        completed_domains: list[str] = []
        if output_path.exists():
            checkpoint = json.loads(output_path.read_text(encoding="utf-8"))
            if (
                not isinstance(checkpoint, dict)
                or checkpoint.get("schema_version") != 1
                or checkpoint.get("roots_sha256") != roots_sha256
                or checkpoint.get("candidate_multiplier") != candidate_multiplier
                or not isinstance(checkpoint.get("concepts"), list)
                or not isinstance(checkpoint.get("completed_domains"), list)
            ):
                raise WikidataDiscoveryError(
                    "existing discovery checkpoint does not match current inputs"
                )
            concepts = list(checkpoint["concepts"])
            completed_domains = list(checkpoint["completed_domains"])
        assigned = {
            str(concept["qid"])
            for concept in concepts
            if isinstance(concept, dict) and isinstance(concept.get("qid"), str)
        }
        for domain in domains:
            if not isinstance(domain, dict):
                raise WikidataDiscoveryError("domain entries must be objects")
            name = str(domain.get("name", ""))
            category = str(domain.get("category", ""))
            target_count = domain.get("target_count")
            max_depth = domain.get("max_depth")
            root_qids = domain.get("root_qids")
            traversal_properties = domain.get("traversal_properties", ["P279"])
            if (
                not name
                or category not in ("subject", "genre_format")
                or isinstance(target_count, bool)
                or not isinstance(target_count, int)
                or target_count < 1
                or isinstance(max_depth, bool)
                or not isinstance(max_depth, int)
                or max_depth < 0
                or not isinstance(root_qids, list)
                or not root_qids
                or not all(
                    isinstance(qid, str) and _QID_PATTERN.fullmatch(qid)
                    for qid in root_qids
                )
                or not isinstance(traversal_properties, list)
                or not traversal_properties
                or not all(
                    isinstance(property_id, str)
                    and _PROPERTY_ID_PATTERN.fullmatch(property_id)
                    for property_id in traversal_properties
                )
                or len(traversal_properties) != len(set(traversal_properties))
            ):
                raise WikidataDiscoveryError(f"invalid domain configuration: {name}")
            if name in completed_domains:
                print(f"Using checkpoint for {name}", flush=True)
                continue
            limit = target_count * candidate_multiplier
            print(
                f"Discovering {name}: depth={max_depth}, candidate_limit={limit}",
                flush=True,
            )
            rows = self._query_domain(
                tuple(root_qids),
                limit=limit,
                max_depth=max_depth,
                traversal_properties=tuple(traversal_properties),
            )
            rank = 0
            for qid, popularity in rows:
                if qid in assigned:
                    continue
                assigned.add(qid)
                rank += 1
                concepts.append(
                    {
                        "qid": qid,
                        "category": category,
                        "domain": name,
                        "popularity": popularity,
                        "priority": rank,
                    }
                )
            print(
                f"Discovered {name}: {rank} unique candidates",
                flush=True,
            )
            completed_domains.append(name)
            self._write_json(
                output_path,
                self._document(
                    roots,
                    roots_sha256,
                    candidate_multiplier,
                    concepts,
                    completed_domains,
                ),
            )

        document = self._document(
            roots,
            roots_sha256,
            candidate_multiplier,
            concepts,
            completed_domains,
        )
        self._write_json(output_path, document)
        return document

    def _document(
        self,
        roots: dict[str, Any],
        roots_sha256: str,
        candidate_multiplier: int,
        concepts: list[dict[str, str | int]],
        completed_domains: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "snapshot_version": int(roots["snapshot_version"]),
            "created_at": str(roots["created_at"]),
            "endpoint": self._endpoint,
            "roots_sha256": roots_sha256,
            "candidate_multiplier": candidate_multiplier,
            "completed_domains": completed_domains,
            "concepts": concepts,
        }

    def _query_domain(
        self,
        root_qids: tuple[str, ...],
        *,
        limit: int,
        max_depth: int,
        traversal_properties: tuple[str, ...],
    ) -> list[tuple[str, int]]:
        candidates = {qid: 1_000_000_000 for qid in root_qids}
        frontier = tuple(sorted(root_qids, key=lambda qid: int(qid[1:])))
        for _depth in range(max_depth):
            children: dict[str, int] = {}
            for offset in range(0, len(frontier), _FRONTIER_BATCH_SIZE):
                for qid, popularity in self._query_direct_children(
                    frontier[offset : offset + _FRONTIER_BATCH_SIZE],
                    traversal_properties,
                    limit,
                ):
                    children[qid] = max(popularity, children.get(qid, -1))
                    candidates[qid] = max(popularity, candidates.get(qid, -1))
            ranked_children = sorted(
                children.items(),
                key=lambda row: (-row[1], int(row[0][1:])),
            )[:limit]
            frontier = tuple(qid for qid, _popularity in ranked_children)
            if not frontier:
                break
        return sorted(
            candidates.items(),
            key=lambda row: (-row[1], int(row[0][1:])),
        )[:limit]

    def _query_direct_children(
        self,
        parent_qids: tuple[str, ...],
        traversal_properties: tuple[str, ...],
        limit: int,
    ) -> list[tuple[str, int]]:
        parents = " ".join(f"wd:{qid}" for qid in parent_qids)
        properties = " ".join(
            f"wdt:{property_id}" for property_id in traversal_properties
        )
        query = f"""
SELECT ?item (MAX(?links) AS ?popularity) WHERE {{
  VALUES ?parent {{ {parents} }}
      VALUES ?traversalProperty {{ {properties} }}
      ?item ?traversalProperty ?parent.
    FILTER(REGEX(STR(?item), "/Q[1-9][0-9]*$"))
  OPTIONAL {{ ?item wikibase:sitelinks ?links. }}
}}
GROUP BY ?item
ORDER BY DESC(?popularity) xsd:integer(STRAFTER(STR(?item), "/Q"))
LIMIT {limit}
""".strip()
        url = f"{self._endpoint}?{urlencode({'query': query, 'format': 'json'})}"
        request = Request(
            url,
            headers={"Accept": "application/sparql-results+json", "User-Agent": _USER_AGENT},
        )
        payload: bytes | None = None
        last_error: Exception | None = None
        for attempt in range(1, _MAX_REQUEST_ATTEMPTS + 1):
            try:
                with self._opener(request, timeout=_TIMEOUT_SECONDS) as response:
                    if not 200 <= response.status < 300:
                        raise WikidataDiscoveryError(
                            f"Wikidata Query Service HTTP status {response.status}"
                        )
                    payload = response.read()
                break
            except HTTPError as exc:
                last_error = exc
                if exc.code != 429 and not 500 <= exc.code < 600:
                    break
            except (URLError, OSError) as exc:
                last_error = exc
            if attempt < _MAX_REQUEST_ATTEMPTS:
                print(
                    f"Retrying Wikidata query after attempt {attempt}: {last_error}",
                    flush=True,
                )
        if payload is None:
            raise WikidataDiscoveryError(
                f"Wikidata Query Service request failed after "
                f"{_MAX_REQUEST_ATTEMPTS} attempts: {last_error}"
            ) from last_error
        try:
            document = json.loads(payload.decode("utf-8"))
            bindings = document["results"]["bindings"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise WikidataDiscoveryError(
                "Wikidata Query Service returned invalid JSON results"
            ) from exc
        if not isinstance(bindings, list):
            raise WikidataDiscoveryError("Wikidata query bindings must be an array")
        rows: list[tuple[str, int]] = []
        for binding in bindings:
            try:
                item_uri = binding["item"]["value"]
                popularity_value = binding.get("popularity", {}).get("value", 0)
                popularity = int(popularity_value)
            except (KeyError, TypeError, ValueError) as exc:
                raise WikidataDiscoveryError("invalid candidate query row") from exc
            qid = str(item_uri).removeprefix(_ENTITY_PREFIX)
            if not _QID_PATTERN.fullmatch(qid) or popularity < 0:
                raise WikidataDiscoveryError(
                    f"invalid candidate QID or popularity: {item_uri!r}, {popularity}"
                )
            rows.append((qid, popularity))
        rows.sort(key=lambda row: (-row[1], int(row[0][1:])))
        return rows

    @staticmethod
    def _write_json(path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--endpoint", default=_DEFAULT_ENDPOINT)
    parser.add_argument("--candidate-multiplier", type=int, default=3)
    arguments = parser.parse_args()
    WikidataVisualCandidateDiscoverer(endpoint=arguments.endpoint).discover(
        arguments.roots,
        arguments.output,
        candidate_multiplier=arguments.candidate_multiplier,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())