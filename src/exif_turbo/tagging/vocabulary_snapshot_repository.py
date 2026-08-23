from __future__ import annotations

from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from ..models.vocabulary import (
    REQUIRED_VOCABULARY_LOCALES,
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
    VocabularySnapshot,
)


class VocabularySnapshotRepository:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self._path = path
        self._snapshot: VocabularySnapshot | None = None
        self._by_id: dict[str, VocabularyConcept] = {}
        self._by_label: dict[tuple[str, str], list[VocabularyConcept]] = {}

    def activate(self, snapshot: VocabularySnapshot) -> None:
        payload = json.dumps(
            self._to_dict(snapshot),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        temp_path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as raw_stream:
                with gzip.GzipFile(
                    filename="", fileobj=raw_stream, mode="wb", mtime=0
                ) as stream:
                    stream.write(payload)
                raw_stream.flush()
                os.fsync(raw_stream.fileno())
            validated = self._decode(temp_path.read_bytes())
            os.replace(temp_path, self._path)
        finally:
            temp_path.unlink(missing_ok=True)
        self._set_snapshot(validated)

    def load(self) -> VocabularySnapshot:
        if self._snapshot is None:
            self._set_snapshot(self._decode(self._path.read_bytes()))
        assert self._snapshot is not None
        return self._snapshot

    def get(self, concept_id: str) -> VocabularyConcept | None:
        self.load()
        return self._by_id.get(concept_id)

    def preferred_label(self, concept_id: str, locale: str) -> str | None:
        self._require_locale(locale)
        concept = self.get(concept_id)
        return None if concept is None else concept.preferred_label(locale)

    def resolve_label(self, label: str, locale: str) -> VocabularyConcept | None:
        self._require_locale(locale)
        self.load()
        matches = self._by_label.get((locale, label.strip().casefold()), [])
        if len(matches) > 1:
            raise ValueError(f"label is ambiguous in locale {locale}: {label}")
        return matches[0] if matches else None

    def search(
        self, query: str, locale: str, limit: int = 20
    ) -> tuple[VocabularyConcept, ...]:
        self._require_locale(locale)
        normalized = query.strip().casefold()
        if not normalized or limit <= 0:
            return ()
        matches: list[tuple[int, str, str, VocabularyConcept]] = []
        for concept in self.load().concepts:
            terms = concept.terms(locale)
            labels = (terms.preferred_label, *terms.aliases)
            folded = tuple(label.casefold() for label in labels)
            if not any(normalized in label for label in folded):
                continue
            rank = 0 if any(label.startswith(normalized) for label in folded) else 1
            matches.append(
                (rank, terms.preferred_label.casefold(), concept.concept_id, concept)
            )
        matches.sort(key=lambda item: item[:3])
        return tuple(item[3] for item in matches[:limit])

    def _set_snapshot(self, snapshot: VocabularySnapshot) -> None:
        self._snapshot = snapshot
        self._by_id = {concept.concept_id: concept for concept in snapshot.concepts}
        self._by_label = {}
        for concept in snapshot.concepts:
            for terms in concept.localized_terms:
                for label in (terms.preferred_label, *terms.aliases):
                    self._by_label.setdefault(
                        (terms.locale, label.casefold()), []
                    ).append(concept)
        for concepts in self._by_label.values():
            concepts.sort(key=lambda concept: concept.concept_id)

    @classmethod
    def _decode(cls, payload: bytes) -> VocabularySnapshot:
        value = json.loads(gzip.decompress(payload).decode("utf-8"))
        return cls._from_dict(value)

    @classmethod
    def _to_dict(cls, snapshot: VocabularySnapshot) -> dict[str, Any]:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "version": snapshot.version,
            "created_at": snapshot.created_at.isoformat(),
            "source_name": snapshot.source_name,
            "source_dump_uri": snapshot.source_dump_uri,
            "source_dump_sha256": snapshot.source_dump_sha256,
            "manifest_sha256": snapshot.manifest_sha256,
            "license_id": snapshot.license_id,
            "concepts": [
                {
                    "concept_id": concept.concept_id,
                    "category": concept.category.value,
                    "canonical_label": concept.canonical_label,
                    "source_uri": concept.source_uri,
                    "license_id": concept.license_id,
                    "localized_terms": [
                        {
                            "locale": terms.locale,
                            "preferred_label": terms.preferred_label,
                            "aliases": list(terms.aliases),
                        }
                        for terms in concept.localized_terms
                    ],
                }
                for concept in snapshot.concepts
            ],
        }

    @classmethod
    def _from_dict(cls, value: object) -> VocabularySnapshot:
        if not isinstance(value, dict) or value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported vocabulary snapshot schema")
        concepts_value = value.get("concepts")
        if not isinstance(concepts_value, list):
            raise ValueError("vocabulary snapshot concepts must be an array")
        concepts: list[VocabularyConcept] = []
        for concept_value in concepts_value:
            if not isinstance(concept_value, dict):
                raise ValueError("vocabulary concept must be an object")
            localized_value = concept_value.get("localized_terms")
            if not isinstance(localized_value, list):
                raise ValueError("localized_terms must be an array")
            localized_terms = tuple(
                LocalizedVocabularyTerms(
                    locale=str(terms["locale"]),
                    preferred_label=str(terms["preferred_label"]),
                    aliases=tuple(str(alias) for alias in terms.get("aliases", [])),
                )
                for terms in localized_value
                if isinstance(terms, dict)
            )
            if len(localized_terms) != len(localized_value):
                raise ValueError("localized_terms entries must be objects")
            concepts.append(
                VocabularyConcept(
                    concept_id=str(concept_value["concept_id"]),
                    category=VocabularyCategory(str(concept_value["category"])),
                    canonical_label=str(concept_value["canonical_label"]),
                    localized_terms=localized_terms,
                    source_uri=str(concept_value["source_uri"]),
                    license_id=str(concept_value["license_id"]),
                )
            )
        return VocabularySnapshot(
            concepts=tuple(concepts),
            version=int(value["version"]),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            source_name=str(value["source_name"]),
            source_dump_uri=str(value["source_dump_uri"]),
            source_dump_sha256=str(value["source_dump_sha256"]),
            manifest_sha256=str(value["manifest_sha256"]),
            license_id=str(value["license_id"]),
        )

    @staticmethod
    def _require_locale(locale: str) -> None:
        if locale not in REQUIRED_VOCABULARY_LOCALES:
            raise ValueError(f"locale must be a required locale: {locale}")