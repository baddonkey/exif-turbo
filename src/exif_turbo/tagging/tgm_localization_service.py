from __future__ import annotations

from pathlib import Path

from ..models.tgm import TgmConcept
from ..models.tgm_localization import TgmLocalizationPack
from .tgm_localization_repository import TgmLocalizationRepository
from .tgm_snapshot_repository import TgmSnapshotRepository


class TgmLocalizationService:
    def __init__(
        self,
        snapshots: TgmSnapshotRepository,
        localizations: TgmLocalizationRepository,
    ) -> None:
        self._snapshots = snapshots
        self._localizations = localizations

    def display_label(self, concept_id: str, locale: str) -> str:
        localized = self._localizations.get(concept_id, locale)
        if localized is not None:
            return localized.preferred_label
        concept = self._snapshots.get(concept_id)
        return "" if concept is None else concept.label

    def localized_aliases(self, concept_id: str, locale: str) -> tuple[str, ...]:
        localized = self._localizations.get(concept_id, locale)
        return () if localized is None else localized.aliases

    def all_localized_labels(self, concept_id: str) -> tuple[str, ...]:
        values: list[str] = []
        for record in self._localizations.records_for(concept_id):
            values.append(record.preferred_label)
            values.extend(record.aliases)
        return tuple(values)

    def search_labels_by_concept(self) -> dict[str, tuple[str, ...]]:
        pack = self._localizations.load()
        if pack is None:
            return {}
        concept_ids = {record.concept_id for record in pack.records}
        return {
            concept_id: self.all_localized_labels(concept_id)
            for concept_id in concept_ids
        }

    def export_labels(
        self,
        concept_id: str,
        canonical_label: str,
        *,
        mode: str,
        interface_locale: str,
        selected_locales: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        if mode == "canonical":
            return (canonical_label,)
        if mode == "interface":
            return (self.display_label(concept_id, interface_locale) or canonical_label,)
        if mode != "selected":
            raise ValueError(f"unsupported tag export mode: {mode}")
        labels: list[str] = []
        for locale in selected_locales:
            if locale == "en":
                labels.append(canonical_label)
                continue
            localized = self._localizations.get(concept_id, locale)
            if localized is not None:
                labels.append(localized.preferred_label)
        return tuple(labels) or (canonical_label,)

    def install_pack(self, source: str) -> TgmLocalizationPack:
        pack = TgmLocalizationRepository.read_pack(Path(source))
        unknown = sorted(
            {
                record.concept_id
                for record in pack.records
                if self._snapshots.get(record.concept_id) is None
            }
        )
        if unknown:
            raise ValueError(
                f"localization pack references unknown TGM concept: {unknown[0]}"
            )
        self._localizations.activate(pack)
        return pack

    def search(
        self,
        query: str,
        locale: str,
        limit: int = 20,
    ) -> tuple[TgmConcept, ...]:
        normalized = query.strip().casefold()
        if not normalized or limit <= 0:
            return ()
        matches: list[tuple[int, str, TgmConcept]] = []
        for concept in self._snapshots.list_selectable():
            localized = self._localizations.get(concept.concept_id, locale)
            labels = [concept.label, *concept.aliases]
            if localized is not None:
                labels.extend((localized.preferred_label, *localized.aliases))
            folded = tuple(label.casefold() for label in labels)
            if not any(normalized in label for label in folded):
                continue
            rank = 0 if any(label.startswith(normalized) for label in folded) else 1
            display = self.display_label(concept.concept_id, locale)
            matches.append((rank, display.casefold(), concept))
        matches.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in matches[:limit])