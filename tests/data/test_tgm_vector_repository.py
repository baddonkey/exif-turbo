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
    return TgmVectorFingerprint(checksum, 1, 1, "ViT-B-32", "openai", 512)


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


def test_tgm_vector_repository_replace_reload_and_search_returns_ranked_concepts(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    concept_ids = ["loc-tgm:tgm000001", "loc-tgm:tgm000002"]
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
    repository.replace_index(_vectors(), ["a", "b"], _fingerprint())
    (tmp_path / "terms.faiss").write_bytes(b"corrupt")

    # Act / Assert
    with pytest.raises(TgmVectorIndexError, match="rebuild required"):
        _repository(tmp_path)


def test_tgm_vector_repository_mismatched_map_metadata_raises_actionable_error(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = _repository(tmp_path)
    repository.replace_index(_vectors(), ["a", "b"], _fingerprint())
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