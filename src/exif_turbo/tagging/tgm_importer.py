from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
import hashlib
import re

from ..models.tgm import (
    TgmCategory,
    TgmConcept,
    TgmDiagnostic,
    TgmDiagnosticCode,
    TgmSnapshot,
    TgmSourceFormat,
)
from .tgm_source_record import ParsedTgmSource, TgmSourceRecord
from .tgm_text_parser import TgmTextParser
from .tgm_xml_parser import TgmXmlParser


_TNR_PATTERN = re.compile(r"^tgm\d{6}$")


class TgmImportError(ValueError):
    """Raised when a source cannot produce a valid normalized TGM snapshot."""


class TgmImporter:
    def import_bytes(
        self,
        raw: bytes,
        *,
        source_url: str,
        source_format: TgmSourceFormat,
        imported_at: datetime,
    ) -> TgmSnapshot:
        if source_format is TgmSourceFormat.XML:
            parsed = TgmXmlParser().parse(raw)
        elif source_format is TgmSourceFormat.TAGGED_TEXT:
            parsed = TgmTextParser().parse(raw)
        else:
            raise TgmImportError(f"unsupported TGM source format: {source_format}")
        return self._normalize(
            parsed,
            source_url=source_url,
            source_format=source_format,
            imported_at=imported_at,
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            raw_size_bytes=len(raw),
        )

    def _normalize(
        self,
        parsed: ParsedTgmSource,
        *,
        source_url: str,
        source_format: TgmSourceFormat,
        imported_at: datetime,
        raw_sha256: str,
        raw_size_bytes: int,
    ) -> TgmSnapshot:
        diagnostics: list[TgmDiagnostic] = []
        descriptor_by_tnr: dict[str, TgmSourceRecord] = {}
        descriptor_by_label: dict[str, TgmSourceRecord] = {}
        for record in parsed.records:
            if not record.is_descriptor:
                continue
            tnr = record.first("TNR")
            if tnr is None or not _TNR_PATTERN.fullmatch(tnr):
                diagnostics.append(self._diagnostic(TgmDiagnosticCode.MISSING_TNR, record))
                continue
            existing = descriptor_by_tnr.get(tnr)
            if existing is not None and existing.label.casefold() != record.label.casefold():
                raise TgmImportError(
                    f"conflicting descriptor TNR {tnr}: {existing.label!r} and {record.label!r}"
                )
            descriptor_by_tnr[tnr] = record
            descriptor_by_label[record.label.casefold()] = record

        aliases_by_tnr: dict[str, set[str]] = defaultdict(set)
        for record in descriptor_by_tnr.values():
            aliases_by_tnr[record.first("TNR") or ""].update(record.values("UF"))
        for record in parsed.records:
            if record.is_descriptor:
                continue
            target = self._resolve_use(record, descriptor_by_label)
            if target is None:
                diagnostics.append(self._diagnostic(TgmDiagnosticCode.UNRESOLVED_USE, record))
                continue
            target_tnr = target.first("TNR")
            assert target_tnr is not None
            alias_tnr = record.first("TNR")
            if alias_tnr in descriptor_by_tnr:
                diagnostics.append(
                    self._diagnostic(TgmDiagnosticCode.DUPLICATE_ALIAS_COLLISION, record)
                )
                continue
            aliases_by_tnr[target_tnr].add(record.label)

        concepts: list[TgmConcept] = []
        for tnr, record in descriptor_by_tnr.items():
            concept = TgmConcept(
                concept_id=f"loc-tgm:{tnr}",
                tnr=tnr,
                label=record.label,
                categories=self._categories(record, diagnostics),
                aliases=tuple(sorted(aliases_by_tnr[tnr], key=str.casefold)),
                facet_notes=record.values("Facet"),
                scope_notes=record.values("SN"),
                cataloger_notes=record.values("CN"),
                history_notes=record.values("HN"),
                function_notes=record.values("FUN"),
                former_gmgpc_ids=record.values("FCNgmgpc"),
                former_lctgm_ids=record.values("FCNlctgm"),
                reference_types=record.values("TTCRef"),
                subdivision_types=record.values("TTCSubd"),
                subject_types=record.values("TTCSubj"),
                form_types=record.values("TTCForm"),
            )
            concepts.append(
                replace(
                    concept,
                    broader_ids=self._relations(record, "BT", descriptor_by_label, diagnostics),
                    narrower_ids=self._relations(record, "NT", descriptor_by_label, diagnostics),
                    related_ids=self._relations(record, "RT", descriptor_by_label, diagnostics),
                )
            )
        concepts.sort(key=lambda concept: concept.label.casefold())
        if not any(concept.selectable for concept in concepts):
            raise TgmImportError("TGM candidate has no selectable canonical concepts")
        return TgmSnapshot(
            concepts=tuple(concepts),
            diagnostics=tuple(diagnostics),
            source_url=source_url,
            source_format=source_format,
            distribution_date=parsed.distribution_date,
            imported_at=imported_at,
            raw_sha256=raw_sha256,
            raw_size_bytes=raw_size_bytes,
        )

    @staticmethod
    def _resolve_use(
        record: TgmSourceRecord,
        descriptors: dict[str, TgmSourceRecord],
    ) -> TgmSourceRecord | None:
        return next(
            (descriptors[value.casefold()] for value in record.values("USE") if value.casefold() in descriptors),
            None,
        )

    @staticmethod
    def _categories(
        record: TgmSourceRecord,
        diagnostics: list[TgmDiagnostic],
    ) -> tuple[TgmCategory, ...]:
        categories: list[TgmCategory] = []
        if any("150" in value or "650" in value for value in record.values("TTCSubj")):
            categories.append(TgmCategory.SUBJECT)
        if any("155" in value or "655" in value for value in record.values("TTCForm")):
            categories.append(TgmCategory.GENRE_FORMAT)
        if not categories and (record.values("TTCSubj") or record.values("TTCForm")):
            diagnostics.append(TgmImporter._diagnostic(TgmDiagnosticCode.UNSUPPORTED_CATEGORY, record))
        return tuple(categories)

    @staticmethod
    def _relations(
        record: TgmSourceRecord,
        field: str,
        descriptors: dict[str, TgmSourceRecord],
        diagnostics: list[TgmDiagnostic],
    ) -> tuple[str, ...]:
        resolved: list[str] = []
        for label in record.values(field):
            target = descriptors.get(label.casefold())
            if target is None:
                diagnostics.append(
                    TgmDiagnostic(
                        code=TgmDiagnosticCode.UNRESOLVED_RELATION,
                        label=record.label,
                        message=f"unresolved {field} label {label!r}",
                    )
                )
                continue
            tnr = target.first("TNR")
            assert tnr is not None
            resolved.append(f"loc-tgm:{tnr}")
        return tuple(resolved)

    @staticmethod
    def _diagnostic(
        code: TgmDiagnosticCode,
        record: TgmSourceRecord,
    ) -> TgmDiagnostic:
        return TgmDiagnostic(code=code, label=record.label, message=f"{code}: {record.label}")