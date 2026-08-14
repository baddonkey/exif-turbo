from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TgmCategory(StrEnum):
    SUBJECT = "subject"
    GENRE_FORMAT = "genre_format"


class TgmSourceFormat(StrEnum):
    XML = "xml"
    TAGGED_TEXT = "tagged_text"


class TgmDiagnosticCode(StrEnum):
    MISSING_TNR = "missing_tnr"
    DUPLICATE_ALIAS_COLLISION = "duplicate_alias_collision"
    DUPLICATE_DESCRIPTOR = "duplicate_descriptor"
    UNRESOLVED_USE = "unresolved_use"
    UNRESOLVED_RELATION = "unresolved_relation"
    UNSUPPORTED_CATEGORY = "unsupported_category"


@dataclass(frozen=True)
class TgmDiagnostic:
    code: TgmDiagnosticCode
    message: str
    label: str | None = None


@dataclass(frozen=True)
class TgmConcept:
    concept_id: str
    tnr: str
    label: str
    categories: tuple[TgmCategory, ...]
    aliases: tuple[str, ...] = ()
    broader_ids: tuple[str, ...] = ()
    narrower_ids: tuple[str, ...] = ()
    related_ids: tuple[str, ...] = ()
    facet_notes: tuple[str, ...] = ()
    scope_notes: tuple[str, ...] = ()
    cataloger_notes: tuple[str, ...] = ()
    history_notes: tuple[str, ...] = ()
    function_notes: tuple[str, ...] = ()
    former_gmgpc_ids: tuple[str, ...] = ()
    former_lctgm_ids: tuple[str, ...] = ()
    reference_types: tuple[str, ...] = ()
    subdivision_types: tuple[str, ...] = ()
    subject_types: tuple[str, ...] = ()
    form_types: tuple[str, ...] = ()

    @property
    def selectable(self) -> bool:
        return bool(self.categories)


@dataclass(frozen=True)
class TgmSnapshot:
    concepts: tuple[TgmConcept, ...]
    diagnostics: tuple[TgmDiagnostic, ...]
    source_url: str
    source_format: TgmSourceFormat
    distribution_date: str | None
    imported_at: datetime
    raw_sha256: str
    raw_size_bytes: int
    normalization_version: int = 1

    def concept_by_id(self, concept_id: str) -> TgmConcept | None:
        return next(
            (concept for concept in self.concepts if concept.concept_id == concept_id),
            None,
        )

    def resolve_label(self, label: str) -> TgmConcept | None:
        normalized = label.casefold()
        return next(
            (
                concept
                for concept in self.concepts
                if concept.label.casefold() == normalized
                or any(alias.casefold() == normalized for alias in concept.aliases)
            ),
            None,
        )

    @property
    def selectable_concepts(self) -> tuple[TgmConcept, ...]:
        return tuple(concept for concept in self.concepts if concept.selectable)