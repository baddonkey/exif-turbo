from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from exif_turbo.models.vocabulary import (
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
    VocabularySnapshot,
)
from exif_turbo.tagging.vocabulary_snapshot_repository import (
    VocabularySnapshotRepository,
)


def _concept(
    qid: int,
    english: str,
    german: str,
    french: str,
    italian: str,
    *,
    english_aliases: tuple[str, ...] | None = None,
) -> VocabularyConcept:
    return VocabularyConcept(
        concept_id=f"wikidata:Q{qid}",
        category=VocabularyCategory.SUBJECT,
        canonical_label=english,
        localized_terms=(
            LocalizedVocabularyTerms("it", italian),
            LocalizedVocabularyTerms("fr", french),
            LocalizedVocabularyTerms(
                "en",
                english,
                english_aliases or (f"{english} alias",),
            ),
            LocalizedVocabularyTerms("de", german, (f"{german} Alias",)),
        ),
        source_uri=f"https://www.wikidata.org/entity/Q{qid}",
        license_id="CC0-1.0",
    )


def _snapshot() -> VocabularySnapshot:
    return VocabularySnapshot(
        concepts=(
            _concept(2, "Mountain", "Berg", "Montagne", "Montagna"),
            _concept(1, "Forest", "Wald", "Forêt", "Foresta"),
        ),
        version=1,
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
        source_name="Wikidata",
        source_dump_uri="file:///offline/wikidata.json",
        source_dump_sha256="a" * 64,
        manifest_sha256="b" * 64,
        license_id="CC0-1.0",
    )


def test_vocabulary_snapshot_repository_activate_is_byte_deterministic(
    tmp_path: Path,
) -> None:
    # Arrange
    path = tmp_path / "wikidata-vocabulary.json.gz"
    repository = VocabularySnapshotRepository(path)
    snapshot = _snapshot()

    # Act
    repository.activate(snapshot)
    first = path.read_bytes()
    repository.activate(snapshot)
    second = path.read_bytes()

    # Assert
    assert second == first
    assert repository.load() == snapshot


def test_vocabulary_snapshot_repository_locale_search_uses_requested_locale_only(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = VocabularySnapshotRepository(tmp_path / "snapshot.json.gz")
    repository.activate(_snapshot())

    # Act
    german_results = repository.search("wald alias", "de")
    english_in_german_results = repository.search("forest", "de")

    # Assert
    assert tuple(concept.concept_id for concept in german_results) == (
        "wikidata:Q1",
    )
    assert english_in_german_results == ()


def test_vocabulary_snapshot_repository_search_ranks_exact_preferred_label_first(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = VocabularySnapshotRepository(tmp_path / "snapshot.json.gz")
    snapshot = VocabularySnapshot(
        concepts=(
            _concept(
                1,
                "Acrochordidae",
                "Warzenschlangen",
                "Acrochordidae",
                "Acrocordidi",
                english_aliases=("dog-faced water snake",),
            ),
            _concept(2, "dog", "Hund", "chien", "cane"),
        ),
        version=1,
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
        source_name="Wikidata",
        source_dump_uri="file:///offline/wikidata.json",
        source_dump_sha256="a" * 64,
        manifest_sha256="b" * 64,
        license_id="CC0-1.0",
    )
    repository.activate(snapshot)

    # Act
    results = repository.search("dog", "en")

    # Assert
    assert tuple(concept.concept_id for concept in results) == (
        "wikidata:Q2",
        "wikidata:Q1",
    )


def test_vocabulary_snapshot_repository_resolve_label_requires_available_locale(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = VocabularySnapshotRepository(tmp_path / "snapshot.json.gz")
    repository.activate(_snapshot())

    # Act / Assert
    assert repository.resolve_label("FORÊT", "fr") == repository.get("wikidata:Q1")
    with pytest.raises(ValueError, match="required locale"):
        repository.resolve_label("Forest", "es")