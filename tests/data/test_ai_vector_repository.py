"""Tests for AiVectorRepository — add, save, load, remove_folder, incremental skip."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from exif_turbo.data.ai_vector_repository import AiVectorRepository, _is_inside


# ── helpers ──────────────────────────────────────────────────────────────────

def _random_vec(dim: int = 512) -> np.ndarray:
    v = np.random.default_rng(0).random((dim,)).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


def _make_repo(tmp_path: Path) -> AiVectorRepository:
    repo = AiVectorRepository(
        tmp_path / "ai_index.faiss",
        tmp_path / "ai_id_map.json",
    )
    repo.load()
    return repo


# ── load / save round-trip ────────────────────────────────────────────────────

def test_ai_vector_repository_empty_load_creates_index(tmp_path: Path) -> None:
    # Arrange / Act
    repo = _make_repo(tmp_path)

    # Assert
    assert repo.get_indexed_paths() == set()


def test_ai_vector_repository_save_and_reload_preserves_vectors(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    vec = _random_vec()
    repo.add_images(vec.reshape(1, -1), ["/photos/a.jpg"])

    # Act
    repo.save()
    repo2 = _make_repo(tmp_path)

    # Assert
    assert "/photos/a.jpg" in repo2.get_indexed_paths()


# ── add_images ────────────────────────────────────────────────────────────────

def test_ai_vector_repository_add_images_increases_index_size(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    vecs = np.stack([_random_vec() for _ in range(3)])
    paths = ["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"]

    # Act
    repo.add_images(vecs, paths)

    # Assert
    assert repo.get_indexed_paths() == set(paths)


def test_ai_vector_repository_add_images_single_vec_without_batch_dim(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)

    # Act — 1-D vector (shape 512,) should be accepted
    repo.add_images(_random_vec(), ["/photos/single.jpg"])

    # Assert
    assert "/photos/single.jpg" in repo.get_indexed_paths()


# ── incremental skip ──────────────────────────────────────────────────────────

def test_ai_vector_repository_get_indexed_paths_reflects_added_entries(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec().reshape(1, -1), ["/photos/x.jpg"])

    # Act — caller uses get_indexed_paths() to skip already-vectorised images
    already = repo.get_indexed_paths()

    # Assert
    assert "/photos/x.jpg" in already
    assert "/photos/new.jpg" not in already


def test_ai_vector_repository_get_vector_returns_reconstructed_vector(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    expected = _random_vec()
    repo.add_images(expected, ["/photos/a.jpg"])

    # Act
    actual = repo.get_vector("/photos/a.jpg")

    # Assert
    assert actual is not None
    assert np.allclose(actual, expected)


def test_ai_vector_repository_get_vectors_returns_found_and_missing_paths(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    expected = _random_vec()
    repo.add_images(expected, ["/photos/a.jpg"])

    # Act
    actual = repo.get_vectors(["/photos/missing.jpg", "/photos/a.jpg"])

    # Assert
    assert actual["/photos/missing.jpg"] is None
    assert actual["/photos/a.jpg"] is not None
    assert np.allclose(actual["/photos/a.jpg"], expected)


# ── remove_folder ─────────────────────────────────────────────────────────────

def test_ai_vector_repository_remove_folder_drops_all_paths_in_folder(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    inside = ["/animals/cat.jpg", "/animals/dog.jpg"]
    outside = ["/photos/x.jpg"]
    all_paths = inside + outside
    vecs = np.stack([_random_vec() for _ in all_paths])
    repo.add_images(vecs, all_paths)

    # Act
    repo.remove_folder("/animals")

    # Assert
    remaining = repo.get_indexed_paths()
    assert remaining == set(outside)


def test_ai_vector_repository_remove_folder_noop_when_no_match(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec().reshape(1, -1), ["/photos/a.jpg"])

    # Act
    repo.remove_folder("/other")

    # Assert — unchanged
    assert "/photos/a.jpg" in repo.get_indexed_paths()


def test_ai_vector_repository_remove_folder_all_entries_empties_index(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec().reshape(1, -1), ["/animals/cat.jpg"])

    # Act
    repo.remove_folder("/animals")

    # Assert
    assert repo.get_indexed_paths() == set()


# ── search ────────────────────────────────────────────────────────────────────

def test_ai_vector_repository_search_returns_nearest_path(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    query = _random_vec()
    # Add the query itself (perfect cosine sim = 1.0) plus a random other vec.
    other = np.random.default_rng(42).random(512).astype(np.float32)
    other /= np.linalg.norm(other)
    vecs = np.stack([query, other])
    repo.add_images(vecs, ["/photos/exact.jpg", "/photos/other.jpg"])

    # Act
    results = repo.search(query, top_k=2)

    # Assert — exact match is top hit
    assert results[0][0] == "/photos/exact.jpg"
    assert results[0][1] == pytest.approx(1.0, abs=1e-5)


def test_ai_vector_repository_search_empty_index_returns_empty(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)

    # Act
    results = repo.search(_random_vec())

    # Assert
    assert results == []


def test_ai_vector_repository_search_filtered_top_k_none_returns_all_matches(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    vec_a = _random_vec()
    vec_b = _random_vec()
    repo.add_images(
        np.stack([vec_a, vec_b]),
        ["/photos/a.jpg", "/photos/b.jpg"],
    )
    allowed = {"/photos/a.jpg", "/photos/b.jpg"}

    # Act
    results = repo.search_filtered(
        vec_a,
        allowed,
        top_k=None,
        threshold=0.0,
    )

    # Assert
    assert {path for path, _score in results} == allowed


def test_ai_vector_repository_search_filtered_adapts_candidate_pool_for_sparse_scope(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    query = _random_vec()
    rng = np.random.default_rng(123)
    distractors: list[np.ndarray] = []
    distractor_paths: list[str] = []
    for i in range(1700):
        vec = rng.random(512).astype(np.float32)
        vec /= np.linalg.norm(vec)
        distractors.append(vec)
        distractor_paths.append(f"/photos/distractor_{i}.jpg")

    allowed_paths = ["/photos/allowed_1.jpg", "/photos/allowed_2.jpg"]
    vecs = np.vstack([query, query, *distractors])
    repo.add_images(vecs, [*allowed_paths, *distractor_paths])

    # Act
    results = repo.search_filtered(
        query,
        set(allowed_paths),
        top_k=2,
        threshold=0.0,
    )

    # Assert
    assert len(results) == 2
    assert {path for path, _score in results} == set(allowed_paths)


def test_ai_vector_repository_search_filtered_returns_no_more_than_top_k(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    query = _random_vec()
    rng = np.random.default_rng(321)

    allowed_paths = [f"/photos/allowed_{i}.jpg" for i in range(5)]
    allowed_vecs = [query for _ in allowed_paths]
    distractor_vecs: list[np.ndarray] = []
    distractor_paths: list[str] = []
    for i in range(400):
        vec = rng.random(512).astype(np.float32)
        vec /= np.linalg.norm(vec)
        distractor_vecs.append(vec)
        distractor_paths.append(f"/photos/distractor_{i}.jpg")

    vecs = np.vstack([*allowed_vecs, *distractor_vecs])
    repo.add_images(vecs, [*allowed_paths, *distractor_paths])

    # Act
    results = repo.search_filtered(
        query,
        set(allowed_paths),
        top_k=3,
        threshold=0.0,
    )

    # Assert
    assert len(results) == 3
    assert {path for path, _score in results}.issubset(set(allowed_paths))


# ── _is_inside helper ─────────────────────────────────────────────────────────

def test_is_inside_direct_child_returns_true() -> None:
    assert _is_inside("/photos/cat.jpg", Path("/photos")) is True


def test_is_inside_nested_child_returns_true() -> None:
    assert _is_inside("/photos/2024/cat.jpg", Path("/photos")) is True


def test_is_inside_sibling_folder_returns_false() -> None:
    assert _is_inside("/other/cat.jpg", Path("/photos")) is False


def test_is_inside_prefix_overlap_returns_false() -> None:
    # /photos2 must not match /photos
    assert _is_inside("/photos2/cat.jpg", Path("/photos")) is False
