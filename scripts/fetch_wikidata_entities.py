from __future__ import annotations

import argparse
from collections.abc import Iterable
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_DEFAULT_API_URL = "https://www.wikidata.org/w/api.php"
_USER_AGENT = (
    "exif-turbo-wikidata-fetcher/1.0 "
    "(https://github.com/baddonkey/exif-turbo; build-time curator script)"
)
_QID_PATTERN = re.compile(r"^Q[1-9]\d*$")
_LANGUAGES = ("en", "de", "fr", "it")
_BATCH_SIZE = 50
_TIMEOUT_SECONDS = 30.0
_MAX_REQUEST_ATTEMPTS = 4


class WikidataEntityFetchError(RuntimeError):
    """Raised when curated Wikidata entities cannot be fetched completely."""


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


class WikidataEntityFetcher:
    def __init__(
        self,
        *,
        api_url: str = _DEFAULT_API_URL,
        opener: _UrlOpener | None = None,
        include_claims: bool = False,
    ) -> None:
        self._api_url = api_url
        self._opener = opener or urlopen
        self._include_claims = include_claims

    def fetch(
        self,
        manifest_path: Path,
        output_path: Path,
        *,
        exclude_entity_paths: tuple[Path, ...] = (),
    ) -> None:
        excluded_qids: set[str] = set()
        for path in exclude_entity_paths:
            excluded_qids.update(
                self._read_entity_qids(
                    path,
                    require_claims=self._include_claims,
                )
            )
        qids = tuple(
            qid
            for qid in self._read_manifest_qids(manifest_path)
            if qid not in excluded_qids
        )
        entities: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(qids), _BATCH_SIZE):
            batch = qids[offset : offset + _BATCH_SIZE]
            entities.update(self._fetch_batch(batch))
            print(
                f"Fetched {min(offset + len(batch), len(qids))}/{len(qids)} entities",
                flush=True,
            )
        missing_qids = [qid for qid in qids if qid not in entities]
        if missing_qids:
            raise WikidataEntityFetchError(
                "missing QIDs: " + ", ".join(missing_qids)
            )
        self._write_entities(output_path, (entities[qid] for qid in qids))

    @staticmethod
    def _read_entity_qids(
        path: Path,
        *,
        require_claims: bool,
    ) -> set[str]:
        qids: set[str] = set()
        with path.open("r", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    entity = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise WikidataEntityFetchError(
                        f"invalid existing entity on line {line_number} of {path.name}"
                    ) from exc
                qid = entity.get("id") if isinstance(entity, dict) else None
                if (
                    not isinstance(qid, str)
                    or not _QID_PATTERN.fullmatch(qid)
                    or qid in qids
                ):
                    raise WikidataEntityFetchError(
                        f"invalid existing entity ID on line {line_number} of {path.name}"
                    )
                if (
                    "missing" in entity
                    or "deleted" in entity
                    or (require_claims and not isinstance(entity.get("claims"), dict))
                ):
                    continue
                qids.add(qid)
        return qids

    def _fetch_batch(self, qids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        query = urlencode(
            {
                "action": "wbgetentities",
                "format": "json",
                "formatversion": "2",
                "ids": "|".join(qids),
                "languages": "|".join(_LANGUAGES),
                "props": (
                    "info|labels|aliases|descriptions|claims"
                    if self._include_claims
                    else "info|labels|aliases|descriptions"
                ),
            }
        )
        separator = "&" if "?" in self._api_url else "?"
        request = Request(
            f"{self._api_url}{separator}{query}",
            headers={"User-Agent": _USER_AGENT},
        )
        payload: bytes | None = None
        last_error: Exception | None = None
        for attempt in range(1, _MAX_REQUEST_ATTEMPTS + 1):
            try:
                with self._opener(request, timeout=_TIMEOUT_SECONDS) as response:
                    if not 200 <= response.status < 300:
                        raise WikidataEntityFetchError(
                            f"Wikidata HTTP status {response.status}"
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
                    f"Retrying Wikidata entity batch after attempt {attempt}: "
                    f"{last_error}",
                    flush=True,
                )
        if payload is None:
            raise WikidataEntityFetchError(
                f"Wikidata request failed after {_MAX_REQUEST_ATTEMPTS} attempts: "
                f"{last_error}"
            ) from last_error
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WikidataEntityFetchError(
                "Wikidata API returned invalid UTF-8 JSON"
            ) from exc
        if not isinstance(document, dict):
            raise WikidataEntityFetchError("Wikidata API response must be an object")
        api_error = document.get("error")
        if api_error is not None:
            if isinstance(api_error, dict):
                code = str(api_error.get("code", "unknown"))
                info = str(api_error.get("info", "unknown API error"))
                raise WikidataEntityFetchError(
                    f"Wikidata API error {code}: {info}"
                )
            raise WikidataEntityFetchError("Wikidata API returned an invalid error")
        entity_values = document.get("entities")
        if not isinstance(entity_values, dict):
            raise WikidataEntityFetchError(
                "Wikidata API response is missing entities"
            )
        entities: dict[str, dict[str, Any]] = {}
        for qid in qids:
            entity = entity_values.get(qid)
            if not isinstance(entity, dict) or "missing" in entity:
                continue
            if entity.get("id") != qid:
                raise WikidataEntityFetchError(
                    f"Wikidata API returned mismatched entity for {qid}"
                )
            if self._include_claims and not isinstance(entity.get("claims"), dict):
                raise WikidataEntityFetchError(
                    f"Wikidata API returned claims-free entity for {qid}"
                )
            entities[qid] = entity
        return entities

    @staticmethod
    def _read_manifest_qids(path: Path) -> tuple[str, ...]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WikidataEntityFetchError(
                "manifest must be readable UTF-8 JSON"
            ) from exc
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise WikidataEntityFetchError(
                "unsupported Wikidata manifest schema"
            )
        concepts = document.get("concepts")
        if not isinstance(concepts, list) or not concepts:
            raise WikidataEntityFetchError(
                "manifest concepts must be a non-empty array"
            )
        qids: list[str] = []
        for concept in concepts:
            if not isinstance(concept, dict):
                raise WikidataEntityFetchError(
                    "manifest concepts must be objects"
                )
            qid = concept.get("qid")
            if not isinstance(qid, str) or not _QID_PATTERN.fullmatch(qid):
                raise WikidataEntityFetchError(
                    "manifest qid must match Q<positive integer>"
                )
            qids.append(qid)
        if len(qids) != len(set(qids)):
            raise WikidataEntityFetchError("manifest QIDs must be unique")
        return tuple(sorted(qids, key=lambda qid: int(qid[1:])))

    @staticmethod
    def _write_entities(
        output_path: Path, entities: Iterable[dict[str, Any]]
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=output_path.parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                for entity in entities:
                    json.dump(
                        entity,
                        stream,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, output_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


class WikidataEntityFetchCommand:
    def run(self) -> int:
        parser = argparse.ArgumentParser(
            description=(
                "Fetch curated Wikidata entities as deterministic JSON-lines input."
            )
        )
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--api-url", default=_DEFAULT_API_URL)
        parser.add_argument(
            "--exclude-entities",
            action="append",
            default=[],
            type=Path,
            help="skip QIDs already present in this JSON-lines export",
        )
        parser.add_argument(
            "--include-claims",
            action="store_true",
            help="include claims required by graph-based curation",
        )
        arguments = parser.parse_args()
        WikidataEntityFetcher(
            api_url=arguments.api_url,
            include_claims=arguments.include_claims,
        ).fetch(
            arguments.manifest,
            arguments.output,
            exclude_entity_paths=tuple(arguments.exclude_entities),
        )
        return 0


def main() -> int:
    return WikidataEntityFetchCommand().run()


if __name__ == "__main__":
    raise SystemExit(main())