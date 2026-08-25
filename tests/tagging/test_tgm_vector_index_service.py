from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from exif_turbo.data.tgm_vector_repository import TgmVectorRepository
from exif_turbo.models.ai_model_profile import DEFAULT_AI_MODEL_PROFILE
from exif_turbo.models.vocabulary import (
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
    VocabularySnapshot,
)
from exif_turbo.tagging.tgm_prompt_builder import TgmPromptBuilder
from exif_turbo.tagging.public_figure_prompt_builder import PublicFigurePromptBuilder
from exif_turbo.tagging.tgm_vector_index_service import TgmVectorIndexService
from exif_turbo.tagging.vocabulary_snapshot_repository import VocabularySnapshotRepository


def _concept(number: int, label: str) -> VocabularyConcept:
    return VocabularyConcept(
        concept_id=f"wikidata:Q{number}",
        category=VocabularyCategory.SUBJECT,
        canonical_label=label,
        localized_terms=(
            LocalizedVocabularyTerms("it", f"{label} it", (f"{label} alias it",)),
            LocalizedVocabularyTerms("fr", f"{label} fr", (f"{label} alias fr",)),
            LocalizedVocabularyTerms("en", label, (f"{label} alias en",)),
            LocalizedVocabularyTerms("de", f"{label} de", (f"{label} alias de",)),
        ),
        source_uri=f"https://www.wikidata.org/entity/Q{number}",
        license_id="CC0-1.0",
    )


def _snapshot(checksum: str = "a") -> VocabularySnapshot:
    return VocabularySnapshot(
        concepts=(_concept(1, "Forests"), _concept(2, "Deer")),
        version=1,
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
        source_name="Wikidata",
        source_dump_uri="file:///offline/wikidata.json",
        source_dump_sha256=checksum * 64,
        manifest_sha256="b" * 64,
        license_id="CC0-1.0",
    )


class _FakeEncoder:
    profile = DEFAULT_AI_MODEL_PROFILE

    def encode_texts(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        vectors = np.zeros((len(texts), 512), dtype=np.float32)
        for index in range(len(texts)):
            vectors[index, index % 512] = 1.0
        return vectors


def _service(tmp_path: Path, checksum: str = "snapshot-a") -> tuple[
    TgmVectorIndexService, TgmVectorRepository, VocabularySnapshotRepository
]:
    snapshots = VocabularySnapshotRepository(tmp_path / "snapshot.json.gz")
    snapshots.activate(_snapshot(checksum))
    vectors = TgmVectorRepository(
        tmp_path / "terms.faiss",
        tmp_path / "concepts.json",
        tmp_path / "metadata.json",
    )
    vectors.load()
    service = TgmVectorIndexService(snapshots, vectors, _FakeEncoder())  # type: ignore[arg-type]
    return service, vectors, snapshots


def test_tgm_prompt_builder_builds_bounded_prompt_for_each_locale() -> None:
    # Arrange
    concept = VocabularyConcept(
        concept_id="wikidata:Q1",
        category=VocabularyCategory.SUBJECT,
        canonical_label="Forest",
        localized_terms=(
            LocalizedVocabularyTerms("de", "Wald", ("Forst", "Gehölz")),
            LocalizedVocabularyTerms("it", "Foresta", ("Bosco",)),
            LocalizedVocabularyTerms("en", "Forest", ("Woods", "Woodland")),
            LocalizedVocabularyTerms("fr", "Forêt", ("Bois",)),
        ),
        source_uri="https://www.wikidata.org/entity/Q1",
        license_id="CC0-1.0",
    )

    # Act
    prompts = TgmPromptBuilder().build_all(concept)

    # Assert
    assert prompts == (
        ("en", "A photograph depicting Forest (aliases: Woodland, Woods)."),
        ("de", "Ein Foto mit Wald (Synonyme: Forst, Gehölz)."),
        ("fr", "Une photographie représentant Forêt (alias : Bois)."),
        ("it", "Una fotografia raffigurante Foresta (alias: Bosco)."),
    )
    assert all(
        len(prompt) <= TgmPromptBuilder.MAX_PROMPT_LENGTH
        for _locale, prompt in prompts
    )


def test_public_figure_prompt_builder_uses_names_and_aliases() -> None:
    # Arrange
    concept = VocabularyConcept(
        concept_id="wikidata:Q43274",
        category=VocabularyCategory.SUBJECT,
        canonical_label="Charles III",
        localized_terms=(
            LocalizedVocabularyTerms("en", "Charles III", ("King Charles III",)),
            LocalizedVocabularyTerms("de", "Charles III.", ("König Charles III.",)),
            LocalizedVocabularyTerms("fr", "Charles III", ("roi Charles III",)),
            LocalizedVocabularyTerms("it", "Carlo III", ("re Carlo III",)),
        ),
        source_uri="https://www.wikidata.org/entity/Q43274",
        license_id="CC0-1.0",
    )

    # Act
    prompts = PublicFigurePromptBuilder().build_all(concept)

    # Assert
    assert prompts == (
        ("en", "A photograph of Charles III (also known as: King Charles III)."),
        ("de", "Ein Foto von Charles III. (auch bekannt als: König Charles III.)."),
        ("fr", "Une photographie de Charles III (aussi connu comme : roi Charles III)."),
        ("it", "Una fotografia di Carlo III (noto anche come: re Carlo III)."),
    )


def test_tgm_vector_fingerprint_identifies_wikidata_snapshot_and_prompt_contract(
    tmp_path: Path,
) -> None:
    # Arrange
    service, _vectors, _snapshots = _service(tmp_path, "a")

    # Act
    fingerprint = service.expected_fingerprint()

    # Assert
    assert fingerprint.to_dict() == {
        "vocabulary": "wikidata",
        "snapshot_version": 1,
        "source_dump_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "prompt_version": TgmPromptBuilder.VERSION,
        "prompt_strategy": TgmPromptBuilder.STRATEGY,
        "prompt_locales": ("en", "de", "fr", "it"),
        "model_name": DEFAULT_AI_MODEL_PROFILE.model_name,
        "pretrained": DEFAULT_AI_MODEL_PROFILE.pretrained,
        "dimension": DEFAULT_AI_MODEL_PROFILE.dimension,
    }


def test_tgm_vector_index_service_fingerprint_detects_stale_snapshot(
    tmp_path: Path,
) -> None:
    # Arrange
    service, vectors, snapshots = _service(tmp_path, "a")
    service.build(batch_size=1)
    snapshots.activate(_snapshot("c"))

    # Act / Assert
    assert vectors.count == 8
    assert service.is_current() is False


def test_tgm_vector_index_service_cancellation_keeps_old_active_index(
    tmp_path: Path,
) -> None:
    # Arrange
    service, vectors, snapshots = _service(tmp_path, "a")
    service.build(batch_size=1)
    old_fingerprint = vectors.fingerprint
    snapshots.activate(_snapshot("c"))
    calls = 0

    def _cancel_after_first_batch() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    # Act
    result = service.build(batch_size=1, cancel_check=_cancel_after_first_batch)

    # Assert
    assert result.completed is False
    assert vectors.fingerprint == old_fingerprint