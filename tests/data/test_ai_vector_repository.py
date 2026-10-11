"""Tests for AiVectorRepository — add, save, load, remove_folder, incremental skip."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from exif_turbo.data.ai_vector_repository import (
    AiVectorIndexError,
    AiVectorRepository,
    _is_inside,
)
from exif_turbo.models.ai_model_profile import AiModelProfile, DEFAULT_AI_MODEL_PROFILE
from exif_turbo.data.ai_vector_storage import AiVectorAuthenticationError, AiVectorStorage


# ── helpers ──────────────────────────────────────────────────────────────────

def _random_vec(dim: int = 512) -> np.ndarray:
    v = np.random.default_rng(0).random((dim,)).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


def _make_repo(tmp_path: Path, key: str = "") -> AiVectorRepository:
    repo = AiVectorRepository(
        tmp_path / "ai_index.faiss",
        tmp_path / "ai_id_map.json",
        key=key,
    )
    repo.load()
    return repo


# ── load / save round-trip ────────────────────────────────────────────────────

def test_ai_vector_storage_round_trip_hides_plaintext(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "test-password")
    expected = (b"vector-content", b"/private/photo.jpg", b"model-metadata")

    # Act
    storage.save(*expected)

    # Assert
    assert storage.load() == expected
    assert all(part not in storage.path.read_bytes() for part in expected)


def test_ai_vector_storage_multichunk_snapshot_preserves_legacy_reader_compatibility(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "test-password")
    expected = (b"vectors" * 400000, b"paths" * 300000, b"metadata")

    # Act
    storage.save(*expected)

    # Assert
    assert storage.load() == expected
    assert storage._decode(storage.path.read_bytes(), storage._crypto()) == expected


def test_ai_vector_storage_legacy_ciphertext_loads_with_streaming_reader(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "test-password")
    expected = (b"vectors" * 400000, b"paths", b"metadata")
    payload = storage._MAGIC + storage._LENGTHS.pack(len(expected[1]), len(expected[2]))
    payload += expected[1] + expected[2] + expected[0]
    storage.path.write_bytes(storage._crypto().encrypt(payload))

    # Act
    actual = storage.load()

    # Assert
    assert actual == expected


def test_ai_vector_storage_truncated_tag_rejects_multichunk_snapshot(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "test-password")
    storage.save(b"vectors" * 400000, b"paths", b"metadata")
    storage.path.write_bytes(storage.path.read_bytes()[:-1])

    # Act / Assert
    with pytest.raises(AiVectorAuthenticationError):
        storage.load()
    with pytest.raises(AiVectorAuthenticationError):
        storage.verify()


def test_ai_vector_storage_tampered_header_is_authentication_not_format_error(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "test-password")
    storage.save(b"vectors" * 400000, b"paths", b"metadata")
    ciphertext = bytearray(storage.path.read_bytes())
    ciphertext[12] ^= 1
    storage.path.write_bytes(ciphertext)

    # Act / Assert
    with pytest.raises(AiVectorAuthenticationError):
        storage.load()
    with pytest.raises(AiVectorAuthenticationError):
        storage.verify()


def test_ai_vector_storage_wrong_password_rejects_snapshot(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "test-password")
    storage.save(b"vectors", b"paths", b"metadata")
    wrong = AiVectorStorage(tmp_path / "ai_index.faiss", "wrong-password")

    # Act / Assert
    with pytest.raises(AiVectorAuthenticationError):
        wrong.load()


def test_ai_vector_storage_interrupted_save_preserves_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "test-password")
    original = (b"vectors", b"paths", b"metadata")
    storage.save(*original)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated interrupted publication")

    # Act
    with monkeypatch.context() as patch:
        patch.setattr("exif_turbo.data.ai_vector_storage.os.replace", fail_replace)
        with pytest.raises(OSError, match="interrupted publication"):
            storage.save(b"new-vectors", b"new-paths", b"new-metadata")

    # Assert
    assert storage.load() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_ai_vector_repository_encrypted_round_trip_preserves_views(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path, "test-password")
    expected = _random_vec()
    repo.add_images(np.stack([expected, expected]), ["/private/a.jpg"] * 2,
                    view_ids=["full", "top_left"])

    # Act
    repo.save()
    loaded = _make_repo(tmp_path, "test-password")

    # Assert
    assert set(loaded.get_view_vectors("/private/a.jpg")) == {"full", "top_left"}
    assert np.allclose(loaded.get_vector("/private/a.jpg"), expected)
    assert not (tmp_path / "ai_index.faiss").exists()
    assert not (tmp_path / "ai_id_map.json").exists()
    assert not (tmp_path / "ai_index_meta.json").exists()


def test_ai_vector_repository_plaintext_load_migrates_snapshot(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    expected = _random_vec()
    repo.add_images(expected, ["/private/a.jpg"])
    repo.save()

    # Act
    migrated = _make_repo(tmp_path, "test-password")

    # Assert
    assert np.allclose(migrated.get_vector("/private/a.jpg"), expected)
    assert (tmp_path / "ai_index.faiss.enc").exists()
    assert not (tmp_path / "ai_id_map.json").exists()


def test_ai_vector_repository_tampering_rejects_plaintext_fallback(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec(), ["/private/a.jpg"])
    repo.save()
    legacy = {path: path.read_bytes() for path in tmp_path.glob("*.*")}
    _make_repo(tmp_path, "test-password")
    for path, content in legacy.items():
        path.write_bytes(content)
    encrypted = tmp_path / "ai_index.faiss.enc"
    content = bytearray(encrypted.read_bytes())
    content[-1] ^= 1
    encrypted.write_bytes(content)

    # Act / Assert
    with pytest.raises(AiVectorAuthenticationError, match="authentication"):
        _make_repo(tmp_path, "test-password")

    assert all(path.exists() for path in legacy)


def test_ai_vector_storage_password_change_preserves_snapshot(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "old-password")
    expected = (b"vectors", b"paths", b"metadata")
    storage.save(*expected)
    encrypted = storage.path.read_bytes()

    # Act
    storage.change_password("new-password")

    # Assert
    assert storage.load() == expected
    assert storage.path.read_bytes() == encrypted
    with pytest.raises(AiVectorAuthenticationError):
        AiVectorStorage(tmp_path / "ai_index.faiss", "old-password").load()


def test_ai_vector_storage_staged_password_change_recovers_after_rekey(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "old-password")
    expected = (b"vectors", b"paths", b"metadata")
    storage.save(*expected)
    storage.stage_password_change("new-password")

    # Act
    recovered = AiVectorStorage(tmp_path / "ai_index.faiss", "new-password")

    # Assert
    assert recovered.load() == expected
    assert not (storage.key_dir / "password.pending").exists()


def test_ai_vector_storage_interrupted_migration_retains_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    paths = (tmp_path / "ai_index.faiss", tmp_path / "ai_id_map.json", tmp_path / "ai_index_meta.json")
    original = (b"vectors", b"private-path", b"model")
    for path, data in zip(paths, original):
        path.write_bytes(data)
    storage = AiVectorStorage(paths[0], "test-password")
    storage._crypto()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated migration interruption")

    monkeypatch.setattr("exif_turbo.data.ai_vector_storage.os.replace", fail_replace)

    # Act / Assert
    with pytest.raises(OSError, match="migration interruption"):
        storage.migrate(*paths)
    assert tuple(path.read_bytes() for path in paths) == original


def test_ai_vector_storage_missing_key_rejects_without_recreation(tmp_path: Path) -> None:
    # Arrange
    storage = AiVectorStorage(tmp_path / "ai_index.faiss", "test-password")
    storage.save(b"vectors", b"paths", b"metadata")
    key_path = storage.key_dir / ".thumb_key"
    key_path.unlink()

    # Act / Assert
    with pytest.raises(AiVectorAuthenticationError, match="missing"):
        storage.load()
    assert not key_path.exists()


def test_ai_vector_repository_encrypted_index_requires_password(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path, "test-password")
    repo.save()

    # Act / Assert
    with pytest.raises(AiVectorAuthenticationError, match="password"):
        _make_repo(tmp_path)


def test_ai_vector_storage_migration_cleans_legacy_temporary_files(tmp_path: Path) -> None:
    # Arrange
    paths = (tmp_path / "ai_index.faiss", tmp_path / "ai_id_map.json", tmp_path / "ai_index_meta.json")
    storage = AiVectorStorage(paths[0], "test-password")
    storage.save(b"vectors", b"paths", b"metadata")
    temporary = tmp_path / ".ai_id_map.json.interrupted.tmp"
    temporary.write_bytes(b"private path from interrupted legacy save")

    # Act
    storage.migrate(*paths)

    # Assert
    assert not temporary.exists()
    assert storage.load() == (b"vectors", b"paths", b"metadata")


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


def test_ai_vector_repository_save_writes_model_metadata(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec(), ["/photos/a.jpg"])

    # Act
    repo.save()
    metadata = json.loads(
        (tmp_path / "ai_index_meta.json").read_text(encoding="utf-8")
    )

    # Assert
    assert metadata["model_fingerprint"] == DEFAULT_AI_MODEL_PROFILE.identifier
    assert metadata["dimension"] == 512
    assert metadata["count"] == 1
    assert metadata["image_count"] == 1
    assert metadata["view_strategy"] == "full-plus-four-corners-v1"


def test_ai_vector_repository_load_legacy_index_requires_full_rescan(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec(), ["/photos/a.jpg"])
    repo.save()
    (tmp_path / "ai_index_meta.json").unlink()

    # Act / Assert
    with pytest.raises(AiVectorIndexError, match="AI Full Rescan"):
        _make_repo(tmp_path)


def test_ai_vector_repository_load_different_model_requires_full_rescan(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec(), ["/photos/a.jpg"])
    repo.save()
    other_profile = AiModelProfile(
        identifier="other-model-v1",
        model_name="other-model",
        pretrained="weights",
        dimension=512,
    )
    other_repo = AiVectorRepository(
        tmp_path / "ai_index.faiss",
        tmp_path / "ai_id_map.json",
        profile=other_profile,
    )

    # Act / Assert
    with pytest.raises(AiVectorIndexError, match="AI Full Rescan"):
        other_repo.load()


# ── add_images ────────────────────────────────────────────────────────────────

def test_ai_vector_repository_batch_append_rejects_existing_view_without_mutation(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec(), ["/photos/a.jpg"], view_ids=["full"])
    repo.add_images(_random_vec(), ["/photos/a.jpg"], view_ids=["top_left"])

    # Act / Assert
    with pytest.raises(ValueError, match="already indexed"):
        repo.add_images(np.stack([_random_vec(), _random_vec()]),
                        ["/photos/new.jpg", "/photos/a.jpg"], view_ids=["full", "full"])
    assert repo.get_indexed_paths() == {"/photos/a.jpg"}
    assert set(repo.get_view_vectors("/photos/a.jpg")) == {"full", "top_left"}


def test_ai_vector_repository_removed_views_can_be_reindexed(tmp_path: Path) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_random_vec(), ["/photos/a.jpg"])
    repo.remove_folder("/photos")

    # Act
    repo.add_images(_random_vec(), ["/photos/a.jpg"])

    # Assert
    assert repo.get_indexed_paths() == {"/photos/a.jpg"}


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


def test_ai_vector_repository_get_view_vectors_returns_all_views_for_path(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    full = _random_vec()
    crop = np.roll(full, 1)
    repo.add_images(
        np.stack([full, crop]),
        ["/photos/a.jpg", "/photos/a.jpg"],
        view_ids=["full", "top_left"],
    )

    # Act
    actual = repo.get_view_vectors("/photos/a.jpg")

    # Assert
    assert tuple(actual) == ("full", "top_left")
    assert np.allclose(actual["full"], full)
    assert np.allclose(actual["top_left"], crop)


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


def test_ai_vector_repository_search_max_pools_views_before_top_k(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    query = np.zeros(512, dtype=np.float32)
    query[0] = 1.0
    vectors = np.zeros((4, 512), dtype=np.float32)
    vectors[0, :2] = (0.9, 0.1)
    vectors[1, :2] = (0.8, 0.2)
    vectors[2, :2] = (0.7, 0.3)
    vectors[3, :2] = (0.1, 0.9)
    repo.add_images(
        vectors,
        ["/photos/a.jpg", "/photos/a.jpg", "/photos/b.jpg", "/photos/b.jpg"],
        view_ids=["full", "top_left", "full", "top_left"],
    )

    # Act
    results = repo.search(query, top_k=2, threshold=0.0)

    # Assert
    assert [path for path, _score in results] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
    ]


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
