from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from exif_turbo.data.tgm_vector_repository import (
    TgmVectorIndexError,
    TgmVectorRepository,
)
from exif_turbo.models.tgm_vector import TgmVectorFingerprint


def _fingerprint(checksum: str = "abc") -> TgmVectorFingerprint:
    digest = (checksum * 64)[:64]
    return TgmVectorFingerprint(
        vocabulary="wikidata",
        snapshot_version=1,
        source_dump_sha256=digest,
        manifest_sha256="b" * 64,
        prompt_version=3,
        prompt_strategy="wikidata-multilingual-labels-aliases-v1",
        prompt_locales=("en", "de", "fr", "it"),
        model_name="ViT-B-32",
        pretrained="openai",
        dimension=512,
    )


def _repository(tmp_path: Path) -> TgmVectorRepository:
    repository = TgmVectorRepository(
        tmp_path / "terms.faiss",
        tmp_path / "concepts.json",
        tmp_path / "metadata.json",
    )
    repository.load()
    return repository


def _vectors() -> np.ndarray:
    vectors = np.zeros((2, 512), dtype=np.float32)
    vectors[0, 0] = 2.0
    vectors[1, 1] = 3.0
    return vectors


def _locale_rows() -> tuple[list[str], list[str]]:
    return (
        ["wikidata:Q1", "wikidata:Q1", "wikidata:Q2", "wikidata:Q2"],
        ["en", "de", "en", "de"],
    )


def test_tgm_vector_repository_replace_reload_and_search_returns_ranked_concepts(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    concept_ids = ["wikidata:Q1", "wikidata:Q2"]
    repository.replace_index(_vectors(), concept_ids, _fingerprint())
    reloaded = _repository(tmp_path)

    # Act
    hits = reloaded.search(_vectors()[0], top_k=2, threshold=0.1)

    # Assert
    assert reloaded.count == 2
    assert reloaded.fingerprint == _fingerprint()
    assert [hit.concept_id for hit in hits] == [concept_ids[0]]
    assert hits[0].score == pytest.approx(1.0)


def test_tgm_vector_repository_corrupt_index_raises_actionable_error(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    repository.replace_index(_vectors(), ["wikidata:Q1", "wikidata:Q2"], _fingerprint())
    (tmp_path / "terms.faiss").write_bytes(b"corrupt")

    # Act / Assert
    with pytest.raises(TgmVectorIndexError, match="rebuild required"):
        _repository(tmp_path)


def test_tgm_vector_repository_mismatched_map_metadata_raises_actionable_error(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    repository.replace_index(_vectors(), ["wikidata:Q1", "wikidata:Q2"], _fingerprint())
    (tmp_path / "concepts.json").write_text(json.dumps(["other"]), encoding="utf-8")

    # Act / Assert
    with pytest.raises(TgmVectorIndexError, match="mismatched"):
        _repository(tmp_path)


def test_tgm_vector_repository_partial_files_raise_incomplete_error(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "concepts.json").write_text("[]", encoding="utf-8")

    # Act / Assert
    with pytest.raises(TgmVectorIndexError, match="incomplete"):
        _repository(tmp_path)


def test_tgm_vector_repository_legacy_tgm_fingerprint_requires_rebuild(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    repository.replace_index(
        _vectors(), ["wikidata:Q1", "wikidata:Q2"], _fingerprint()
    )
    metadata_path = tmp_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema_version"] = 1
    metadata["fingerprint"] = {
        "raw_tgm_sha256": "legacy",
        "normalization_version": 1,
        "prompt_version": 1,
        "model_name": "ViT-B-32",
        "pretrained": "openai",
        "dimension": 512,
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    # Act / Assert
    with pytest.raises(TgmVectorIndexError, match="rebuild required"):
        _repository(tmp_path)


def test_tgm_vector_repository_load_for_rebuild_replaces_legacy_metadata(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    repository.replace_index(
        _vectors(), ["wikidata:Q1", "wikidata:Q2"], _fingerprint()
    )
    metadata_path = tmp_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema_version"] = 1
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    recovering = TgmVectorRepository(
        tmp_path / "terms.faiss",
        tmp_path / "concepts.json",
        metadata_path,
    )

    # Act
    recovering.load_for_rebuild()
    recovering.replace_index(
        _vectors(), ["wikidata:Q1", "wikidata:Q2"], _fingerprint("c")
    )
    reloaded = _repository(tmp_path)

    # Assert
    assert reloaded.count == 2
    assert reloaded.fingerprint == _fingerprint("c")


def test_tgm_vector_repository_non_wikidata_concept_id_is_rejected(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)

    # Act / Assert
    with pytest.raises(ValueError, match="wikidata:Q"):
        repository.replace_index(
            _vectors(), ["loc-tgm:tgm000001", "wikidata:Q2"], _fingerprint()
        )


def test_tgm_vector_repository_search_max_pools_locale_rows_before_top_k(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    vectors = np.zeros((4, 512), dtype=np.float32)
    vectors[0, :2] = (0.9, 0.1)
    vectors[1, :2] = (0.8, 0.2)
    vectors[2, :2] = (0.7, 0.3)
    vectors[3, :2] = (0.1, 0.9)
    concept_ids, locales = _locale_rows()
    repository.replace_index(vectors, concept_ids, _fingerprint(), locales=locales)
    query = np.zeros(512, dtype=np.float32)
    query[0] = 1.0

    # Act
    hits = repository.search(query, top_k=2, threshold=0.0)

    # Assert
    assert [(hit.concept_id, hit.locale) for hit in hits] == [
        ("wikidata:Q1", "en"),
        ("wikidata:Q2", "en"),
    ]


def test_tgm_vector_repository_duplicate_concept_locale_row_is_rejected(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    concept_ids, locales = _locale_rows()
    locales[1] = "en"
    vectors = np.zeros((4, 512), dtype=np.float32)
    vectors[:, 0] = 1.0

    # Act / Assert
    with pytest.raises(ValueError, match="concept and locale rows must be unique"):
        repository.replace_index(
            vectors,
            concept_ids,
            _fingerprint(),
            locales=locales,
        )