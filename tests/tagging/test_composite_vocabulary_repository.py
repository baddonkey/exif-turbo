from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from exif_turbo.models.vocabulary import (
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
    VocabularySnapshot,
)
from exif_turbo.tagging.composite_vocabulary_repository import (
    CompositeVocabularyRepository,
)
from exif_turbo.tagging.vocabulary_snapshot_repository import (
    VocabularySnapshotRepository,
)


def _repository(
    path: Path,
    concept_id: str,
    label: str,
    *,
    version: int,
) -> VocabularySnapshotRepository:
    repository = VocabularySnapshotRepository(path)
    repository.activate(
        VocabularySnapshot(
            concepts=(
                VocabularyConcept(
                    concept_id=concept_id,
                    category=VocabularyCategory.SUBJECT,
                    canonical_label=label,
                    localized_terms=tuple(
                        LocalizedVocabularyTerms(locale, label)
                        for locale in ("en", "de", "fr", "it")
                    ),
                    source_uri=(
                        "https://www.wikidata.org/entity/"
                        f"{concept_id.removeprefix('wikidata:')}"
                    ),
                    license_id="CC0-1.0",
                ),
            ),
            version=version,
            created_at=datetime(2026, 8, 25, tzinfo=UTC),
            source_name="Wikidata",
            source_dump_uri=f"file:///snapshot-{version}.jsonl",
            source_dump_sha256=str(version) * 64,
            manifest_sha256=str(version + 1) * 64,
            license_id="CC0-1.0",
        )
    )
    return repository


def test_composite_repository_identity_lookup_returns_owning_snapshot(
    tmp_path: Path,
) -> None:
    # Arrange
    generic = _repository(
        tmp_path / "generic.json.gz", "wikidata:Q1", "Monarch", version=1
    )
    identities = _repository(
        tmp_path / "identities.json.gz",
        "wikidata:Q43274",
        "Charles III",
        version=2,
    )
    repository = CompositeVocabularyRepository(generic, identities)

    # Act
    concept = repository.get("wikidata:Q43274")
    snapshot = repository.snapshot_for("wikidata:Q43274")

    # Assert
    assert concept is not None
    assert concept.canonical_label == "Charles III"
    assert snapshot is not None
    assert snapshot.version == 2