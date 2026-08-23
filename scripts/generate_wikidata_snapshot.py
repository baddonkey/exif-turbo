from __future__ import annotations

import argparse
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, TextIO

from exif_turbo.models.vocabulary import (
    REQUIRED_VOCABULARY_LOCALES,
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
    VocabularySnapshot,
)
from exif_turbo.tagging.vocabulary_snapshot_repository import (
    VocabularySnapshotRepository,
)


_QID_PATTERN = re.compile(r"^Q[1-9]\d*$")


class WikidataGenerationError(ValueError):
    """Raised when offline inputs cannot produce a complete snapshot."""


@dataclass(frozen=True)
class _ManifestConcept:
    qid: str
    category: VocabularyCategory


@dataclass(frozen=True)
class _Manifest:
    concepts: tuple[_ManifestConcept, ...]
    snapshot_version: int
    created_at: datetime
    source_name: str
    dump_uri: str
    dump_sha256: str
    license_id: str
    sha256: str


class _WikidataEntityReader:
    _CHUNK_SIZE = 64 * 1024

    def iter_entities(self, path: Path) -> Iterator[dict[str, Any]]:
        with path.open("r", encoding="utf-8-sig") as stream:
            marker = self._first_non_whitespace(stream)
            stream.seek(0)
            iterator = self._iter_array(stream) if marker == "[" else self._iter_lines(stream)
            for value in iterator:
                if not isinstance(value, dict):
                    raise WikidataGenerationError("Wikidata dump entries must be objects")
                yield value

    @staticmethod
    def _first_non_whitespace(stream: TextIO) -> str:
        while char := stream.read(1):
            if not char.isspace():
                return char
        raise WikidataGenerationError("Wikidata dump is empty")

    @staticmethod
    def _iter_lines(stream: TextIO) -> Iterator[object]:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise WikidataGenerationError(
                    f"invalid JSON-lines entry at line {line_number}"
                ) from exc

    def _iter_array(self, stream: TextIO) -> Iterator[object]:
        decoder = json.JSONDecoder()
        buffer = ""
        position = 0
        eof = False
        opened = False
        expect_value = True
        while True:
            if position >= len(buffer) and not eof:
                buffer = stream.read(self._CHUNK_SIZE)
                position = 0
                eof = not buffer
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position >= len(buffer):
                if eof:
                    raise WikidataGenerationError("unterminated Wikidata JSON array")
                continue
            if not opened:
                if buffer[position] != "[":
                    raise WikidataGenerationError("Wikidata JSON array must start with '['")
                opened = True
                position += 1
                continue
            if not expect_value:
                if buffer[position] == "]":
                    if buffer[position + 1 :].strip() or stream.read().strip():
                        raise WikidataGenerationError("data follows Wikidata JSON array")
                    return
                if buffer[position] != ",":
                    raise WikidataGenerationError("Wikidata JSON array entries need commas")
                position += 1
                expect_value = True
                continue
            if buffer[position] == "]":
                if buffer[position + 1 :].strip() or stream.read().strip():
                    raise WikidataGenerationError("data follows Wikidata JSON array")
                return
            while True:
                try:
                    value, end = decoder.raw_decode(buffer, position)
                    position = end
                    expect_value = False
                    yield value
                    break
                except json.JSONDecodeError as exc:
                    if eof:
                        raise WikidataGenerationError("invalid Wikidata JSON array") from exc
                    chunk = stream.read(self._CHUNK_SIZE)
                    buffer = buffer[position:] + chunk
                    position = 0
                    eof = not chunk


class WikidataSnapshotGenerator:
    def __init__(self, reader: _WikidataEntityReader | None = None) -> None:
        self._reader = reader or _WikidataEntityReader()

    def generate(
        self, manifest_path: Path, dump_path: Path, output_path: Path
    ) -> VocabularySnapshot:
        manifest = self._read_manifest(manifest_path)
        actual_dump_sha256 = self._sha256(dump_path)
        if actual_dump_sha256 != manifest.dump_sha256:
            raise WikidataGenerationError(
                "Wikidata dump SHA256 mismatch: "
                f"expected {manifest.dump_sha256}, got {actual_dump_sha256}"
            )
        entities, redirects = self._select_entities(
            dump_path, {concept.qid for concept in manifest.concepts}
        )
        concepts = tuple(
            sorted(
                (
                    self._build_concept(
                        self._resolve_qid(concept.qid, redirects),
                        concept.category,
                        entities,
                        manifest.license_id,
                    )
                    for concept in manifest.concepts
                ),
                key=lambda concept: int(concept.concept_id.removeprefix("wikidata:Q")),
            )
        )
        if len({concept.concept_id for concept in concepts}) != len(concepts):
            raise WikidataGenerationError("manifest QIDs resolve to duplicate concepts")
        snapshot = VocabularySnapshot(
            concepts=concepts,
            version=manifest.snapshot_version,
            created_at=manifest.created_at,
            source_name=manifest.source_name,
            source_dump_uri=manifest.dump_uri,
            source_dump_sha256=manifest.dump_sha256,
            manifest_sha256=manifest.sha256,
            license_id=manifest.license_id,
        )
        VocabularySnapshotRepository(output_path).activate(snapshot)
        return snapshot

    def _select_entities(
        self, dump_path: Path, requested_qids: set[str]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        wanted = set(requested_qids)
        entities: dict[str, dict[str, Any]] = {}
        redirects: dict[str, str] = {}
        previous_wanted_size = -1
        while previous_wanted_size != len(wanted):
            previous_wanted_size = len(wanted)
            for entity in self._reader.iter_entities(dump_path):
                qid = entity.get("id")
                if not isinstance(qid, str) or qid not in wanted:
                    continue
                if "deleted" in entity or "missing" in entity:
                    raise WikidataGenerationError(f"deleted QID: {qid}")
                redirect_target = self._redirect_target(entity)
                if redirect_target is not None:
                    redirects[qid] = redirect_target
                    wanted.add(redirect_target)
                else:
                    entities[qid] = entity
        unresolved = sorted(
            qid
            for qid in requested_qids
            if self._resolve_qid(qid, redirects) not in entities
        )
        if unresolved:
            raise WikidataGenerationError("missing QIDs: " + ", ".join(unresolved))
        return entities, redirects

    @staticmethod
    def _redirect_target(entity: dict[str, Any]) -> str | None:
        redirect = entity.get("redirect")
        target: object
        if isinstance(redirect, str):
            target = redirect
        elif isinstance(redirect, dict):
            target = redirect.get("to", redirect.get("id"))
        else:
            return None
        if not isinstance(target, str) or not _QID_PATTERN.fullmatch(target):
            raise WikidataGenerationError(
                f"invalid redirect target for {entity.get('id', '<unknown>')}"
            )
        return target

    @staticmethod
    def _resolve_qid(qid: str, redirects: dict[str, str]) -> str:
        visited: set[str] = set()
        while qid in redirects:
            if qid in visited:
                raise WikidataGenerationError("Wikidata redirect cycle detected")
            visited.add(qid)
            qid = redirects[qid]
        return qid

    @staticmethod
    def _build_concept(
        qid: str,
        category: VocabularyCategory,
        entities: dict[str, dict[str, Any]],
        license_id: str,
    ) -> VocabularyConcept:
        entity = entities[qid]
        labels = entity.get("labels")
        aliases = entity.get("aliases", {})
        if not isinstance(labels, dict) or not isinstance(aliases, dict):
            raise WikidataGenerationError(f"QID {qid} has invalid labels or aliases")
        localized_terms: list[LocalizedVocabularyTerms] = []
        for locale in sorted(REQUIRED_VOCABULARY_LOCALES):
            label_record = labels.get(locale)
            if not isinstance(label_record, dict):
                raise WikidataGenerationError(f"QID {qid} is missing locale {locale}")
            preferred_label = label_record.get("value")
            if not isinstance(preferred_label, str) or not preferred_label.strip():
                raise WikidataGenerationError(f"QID {qid} is missing locale {locale}")
            alias_records = aliases.get(locale, [])
            if not isinstance(alias_records, list):
                raise WikidataGenerationError(f"QID {qid} has invalid aliases for {locale}")
            alias_values: dict[str, str] = {}
            for record in alias_records:
                if not isinstance(record, dict) or not isinstance(record.get("value"), str):
                    raise WikidataGenerationError(
                        f"QID {qid} has invalid aliases for {locale}"
                    )
                value = str(record["value"]).strip()
                if value and value.casefold() != preferred_label.casefold():
                    alias_values.setdefault(value.casefold(), value)
            localized_terms.append(
                LocalizedVocabularyTerms(
                    locale=locale,
                    preferred_label=preferred_label.strip(),
                    aliases=tuple(
                        sorted(alias_values.values(), key=lambda value: (value.casefold(), value))
                    ),
                )
            )
        english = next(terms for terms in localized_terms if terms.locale == "en")
        try:
            return VocabularyConcept(
                concept_id=f"wikidata:{qid}",
                category=category,
                canonical_label=english.preferred_label,
                localized_terms=tuple(localized_terms),
                source_uri=f"https://www.wikidata.org/entity/{qid}",
                license_id=license_id,
            )
        except ValueError as exc:
            raise WikidataGenerationError(f"invalid QID {qid}: {exc}") from exc

    @staticmethod
    def _read_manifest(path: Path) -> _Manifest:
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WikidataGenerationError("manifest must be UTF-8 JSON") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise WikidataGenerationError("unsupported Wikidata manifest schema")
        source = value.get("source")
        concepts_value = value.get("concepts")
        if not isinstance(source, dict) or not isinstance(concepts_value, list):
            raise WikidataGenerationError("manifest source and concepts are required")
        concepts: list[_ManifestConcept] = []
        for concept in concepts_value:
            if not isinstance(concept, dict):
                raise WikidataGenerationError("manifest concepts must be objects")
            qid = concept.get("qid")
            if not isinstance(qid, str) or not _QID_PATTERN.fullmatch(qid):
                raise WikidataGenerationError("manifest qid must match Q<positive integer>")
            concepts.append(
                _ManifestConcept(
                    qid=qid,
                    category=VocabularyCategory(str(concept.get("category"))),
                )
            )
        qids = [concept.qid for concept in concepts]
        if not concepts or len(qids) != len(set(qids)):
            raise WikidataGenerationError("manifest concepts must be non-empty and unique")
        license_id = str(source.get("license_id", ""))
        if license_id != "CC0-1.0":
            raise WikidataGenerationError("Wikidata manifest license_id must be CC0-1.0")
        try:
            created_at = datetime.fromisoformat(str(value["created_at"]))
            manifest = _Manifest(
                concepts=tuple(concepts),
                snapshot_version=int(value["snapshot_version"]),
                created_at=created_at,
                source_name=str(source["name"]),
                dump_uri=str(source["dump_uri"]),
                dump_sha256=str(source["dump_sha256"]),
                license_id=license_id,
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WikidataGenerationError(f"invalid Wikidata manifest: {exc}") from exc
        if created_at.tzinfo is None:
            raise WikidataGenerationError("manifest created_at must be timezone-aware")
        if not re.fullmatch(r"[0-9a-f]{64}", manifest.dump_sha256):
            raise WikidataGenerationError("manifest dump_sha256 must be lowercase SHA256")
        return manifest

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()


class WikidataSnapshotCommand:
    def run(self) -> int:
        parser = argparse.ArgumentParser(
            description="Generate a deterministic vocabulary snapshot from a local Wikidata dump."
        )
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--dump", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        arguments = parser.parse_args()
        WikidataSnapshotGenerator().generate(
            arguments.manifest, arguments.dump, arguments.output
        )
        return 0


def main() -> int:
    return WikidataSnapshotCommand().run()


if __name__ == "__main__":
    raise SystemExit(main())