from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


_LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
_REVIEW_STATUSES = {"unreviewed", "machine-reviewed", "human-reviewed"}


@dataclass(frozen=True)
class TgmConceptLocalization:
    concept_id: str
    locale: str
    preferred_label: str
    aliases: tuple[str, ...] = ()
    source_uri: str = ""
    license_id: str = ""
    translation_method: str = "manual"
    review_status: str = "unreviewed"

    def __post_init__(self) -> None:
        if not self.concept_id.startswith("loc-tgm:tgm"):
            raise ValueError("localization concept_id must be a LOC TGM identifier")
        if not _LOCALE_PATTERN.fullmatch(self.locale):
            raise ValueError("localization locale must be a BCP 47 language tag")
        if not self.preferred_label.strip():
            raise ValueError("localized preferred_label must not be empty")
        if self.review_status not in _REVIEW_STATUSES:
            raise ValueError("unsupported localization review_status")


@dataclass(frozen=True)
class TgmLocalizationPack:
    records: tuple[TgmConceptLocalization, ...]
    version: int
    created_at: datetime
    source_uri: str
    license_id: str

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError("localization pack version must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("localization pack created_at must be timezone-aware")
        if not self.source_uri.strip():
            raise ValueError("localization pack source_uri must not be empty")
        if not self.license_id.strip():
            raise ValueError("localization pack license_id must not be empty")
        keys = [(record.concept_id, record.locale) for record in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("localization pack contains duplicate concept locales")

    @property
    def locales(self) -> tuple[str, ...]:
        return tuple(sorted({record.locale for record in self.records}))