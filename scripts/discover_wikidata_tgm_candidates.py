#!/usr/bin/env python3
"""Discover and domain-classify Wikidata concepts linked to LCTGM."""
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
_ENTITY_PREFIX = "http://www.wikidata.org/entity/"
_QID_PATTERN = re.compile(r"^Q[1-9]\d*$")
_MAX_REQUEST_ATTEMPTS = 4
_TIMEOUT_SECONDS = 180.0


class WikidataTgmDiscoveryError(RuntimeError):
    """The TGM candidate query, checkpoint, or response is invalid."""


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
    def __call__(self, request: Request, *, timeout: float) -> _HttpResponse: ...


class WikidataTgmCandidateDiscoverer:
    """Enumerate P5160 concepts and map them onto configured visual domains."""

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
        page_size: int = 500,
        classification_batch_size: int = 50,
    ) -> dict[str, Any]:
        if page_size < 1 or classification_batch_size < 1:
            raise WikidataTgmDiscoveryError("batch sizes must be positive")
        roots = json.loads(roots_path.read_text(encoding="utf-8"))
        domains = roots.get("domains") if isinstance(roots, dict) else None
        if roots.get("schema_version") != 1 or not isinstance(domains, list):
            raise WikidataTgmDiscoveryError("unsupported visual-domain roots schema")
        domain_by_root: dict[str, tuple[int, str, str]] = {}
        for index, domain in enumerate(domains):
            if not isinstance(domain, dict):
                raise WikidataTgmDiscoveryError("domain entries must be objects")
            name = domain.get("name")
            category = domain.get("category")
            root_qids = domain.get("root_qids")
            if (
                not isinstance(name, str)
                or category not in ("subject", "genre_format")
                or not isinstance(root_qids, list)
                or not all(
                    isinstance(qid, str) and _QID_PATTERN.fullmatch(qid)
                    for qid in root_qids
                )
            ):
                raise WikidataTgmDiscoveryError("invalid domain configuration")
            for root_qid in root_qids:
                domain_by_root.setdefault(root_qid, (index, name, category))

        roots_sha256 = hashlib.sha256(roots_path.read_bytes()).hexdigest()
        checkpoint = self._load_checkpoint(
            output_path,
            roots_sha256,
            page_size,
            classification_batch_size,
        )
        items = checkpoint["items"]
        if not checkpoint["enumeration_complete"]:
            cursor = str(checkpoint["cursor"])
            while True:
                page = self._query_tgm_page(cursor, page_size)
                for qid, popularity in page:
                    items[qid] = max(popularity, int(items.get(qid, 0)))
                if len(page) < page_size:
                    checkpoint["enumeration_complete"] = True
                    checkpoint["cursor"] = ""
                    break
                cursor = page[-1][0]
                checkpoint["cursor"] = cursor
                self._write_checkpoint(output_path, checkpoint)
            self._write_checkpoint(output_path, checkpoint)

        ordered_qids = sorted(items, key=lambda qid: int(qid[1:]))
        assignments = checkpoint["assignments"]
        offset = int(checkpoint["classification_offset"])
        while offset < len(ordered_qids):
            batch = tuple(ordered_qids[offset : offset + classification_batch_size])
            matches = self._query_domain_matches(batch, tuple(domain_by_root))
            for qid in batch:
                candidates = [
                    domain_by_root[root_qid]
                    for root_qid in matches.get(qid, ())
                    if root_qid in domain_by_root
                ]
                if candidates:
                    _index, domain, category = min(candidates)
                    assignments[qid] = {"domain": domain, "category": category}
            offset += len(batch)
            checkpoint["classification_offset"] = offset
            self._write_checkpoint(output_path, checkpoint)

        concepts: list[dict[str, str | int]] = []
        priority_by_domain: dict[str, int] = {}
        ranked_qids = sorted(
            assignments,
            key=lambda qid: (-int(items[qid]), int(qid[1:])),
        )
        for qid in ranked_qids:
            assignment = assignments[qid]
            domain = str(assignment["domain"])
            priority_by_domain[domain] = priority_by_domain.get(domain, 0) + 1
            concepts.append(
                {
                    "qid": qid,
                    "category": str(assignment["category"]),
                    "domain": domain,
                    "popularity": int(items[qid]),
                    "priority": priority_by_domain[domain],
                }
            )
        mapped = set(assignments)
        document = self._document(
            roots,
            roots_sha256,
            page_size,
            classification_batch_size,
            items,
            assignments,
            concepts,
            [qid for qid in ordered_qids if qid not in mapped],
        )
        document["complete"] = True
        self._write_json(output_path, document)
        return document

    def _load_checkpoint(
        self,
        output_path: Path,
        roots_sha256: str,
        page_size: int,
        classification_batch_size: int,
    ) -> dict[str, Any]:
        if not output_path.exists():
            return {
                "schema_version": 1,
                "endpoint": self._endpoint,
                "roots_sha256": roots_sha256,
                "property_id": "P5160",
                "page_size": page_size,
                "classification_batch_size": classification_batch_size,
                "cursor": "",
                "enumeration_complete": False,
                "classification_offset": 0,
                "items": {},
                "assignments": {},
            }
        document = json.loads(output_path.read_text(encoding="utf-8"))
        expected = {
            "schema_version": 1,
            "endpoint": self._endpoint,
            "roots_sha256": roots_sha256,
            "property_id": "P5160",
            "page_size": page_size,
            "classification_batch_size": classification_batch_size,
        }
        if not isinstance(document, dict) or any(
            document.get(key) != value for key, value in expected.items()
        ):
            raise WikidataTgmDiscoveryError(
                "existing TGM discovery checkpoint does not match current inputs"
            )
        if document.get("complete"):
            return document
        if not isinstance(document.get("items"), dict) or not isinstance(
            document.get("assignments"), dict
        ):
            raise WikidataTgmDiscoveryError("invalid TGM discovery checkpoint")
        return document

    def _query_tgm_page(self, cursor: str, limit: int) -> list[tuple[str, int]]:
        cursor_filter = (
            f"FILTER(STR(?item) > {json.dumps(_ENTITY_PREFIX + cursor)})"
            if cursor
            else ""
        )
        query = f"""
SELECT ?item (MAX(?links) AS ?popularity) WHERE {{
  ?item wdt:P5160 ?tgmId.
  {cursor_filter}
  FILTER(REGEX(STR(?item), "/Q[1-9][0-9]*$"))
  OPTIONAL {{ ?item wikibase:sitelinks ?links. }}
}}
GROUP BY ?item
ORDER BY STR(?item)
LIMIT {limit}
""".strip()
        bindings = self._request_bindings(query)
        rows = [
            (
                self._qid_from_binding(binding, "item"),
                int(binding.get("popularity", {}).get("value", 0)),
            )
            for binding in bindings
        ]
        if any(popularity < 0 for _qid, popularity in rows):
            raise WikidataTgmDiscoveryError("invalid TGM popularity")
        return rows

    def _query_domain_matches(
        self,
        qids: tuple[str, ...],
        root_qids: tuple[str, ...],
    ) -> dict[str, set[str]]:
        items = " ".join(f"wd:{qid}" for qid in qids)
        roots = " ".join(f"wd:{qid}" for qid in root_qids)
        query = f"""
SELECT DISTINCT ?item ?root WHERE {{
  VALUES ?item {{ {items} }}
  VALUES ?root {{ {roots} }}
  {{ ?item wdt:P279* ?root. }}
  UNION
  {{ ?item wdt:P31/wdt:P279* ?root. }}
    UNION
    {{ ?item wdt:P171* ?root. }}
}}
""".strip()
        matches: dict[str, set[str]] = {}
        for binding in self._request_bindings(query):
            qid = self._qid_from_binding(binding, "item")
            root_qid = self._qid_from_binding(binding, "root")
            if qid not in qids or root_qid not in root_qids:
                raise WikidataTgmDiscoveryError("unexpected domain query row")
            matches.setdefault(qid, set()).add(root_qid)
        return matches

    def _request_bindings(self, query: str) -> list[dict[str, Any]]:
        url = f"{self._endpoint}?{urlencode({'query': query, 'format': 'json'})}"
        request = Request(
            url,
            headers={"Accept": "application/sparql-results+json", "User-Agent": _USER_AGENT},
        )
        payload: bytes | None = None
        last_error: Exception | None = None
        for _attempt in range(_MAX_REQUEST_ATTEMPTS):
            try:
                with self._opener(request, timeout=_TIMEOUT_SECONDS) as response:
                    if not 200 <= response.status < 300:
                        raise WikidataTgmDiscoveryError(
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
        if payload is None:
            raise WikidataTgmDiscoveryError(
                f"Wikidata Query Service request failed: {last_error}"
            ) from last_error
        try:
            document = json.loads(payload.decode("utf-8"))
            bindings = document["results"]["bindings"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise WikidataTgmDiscoveryError(
                "Wikidata Query Service returned invalid JSON results"
            ) from exc
        if not isinstance(bindings, list) or not all(
            isinstance(binding, dict) for binding in bindings
        ):
            raise WikidataTgmDiscoveryError("invalid Wikidata query bindings")
        return bindings

    @staticmethod
    def _qid_from_binding(binding: dict[str, Any], key: str) -> str:
        try:
            uri = binding[key]["value"]
        except (KeyError, TypeError) as exc:
            raise WikidataTgmDiscoveryError("invalid Wikidata query row") from exc
        qid = str(uri).removeprefix(_ENTITY_PREFIX)
        if not _QID_PATTERN.fullmatch(qid):
            raise WikidataTgmDiscoveryError(f"invalid Wikidata entity URI: {uri}")
        return qid

    def _document(
        self,
        roots: dict[str, Any],
        roots_sha256: str,
        page_size: int,
        classification_batch_size: int,
        items: dict[str, int],
        assignments: dict[str, dict[str, str]],
        concepts: list[dict[str, str | int]],
        unmapped_qids: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "snapshot_version": int(roots["snapshot_version"]),
            "created_at": str(roots["created_at"]),
            "endpoint": self._endpoint,
            "roots_sha256": roots_sha256,
            "property_id": "P5160",
            "page_size": page_size,
            "classification_batch_size": classification_batch_size,
            "cursor": "",
            "enumeration_complete": True,
            "classification_offset": len(items),
            "items": items,
            "assignments": assignments,
            "concepts": concepts,
            "unmapped_qids": unmapped_qids,
        }

    @staticmethod
    def _write_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
        document = dict(checkpoint)
        document["concepts"] = []
        document["unmapped_qids"] = []
        document["complete"] = False
        WikidataTgmCandidateDiscoverer._write_json(path, document)

    @staticmethod
    def _write_json(path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
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
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--classification-batch-size", type=int, default=50)
    arguments = parser.parse_args()
    WikidataTgmCandidateDiscoverer(endpoint=arguments.endpoint).discover(
        arguments.roots,
        arguments.output,
        page_size=arguments.page_size,
        classification_batch_size=arguments.classification_batch_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())