from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from exif_turbo.models.tgm import TgmCategory, TgmConcept, TgmSnapshot, TgmSourceFormat
from exif_turbo.models.tgm_localization import (
    TgmConceptLocalization,
    TgmLocalizationPack,
)
from exif_turbo.tagging.tgm_localization_repository import TgmLocalizationRepository
from exif_turbo.tagging.tgm_localization_service import TgmLocalizationService
from exif_turbo.tagging.tgm_snapshot_repository import TgmSnapshotRepository


def _pack(*records: TgmConceptLocalization) -> TgmLocalizationPack:
    return TgmLocalizationPack(
        records=records,
        version=1,
        created_at=datetime(2026, 8, 22, tzinfo=UTC),
        source_uri="https://example.test/tgm-localizations",
        license_id="CC0-1.0",
    )


def _service(tmp_path: Path) -> TgmLocalizationService:
    snapshots = TgmSnapshotRepository(tmp_path / "snapshot.json.gz")
    snapshots.activate(
        TgmSnapshot(
            concepts=(
                TgmConcept(
                    concept_id="loc-tgm:tgm000001",
                    tnr="tgm000001",
                    label="Golden eagles",
                    categories=(TgmCategory.SUBJECT,),
                    aliases=("Aquila chrysaetos",),
                ),
            ),
            diagnostics=(),
            source_url="https://example.test/tgm.xml",
            source_format=TgmSourceFormat.XML,
            distribution_date=None,
            imported_at=datetime(2026, 8, 22, tzinfo=UTC),
            raw_sha256="snapshot",
            raw_size_bytes=100,
        )
    )
    localizations = TgmLocalizationRepository(tmp_path / "localizations.json.gz")
    localizations.activate(
        _pack(
            TgmConceptLocalization(
                concept_id="loc-tgm:tgm000001",
                locale="de",
                preferred_label="Steinadler",
                aliases=("Goldadler",),
                source_uri="https://example.test/de",
                license_id="CC0-1.0",
                translation_method="manual",
                review_status="human-reviewed",
            ),
            TgmConceptLocalization(
                concept_id="loc-tgm:tgm000001",
                locale="fr",
                preferred_label="Aigles royaux",
            ),
        )
    )
    return TgmLocalizationService(snapshots, localizations)


def test_tgm_localization_repository_activate_round_trips_pack(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "localizations.json.gz"
    repository = TgmLocalizationRepository(path)
    pack = _pack(
        TgmConceptLocalization(
            concept_id="loc-tgm:tgm000001",
            locale="de",
            preferred_label="Steinadler",
        )
    )

    # Act
    repository.activate(pack)
    reloaded = TgmLocalizationRepository(path).load()

    # Assert
    assert reloaded == pack
    assert repository.checksum


def test_tgm_localization_service_install_pack_validates_canonical_ids(
    tmp_path: Path,
) -> None:
    # Arrange
    service = _service(tmp_path)
    source = tmp_path / "incoming.json.gz"
    TgmLocalizationRepository(source).activate(
        _pack(
            TgmConceptLocalization(
                concept_id="loc-tgm:tgm999999",
                locale="de",
                preferred_label="Unbekannt",
            )
        )
    )

    # Act / Assert
    with pytest.raises(ValueError, match="unknown TGM concept"):
        service.install_pack(str(source))
    assert service.display_label("loc-tgm:tgm000001", "de") == "Steinadler"


def test_tgm_localization_service_install_pack_activates_valid_file(
    tmp_path: Path,
) -> None:
    # Arrange
    service = _service(tmp_path)
    source = tmp_path / "incoming.json.gz"
    pack = _pack(
        TgmConceptLocalization(
            concept_id="loc-tgm:tgm000001",
            locale="it",
            preferred_label="Aquile reali",
        )
    )
    TgmLocalizationRepository(source).activate(pack)

    # Act
    installed = service.install_pack(str(source))

    # Assert
    assert installed == pack
    assert service.display_label("loc-tgm:tgm000001", "it") == "Aquile reali"


def test_tgm_localization_pack_duplicate_concept_locale_raises_error() -> None:
    # Arrange
    record = TgmConceptLocalization(
        concept_id="loc-tgm:tgm000001",
        locale="de",
        preferred_label="Steinadler",
    )

    # Act / Assert
    with pytest.raises(ValueError, match="duplicate concept locales"):
        _pack(record, record)


def test_tgm_localization_service_missing_locale_returns_canonical_label(
    tmp_path: Path,
) -> None:
    # Arrange
    service = _service(tmp_path)

    # Act
    label = service.display_label("loc-tgm:tgm000001", "it")

    # Assert
    assert label == "Golden eagles"


def test_tgm_localization_service_search_localized_alias_returns_canonical_concept(
    tmp_path: Path,
) -> None:
    # Arrange
    service = _service(tmp_path)

    # Act
    concepts = service.search("Goldadler", "de")

    # Assert
    assert [concept.concept_id for concept in concepts] == ["loc-tgm:tgm000001"]


def test_tgm_localization_service_all_labels_contains_every_locale(
    tmp_path: Path,
) -> None:
    # Arrange
    service = _service(tmp_path)

    # Act
    labels = service.all_localized_labels("loc-tgm:tgm000001")

    # Assert
    assert labels == ("Steinadler", "Goldadler", "Aigles royaux")


def test_tgm_localization_service_search_labels_groups_by_canonical_concept(
    tmp_path: Path,
) -> None:
    # Arrange
    service = _service(tmp_path)

    # Act
    labels = service.search_labels_by_concept()

    # Assert
    assert labels == {
        "loc-tgm:tgm000001": ("Steinadler", "Goldadler", "Aigles royaux")
    }