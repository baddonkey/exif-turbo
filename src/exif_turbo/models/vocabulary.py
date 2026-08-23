from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re


REQUIRED_VOCABULARY_LOCALES = frozenset({"en", "de", "fr", "it"})
_CONCEPT_ID_PATTERN = re.compile(r"^wikidata:Q[1-9]\d*$")
_LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


class VocabularyCategory(StrEnum):
    SUBJECT = "subject"
    GENRE_FORMAT = "genre_format"


@dataclass(frozen=True)
class LocalizedVocabularyTerms:
    locale: str
    preferred_label: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _LOCALE_PATTERN.fullmatch(self.locale):
            raise ValueError("locale must be a BCP 47 language tag")
        if not self.preferred_label.strip():
            raise ValueError("preferred_label must not be empty")
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("aliases must not contain empty values")
        folded = [alias.casefold() for alias in self.aliases]
        if len(folded) != len(set(folded)):
            raise ValueError("aliases must be unique within a locale")


@dataclass(frozen=True)
class VocabularyConcept:
    concept_id: str
    category: VocabularyCategory
    canonical_label: str
    localized_terms: tuple[LocalizedVocabularyTerms, ...]
    source_uri: str
    license_id: str

    def __post_init__(self) -> None:
        if not _CONCEPT_ID_PATTERN.fullmatch(self.concept_id):
            raise ValueError("concept_id must match wikidata:Q<positive integer>")
        if not self.canonical_label.strip():
            raise ValueError("canonical_label must not be empty")
        if not self.source_uri.strip():
            raise ValueError("source_uri must not be empty")
        if not self.license_id.strip():
            raise ValueError("license_id must not be empty")
        locales = [terms.locale for terms in self.localized_terms]
        if len(locales) != len(set(locales)):
            raise ValueError("localized_terms must contain unique locales")
        missing = REQUIRED_VOCABULARY_LOCALES.difference(locales)
        if missing:
            raise ValueError(
                "localized_terms is missing required locales: "
                + ", ".join(sorted(missing))
            )
        if self.preferred_label("en") != self.canonical_label:
            raise ValueError("canonical_label must equal the English preferred label")

    def terms(self, locale: str) -> LocalizedVocabularyTerms:
        for terms in self.localized_terms:
            if terms.locale == locale:
                return terms
        raise ValueError(f"concept has no intrinsic terms for locale: {locale}")

    def preferred_label(self, locale: str) -> str:
        return self.terms(locale).preferred_label

    def aliases(self, locale: str) -> tuple[str, ...]:
        return self.terms(locale).aliases


@dataclass(frozen=True)
class VocabularySnapshot:
    concepts: tuple[VocabularyConcept, ...]
    version: int
    created_at: datetime
    source_name: str
    source_dump_uri: str
    source_dump_sha256: str
    manifest_sha256: str
    license_id: str

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError("version must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if not self.source_name.strip() or not self.source_dump_uri.strip():
            raise ValueError("snapshot source fields must not be empty")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_dump_sha256):
            raise ValueError("source_dump_sha256 must be lowercase SHA256")
        if not re.fullmatch(r"[0-9a-f]{64}", self.manifest_sha256):
            raise ValueError("manifest_sha256 must be lowercase SHA256")
        if not self.license_id.strip():
            raise ValueError("license_id must not be empty")
        concept_ids = [concept.concept_id for concept in self.concepts]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("snapshot contains duplicate concept IDs")

    def concept_by_id(self, concept_id: str) -> VocabularyConcept | None:
        return next(
            (concept for concept in self.concepts if concept.concept_id == concept_id),
            None,
        )