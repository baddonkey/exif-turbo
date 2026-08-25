#!/usr/bin/env python3
"""Discover notable recent public figures for a separate identity manifest."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import random
import re
import tempfile
import time
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
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GROUP_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_REQUEST_ATTEMPTS = 4
_TIMEOUT_SECONDS = 180.0
_MIN_REQUEST_INTERVAL_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 60.0
_CLASSIFICATION_BATCH_SIZE = 10
_ENRICHMENT_BATCH_SIZE = 25


class WikidataPublicFigureDiscoveryError(RuntimeError):
    """The public-figure query, configuration, or response is invalid."""


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


class WikidataPublicFigureDiscoverer:
    """Select prominent public figures with multilingual labels and portraits."""

    def __init__(
        self,
        *,
        endpoint: str = _DEFAULT_ENDPOINT,
        opener: _UrlOpener | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        jitter: Callable[[], float] = random.random,
        request_interval_seconds: float = _MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must not be negative")
        self._endpoint = endpoint
        self._opener = opener or urlopen
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(UTC))
        self._jitter = jitter
        self._request_interval_seconds = request_interval_seconds
        self._last_request_started_at: float | None = None

    def discover(self, criteria_path: Path, output_path: Path) -> dict[str, Any]:
        criteria = self._load_criteria(criteria_path)
        checkpoint_path = output_path.with_suffix(".checkpoint.json")
        completed_groups = self._load_checkpoint(checkpoint_path, criteria)
        candidates: dict[str, dict[str, Any]] = {}
        group_counts: dict[str, int] = {}
        for group in criteria["groups"]:
            group_name = str(group["name"])
            checkpoint_rows = completed_groups.get(group_name)
            if checkpoint_rows is None:
                rows = self._query_group(criteria, group)
                completed_groups[group_name] = rows
                self._write_checkpoint(checkpoint_path, criteria, completed_groups)
            else:
                rows = checkpoint_rows
                print(
                    f"Discovering {group_name}: resumed {len(rows)} checkpointed matches",
                    flush=True,
                )
            group_counts[group_name] = len(rows)
            for qid, popularity, reference_image in rows:
                candidate = candidates.setdefault(
                    qid,
                    {
                        "qid": qid,
                        "category": "subject",
                        "identity_types": [],
                        "popularity": popularity,
                        "reference_image": reference_image,
                    },
                )
                candidate["identity_types"].append(group_name)
                if popularity > candidate["popularity"]:
                    candidate["popularity"] = popularity
                    candidate["reference_image"] = reference_image
        ranked = sorted(
            candidates.values(),
            key=lambda candidate: (-int(candidate["popularity"]), int(candidate["qid"][1:])),
        )
        concepts = [
            {**candidate, "priority": priority}
            for priority, candidate in enumerate(ranked, start=1)
        ]
        document = {
            "schema_version": 1,
            "identity_snapshot_version": criteria["identity_snapshot_version"],
            "created_at": criteria["created_at"],
            "endpoint": self._endpoint,
            "complete": True,
            "criteria": criteria,
            "group_counts": group_counts,
            "concepts": concepts,
        }
        self._write_json(output_path, document)
        checkpoint_path.unlink(missing_ok=True)
        return document

    def _load_checkpoint(
        self,
        path: Path,
        criteria: dict[str, Any],
    ) -> dict[str, list[tuple[str, int, str]]]:
        if not path.exists():
            return {}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WikidataPublicFigureDiscoveryError(
                "checkpoint must be readable UTF-8 JSON"
            ) from exc
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != 1
            or document.get("criteria") != criteria
            or not isinstance(document.get("groups"), dict)
        ):
            raise WikidataPublicFigureDiscoveryError(
                "checkpoint does not match public-figure criteria"
            )
        rows_by_group: dict[str, list[tuple[str, int, str]]] = {}
        for group_name, values in document["groups"].items():
            if not isinstance(group_name, str) or not isinstance(values, list):
                raise WikidataPublicFigureDiscoveryError("invalid checkpoint group")
            rows: list[tuple[str, int, str]] = []
            for value in values:
                if (
                    not isinstance(value, list)
                    or len(value) != 3
                    or not isinstance(value[0], str)
                    or _QID_PATTERN.fullmatch(value[0]) is None
                    or isinstance(value[1], bool)
                    or not isinstance(value[1], int)
                    or value[1] < 0
                    or not isinstance(value[2], str)
                    or not value[2].startswith("http")
                ):
                    raise WikidataPublicFigureDiscoveryError(
                        "invalid checkpoint identity row"
                    )
                rows.append((value[0], value[1], value[2]))
            rows_by_group[group_name] = rows
        return rows_by_group

    def _write_checkpoint(
        self,
        path: Path,
        criteria: dict[str, Any],
        groups: dict[str, list[tuple[str, int, str]]],
    ) -> None:
        self._write_json(
            path,
            {
                "schema_version": 1,
                "criteria": criteria,
                "groups": groups,
            },
        )

    @staticmethod
    def _load_criteria(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WikidataPublicFigureDiscoveryError(
                "criteria must be readable UTF-8 JSON"
            ) from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise WikidataPublicFigureDiscoveryError("unsupported criteria schema")
        version = value.get("identity_snapshot_version")
        created_at = value.get("created_at")
        cutoff = value.get("earliest_life_date")
        min_sitelinks = value.get("min_sitelinks")
        required_locales = value.get("required_locales")
        groups = value.get("groups")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version < 1
            or not isinstance(created_at, str)
            or not created_at
            or not isinstance(cutoff, str)
            or _DATE_PATTERN.fullmatch(cutoff) is None
            or isinstance(min_sitelinks, bool)
            or not isinstance(min_sitelinks, int)
            or min_sitelinks < 0
            or not isinstance(required_locales, list)
            or not required_locales
            or not all(
                isinstance(locale, str) and re.fullmatch(r"[a-z]{2,3}", locale)
                for locale in required_locales
            )
            or len(required_locales) != len(set(required_locales))
            or not isinstance(groups, list)
            or not groups
        ):
            raise WikidataPublicFigureDiscoveryError(
                "invalid public-figure criteria"
            )
        names: set[str] = set()
        for group in groups:
            if not isinstance(group, dict):
                raise WikidataPublicFigureDiscoveryError("invalid identity group")
            name = group.get("name")
            target_count = group.get("target_count")
            occupation_roots = group.get("occupation_root_qids", [])
            position_roots = group.get("position_root_qids", [])
            if (
                not isinstance(name, str)
                or _GROUP_PATTERN.fullmatch(name) is None
                or name in names
                or isinstance(target_count, bool)
                or not isinstance(target_count, int)
                or target_count < 1
                or not isinstance(occupation_roots, list)
                or not isinstance(position_roots, list)
                or not occupation_roots and not position_roots
                or not all(
                    isinstance(qid, str) and _QID_PATTERN.fullmatch(qid)
                    for qid in occupation_roots + position_roots
                )
                or len(occupation_roots) != len(set(occupation_roots))
                or len(position_roots) != len(set(position_roots))
            ):
                raise WikidataPublicFigureDiscoveryError("invalid identity group")
            names.add(name)
        return value

    def _query_group(
        self,
        criteria: dict[str, Any],
        group: dict[str, Any],
    ) -> list[tuple[str, int, str]]:
        group_name = str(group["name"])
        target_count = int(group["target_count"])
        roots: list[tuple[str, tuple[str, ...]]] = []
        if occupation_root_qids := group.get("occupation_root_qids"):
            roots.append(("P106", tuple(occupation_root_qids)))
        if position_root_qids := group.get("position_root_qids"):
            roots.append(("P39", tuple(position_root_qids)))
        candidates: dict[str, tuple[int, str]] = {}
        print(f"Discovering {group_name}: querying direct classifications", flush=True)
        for property_id, qids in roots:
            for qid in qids:
                self._merge_candidates(
                    candidates,
                    self._query_classification_batch(
                        criteria,
                        group,
                        property_id,
                        (qid,),
                    ),
                )
                print(
                    f"Discovering {group_name}: {len(candidates)}/{target_count} "
                    f"matches after direct {qid}",
                    flush=True,
                )
        print(
            f"Discovering {group_name}: {len(candidates)}/{target_count} direct matches",
            flush=True,
        )
        if len(candidates) < target_count:
            for property_id, root_qids in roots:
                root_set = set(root_qids)
                qids = tuple(
                    qid
                    for qid in self._query_classifications(root_qids)
                    if qid not in root_set
                )
                for offset in range(0, len(qids), _CLASSIFICATION_BATCH_SIZE):
                    batch = qids[offset : offset + _CLASSIFICATION_BATCH_SIZE]
                    self._merge_candidates(
                        candidates,
                        self._query_classification_batch(
                            criteria,
                            group,
                            property_id,
                            batch,
                        ),
                    )
                    print(
                        f"Discovering {group_name}: {len(candidates)}/{target_count} "
                        f"matches after {min(offset + len(batch), len(qids))}/"
                        f"{len(qids)} subclasses",
                        flush=True,
                    )
        rows = [
            (qid, popularity, reference_image)
            for qid, (popularity, reference_image) in candidates.items()
        ]
        rows.sort(key=lambda row: (-row[1], int(row[0][1:])))
        return rows[:target_count]

    @staticmethod
    def _merge_candidates(
        candidates: dict[str, tuple[int, str]],
        rows: list[tuple[str, int, str]],
    ) -> None:
        for qid, popularity, reference_image in rows:
            current = candidates.get(qid)
            if current is None or popularity > current[0]:
                candidates[qid] = (popularity, reference_image)

    def _query_classifications(self, root_qids: tuple[str, ...]) -> tuple[str, ...]:
        roots = " ".join(f"wd:{qid}" for qid in root_qids)
        query = f"""
SELECT DISTINCT ?classification WHERE {{
  VALUES ?classificationRoot {{ {roots} }}
  ?classification wdt:P279* ?classificationRoot.
  FILTER(REGEX(STR(?classification), "/Q[1-9][0-9]*$"))
}}
ORDER BY ?classification
""".strip()
        bindings = self._request_bindings(query)
        qids: set[str] = set(root_qids)
        for binding in bindings:
            try:
                classification_uri = binding["classification"]["value"]
            except (KeyError, TypeError) as exc:
                raise WikidataPublicFigureDiscoveryError(
                    "invalid public-figure classification row"
                ) from exc
            qid = str(classification_uri).removeprefix(_ENTITY_PREFIX)
            if _QID_PATTERN.fullmatch(qid) is None:
                raise WikidataPublicFigureDiscoveryError(
                    "invalid public-figure classification result"
                )
            qids.add(qid)
        return tuple(sorted(qids, key=lambda qid: int(qid[1:])))

    def _query_classification_batch(
        self,
        criteria: dict[str, Any],
        group: dict[str, Any],
        property_id: str,
        classification_qids: tuple[str, ...],
    ) -> list[tuple[str, int, str]]:
        target_count = int(group["target_count"])
        candidate_limit = target_count * 4
        classification_values = " ".join(
            f"wd:{qid}" for qid in classification_qids
        )
        candidate_query = f"""
SELECT ?item (MAX(?candidateLinks) AS ?popularity) WHERE {{
  VALUES ?classification {{ {classification_values} }}
  ?item wdt:{property_id} ?classification;
        wikibase:sitelinks ?candidateLinks.
  FILTER(?candidateLinks >= {criteria['min_sitelinks']})
  FILTER(REGEX(STR(?item), "/Q[1-9][0-9]*$"))
}}
GROUP BY ?item
ORDER BY DESC(?popularity) ?item
LIMIT {candidate_limit}
""".strip()
        candidate_bindings = self._request_bindings(candidate_query)
        candidates: list[tuple[str, int]] = []
        for binding in candidate_bindings:
            try:
                item_uri = binding["item"]["value"]
                popularity = int(binding.get("popularity", {}).get("value", 0))
            except (KeyError, TypeError, ValueError) as exc:
                raise WikidataPublicFigureDiscoveryError(
                    "invalid public-figure candidate row"
                ) from exc
            qid = str(item_uri).removeprefix(_ENTITY_PREFIX)
            if _QID_PATTERN.fullmatch(qid) is None or popularity < 0:
                raise WikidataPublicFigureDiscoveryError(
                    "invalid public-figure candidate result"
                )
            candidates.append((qid, popularity))

        rows: list[tuple[str, int, str]] = []
        for offset in range(0, len(candidates), _ENRICHMENT_BATCH_SIZE):
            batch = candidates[offset : offset + _ENRICHMENT_BATCH_SIZE]
            rows.extend(self._query_candidate_enrichment(criteria, batch))
            if len(rows) >= target_count:
                break
        rows.sort(key=lambda row: (-row[1], int(row[0][1:])))
        return rows[:target_count]

    def _query_candidate_enrichment(
        self,
        criteria: dict[str, Any],
        candidates: list[tuple[str, int]],
    ) -> list[tuple[str, int, str]]:
        popularity_by_qid = dict(candidates)
        item_values = " ".join(f"wd:{qid}" for qid, _ in candidates)
        locale_filters = "\n  ".join(
            "FILTER EXISTS { "
            f'?item rdfs:label ?label_{locale}. FILTER(LANG(?label_{locale}) = "{locale}")'
            " }"
            for locale in criteria["required_locales"]
        )
        query = f"""
SELECT ?item (MIN(STR(?portrait)) AS ?referenceImage) WHERE {{
  VALUES ?item {{ {item_values} }}
  ?item wdt:P31 wd:Q5;
        wdt:P18 ?portrait.
  OPTIONAL {{ ?item wdt:P569 ?birthDate. }}
  OPTIONAL {{ ?item wdt:P570 ?deathDate. }}
  FILTER(
    (BOUND(?birthDate) && ?birthDate >= "{criteria['earliest_life_date']}"^^xsd:dateTime) ||
    (BOUND(?deathDate) && ?deathDate >= "{criteria['earliest_life_date']}"^^xsd:dateTime)
  )
  {locale_filters}
  FILTER(REGEX(STR(?item), "/Q[1-9][0-9]*$"))
}}
GROUP BY ?item
ORDER BY ?item
""".strip()
        bindings = self._request_bindings(query)
        rows: list[tuple[str, int, str]] = []
        for binding in bindings:
            try:
                item_uri = binding["item"]["value"]
                reference_image = binding["referenceImage"]["value"]
            except (KeyError, TypeError) as exc:
                raise WikidataPublicFigureDiscoveryError(
                    "invalid public-figure query row"
                ) from exc
            qid = str(item_uri).removeprefix(_ENTITY_PREFIX)
            popularity = popularity_by_qid.get(qid, -1)
            if (
                not _QID_PATTERN.fullmatch(qid)
                or popularity < 0
                or not isinstance(reference_image, str)
                or not reference_image.startswith("http")
            ):
                raise WikidataPublicFigureDiscoveryError(
                    "invalid public-figure identity result"
                )
            rows.append((qid, popularity, reference_image))
        rows.sort(key=lambda row: (-row[1], int(row[0][1:])))
        return rows

    def _request_bindings(self, query: str) -> list[dict[str, Any]]:
        url = f"{self._endpoint}?{urlencode({'query': query, 'format': 'json'})}"
        request = Request(
            url,
            headers={"Accept": "application/sparql-results+json", "User-Agent": _USER_AGENT},
        )
        payload: bytes | None = None
        last_error: Exception | None = None
        for attempt in range(1, _MAX_REQUEST_ATTEMPTS + 1):
            self._pace_request()
            try:
                with self._opener(request, timeout=_TIMEOUT_SECONDS) as response:
                    if not 200 <= response.status < 300:
                        raise WikidataPublicFigureDiscoveryError(
                            f"Wikidata Query Service HTTP status {response.status}"
                        )
                    payload = response.read()
                break
            except HTTPError as exc:
                last_error = exc
                if exc.code != 429 and not 500 <= exc.code < 600:
                    break
                retry_after = self._retry_after_seconds(exc)
            except (URLError, OSError) as exc:
                last_error = exc
                retry_after = None
            if attempt < _MAX_REQUEST_ATTEMPTS:
                delay = self._backoff_seconds(attempt, retry_after)
                print(
                    "Retrying Wikidata query after "
                    f"{delay:.1f}s (attempt {attempt}): {last_error}",
                    flush=True,
                )
                self._sleeper(delay)
        if payload is None:
            raise WikidataPublicFigureDiscoveryError(
                "Wikidata Query Service request failed after "
                f"{_MAX_REQUEST_ATTEMPTS} attempts: {last_error}"
            ) from last_error
        try:
            document = json.loads(payload.decode("utf-8"))
            bindings = document["results"]["bindings"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise WikidataPublicFigureDiscoveryError(
                "Wikidata Query Service returned invalid JSON results"
            ) from exc
        if not isinstance(bindings, list) or not all(
            isinstance(binding, dict) for binding in bindings
        ):
            raise WikidataPublicFigureDiscoveryError(
                "Wikidata query bindings must be an array of objects"
            )
        return bindings

    def _pace_request(self) -> None:
        if self._last_request_started_at is not None:
            elapsed = self._monotonic() - self._last_request_started_at
            remaining = self._request_interval_seconds - elapsed
            if remaining > 0:
                self._sleeper(remaining)
        self._last_request_started_at = self._monotonic()

    def _backoff_seconds(self, attempt: int, retry_after: float | None) -> float:
        exponential = min(_MAX_BACKOFF_SECONDS, float(2 ** (attempt - 1)))
        jittered = exponential + self._jitter() * min(1.0, exponential)
        return max(jittered, retry_after or 0.0)

    def _retry_after_seconds(self, error: HTTPError) -> float | None:
        value = error.headers.get("Retry-After") if error.headers is not None else None
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0.0, (retry_at - self._now()).total_seconds())

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
    parser.add_argument("criteria", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--endpoint", default=_DEFAULT_ENDPOINT)
    arguments = parser.parse_args()
    WikidataPublicFigureDiscoverer(endpoint=arguments.endpoint).discover(
        arguments.criteria,
        arguments.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())