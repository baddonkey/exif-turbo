"""Tests for encrypted Vec1 vector storage and retrieval."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
import pytest
import sqlcipher3

from exif_turbo.data._connection import open_encrypted_connection
from exif_turbo.data.ai_vec1_repository import (
    AiVec1IndexError,
    AiVec1Repository,
    AiVec1TrainingCanceled,
)
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.ai_model_profile import (
    DEFAULT_AI_MODEL_PROFILE,
    LEGACY_OPENAI_CLIP_PROFILE,
    AiModelProfile,
)

_DATABASE_KEY = "test-vec1-database-password"


@pytest.fixture
def vec1_extension_path() -> Path:
    # The native extension is built per platform and supplied by the test job.
    extension_value = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not extension_value:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")
    extension_path = Path(extension_value)
    if not extension_path.is_file():
        pytest.fail("EXIF_TURBO_VEC1_EXTENSION does not point to a file")
    return extension_path


def _create_indexed_images(db_path: Path, image_paths: list[Path]) -> None:
    repository = ImageIndexRepository(db_path, key=_DATABASE_KEY)
    try:
        for image_path in image_paths:
            repository.upsert_image(
                str(image_path),
                image_path.name,
                1.0,
                100,
                {},
                "",
            )
    finally:
        repository.close()


def _make_repository(
    db_path: Path,
    extension_path: Path,
    *,
    profile: AiModelProfile = DEFAULT_AI_MODEL_PROFILE,
) -> AiVec1Repository:
    repository = AiVec1Repository(
        db_path,
        _DATABASE_KEY,
        extension_path,
        profile=profile,
    )
    repository.load()
    return repository


def test_ai_vec1_repository_search_pools_views_and_applies_scope(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image_a = tmp_path / "photos" / "a.jpg"
    image_b = tmp_path / "photos" / "b.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image_a, image_b])
    repository = _make_repository(db_path, vec1_extension_path)
    query = np.zeros(DEFAULT_AI_MODEL_PROFILE.dimension, dtype=np.float32)
    query[0] = 1.0
    second_view = np.zeros_like(query)
    second_view[1] = 1.0
    diagonal = np.zeros_like(query)
    diagonal[0] = 0.8
    diagonal[1] = 0.6

    try:
        repository.add_images(
            np.stack([query, second_view, diagonal]),
            [str(image_a), str(image_a), str(image_b)],
            view_ids=["full", "top_left", "full"],
        )

        # Act
        results = repository.search(query, threshold=0.5)
        scoped_results = repository.search_filtered(
            query,
            {str(image_b)},
            top_k=1,
            threshold=0.5,
        )

        # Assert
        assert [path for path, _ in results] == [str(image_a), str(image_b)]
        assert [score for _, score in results] == pytest.approx([1.0, 0.8], abs=1e-6)
        assert [path for path, _ in scoped_results] == [str(image_b)]
        assert [score for _, score in scoped_results] == pytest.approx([0.8], abs=1e-6)
        assert set(repository.get_view_vectors(str(image_a))) == {"full", "top_left"}
        assert repository.get_vector_count() == 3
    finally:
        repository.close()

    reopened = _make_repository(db_path, vec1_extension_path)
    try:
        assert reopened.get_vector_count() == 3
        assert [path for path, _ in reopened.search(query, threshold=0.5)] == [
            str(image_a),
            str(image_b),
        ]
    finally:
        reopened.close()


def test_ai_vec1_repository_encryption_hides_paths_and_vectors(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "synthetic-private-path-marker.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image_path])
    repository = _make_repository(db_path, vec1_extension_path)
    vector = np.random.default_rng(42).standard_normal(
        DEFAULT_AI_MODEL_PROFILE.dimension
    ).astype(np.float32)
    vector /= np.linalg.norm(vector)

    try:
        repository.add_images(vector, [str(image_path)])

        # Act
        storage_paths = (
            db_path,
            db_path.with_name(db_path.name + "-wal"),
            db_path.with_name(db_path.name + "-shm"),
        )

        # Assert
        for storage_path in storage_paths:
            if storage_path.exists():
                contents = storage_path.read_bytes()
                assert str(image_path).encode() not in contents
                assert vector.tobytes() not in contents
    finally:
        repository.close()


def test_ai_vec1_repository_rebuild_preserves_exact_search(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image_path = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image_path])
    repository = _make_repository(db_path, vec1_extension_path)
    vector = np.zeros(DEFAULT_AI_MODEL_PROFILE.dimension, dtype=np.float32)
    vector[0] = 1.0
    try:
        repository.add_images(vector, [str(image_path)])

        repository.rebuild()

        assert repository.search(vector) == [(str(image_path), pytest.approx(1.0))]
    finally:
        repository.close()


def test_ai_vec1_training_reopens_and_keeps_exact_search_and_updates(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    db_path = tmp_path / "index.db"
    paths = [tmp_path / f"{index:03}.jpg" for index in range(128)]
    _create_indexed_images(db_path, paths)
    random = np.random.default_rng(42)
    vectors = random.normal(size=(len(paths), DEFAULT_AI_MODEL_PROFILE.dimension)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    repository = _make_repository(db_path, vec1_extension_path)
    try:
        repository.add_images(vectors, [str(path) for path in paths])
        before = repository.search(vectors[0], top_k=10, threshold=-1)

        repository.train_index()

        assert repository.search(vectors[0], top_k=10, threshold=-1) == before
        approximate = repository.search_approximate(vectors[0], top_k=10, threshold=-1, nprobe=2)
        assert [path for path, _ in approximate] == [path for path, _ in before]
        assert [score for _, score in approximate] == pytest.approx([score for _, score in before])
    finally:
        repository.close()

    reopened = _make_repository(db_path, vec1_extension_path)
    try:
        assert reopened.search(vectors[0], top_k=10, threshold=-1) == before
        reopened.delete_images({str(paths[0])})
        reopened.upsert_images(vectors[1], [str(paths[1])])
        assert reopened.get_vector_count() == 127
    finally:
        reopened.close()


def test_ai_vec1_training_cancellation_rolls_back_rebuild(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    db_path = tmp_path / "index.db"
    paths = [tmp_path / f"{index:03}.jpg" for index in range(128)]
    _create_indexed_images(db_path, paths)
    vectors = np.zeros((len(paths), DEFAULT_AI_MODEL_PROFILE.dimension), dtype=np.float32)
    vectors[:, 0] = 1.0
    repository = _make_repository(db_path, vec1_extension_path)
    stages: list[str] = []
    try:
        repository.add_images(vectors, [str(path) for path in paths])

        with pytest.raises(AiVec1TrainingCanceled):
            repository.train_index(
                cancel_check=lambda: "rebuilt" in stages,
                on_progress=stages.append,
            )

        assert repository.get_vector_count() == len(paths)
    finally:
        repository.close()

    reopened = _make_repository(db_path, vec1_extension_path)
    try:
        assert reopened.get_vector_count() == len(paths)
        assert len(reopened.search(vectors[0], top_k=128)) == len(paths)
    finally:
        reopened.close()


def test_ai_vec1_ann_overfetches_multiple_views_before_limiting_images(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    db_path = tmp_path / "index.db"
    first, second = tmp_path / "first.jpg", tmp_path / "second.jpg"
    _create_indexed_images(db_path, [first, second])
    vectors = np.zeros((129, 512), dtype=np.float32)
    vectors[:, 0] = 1.0
    vectors[-1, 0] = 0.8
    vectors[-1, 1] = 0.6
    repository = _make_repository(db_path, vec1_extension_path)
    try:
        repository.add_images(
            vectors, [str(first)] * 128 + [str(second)],
            view_ids=[f"view-{index}" for index in range(128)] + ["full"],
        )
        repository.train_index()

        results = repository.search_approximate(vectors[0], top_k=2, nprobe=2)

        assert [path for path, _ in results] == [str(first), str(second)]
        assert [score for _, score in results] == pytest.approx([1.0, 0.8], abs=1e-6)
    finally:
        repository.close()


def test_ai_vec1_repository_closed_encrypted_backup_restores_vectors(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image_path = tmp_path / "backup-marker.jpg"
    db_path = tmp_path / "index.db"
    backup_path = tmp_path / "backup.db"
    _create_indexed_images(db_path, [image_path])
    repository = _make_repository(db_path, vec1_extension_path)
    vector = np.zeros(DEFAULT_AI_MODEL_PROFILE.dimension, dtype=np.float32)
    vector[0] = 1.0
    try:
        repository.add_images(vector, [str(image_path)])
    finally:
        repository.close()

    shutil.copy2(db_path, backup_path)
    restored = _make_repository(backup_path, vec1_extension_path)
    try:
        assert restored.search(vector) == [(str(image_path), pytest.approx(1.0))]
        assert str(image_path).encode() not in backup_path.read_bytes()
        assert vector.tobytes() not in backup_path.read_bytes()
    finally:
        restored.close()

    with pytest.raises(sqlcipher3.DatabaseError):
        ImageIndexRepository(backup_path, key="incorrect-backup-password")


def test_ai_vec1_repository_hot_encrypted_backup_restores_vectors(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image_path = tmp_path / "live-backup-marker.jpg"
    db_path = tmp_path / "index.db"
    backup_path = tmp_path / "live-backup.db"
    _create_indexed_images(db_path, [image_path])
    repository = _make_repository(db_path, vec1_extension_path)
    random = np.random.default_rng(42)
    vector = random.normal(size=512).astype(np.float32)
    vector /= np.linalg.norm(vector)
    try:
        repository.add_images(vector, [str(image_path)])
        destination = open_encrypted_connection(backup_path, _DATABASE_KEY)
        try:
            repository._connection().backup(destination)
        finally:
            destination.close()
    finally:
        repository.close()

    restored = _make_repository(backup_path, vec1_extension_path)
    try:
        assert restored.search(vector)[0][0] == str(image_path)
        assert str(image_path).encode() not in backup_path.read_bytes()
        assert vector.tobytes() not in backup_path.read_bytes()
    finally:
        restored.close()
    with pytest.raises(sqlcipher3.DatabaseError):
        ImageIndexRepository(backup_path, key="incorrect-backup-password")


def test_ai_vec1_repository_metadata_deletion_queues_vectors_without_vec1(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photos" / "delete-me.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image_path])
    repository = _make_repository(db_path, vec1_extension_path)
    vector = np.zeros(DEFAULT_AI_MODEL_PROFILE.dimension, dtype=np.float32)
    vector[0] = 1.0
    repository.add_images(vector, [str(image_path)])
    repository.close()

    # Act
    metadata_repository = ImageIndexRepository(db_path, key=_DATABASE_KEY)
    try:
        metadata_repository.delete_by_path_prefix(str(image_path.parent))
        pending_count = metadata_repository.conn.execute(
            "SELECT count(*) FROM ai_vector_pending_deletes"
        ).fetchone()[0]
        remaining_images = metadata_repository.conn.execute(
            "SELECT count(*) FROM images"
        ).fetchone()[0]
    finally:
        metadata_repository.close()

    reopened = _make_repository(db_path, vec1_extension_path)
    try:
        # Assert
        assert pending_count == 1
        assert remaining_images == 0
        assert reopened.get_vector_count() == 0
        assert reopened.get_indexed_paths() == set()
    finally:
        reopened.close()


def test_ai_vec1_repository_folder_deletion_respects_path_boundary(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    folder_path = tmp_path / "Photos"
    inside_path = folder_path / "inside.jpg"
    sibling_path = tmp_path / "Photos-extra" / "sibling.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [inside_path, sibling_path])
    repository = _make_repository(db_path, vec1_extension_path)
    vector = np.zeros(DEFAULT_AI_MODEL_PROFILE.dimension, dtype=np.float32)
    vector[0] = 1.0
    repository.add_images(
        np.stack([vector, vector]),
        [str(inside_path), str(sibling_path)],
    )

    try:
        # Act
        repository.remove_folder(str(folder_path))

        # Assert
        assert repository.get_vector_count() == 1
        assert repository.get_indexed_paths() == {str(sibling_path)}
    finally:
        repository.close()


def test_ai_vec1_repository_upsert_failure_preserves_previous_vectors(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photos" / "stable.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image_path])
    repository = _make_repository(db_path, vec1_extension_path)
    old_vector = np.zeros(DEFAULT_AI_MODEL_PROFILE.dimension, dtype=np.float32)
    old_vector[0] = 1.0
    new_vector = np.zeros(DEFAULT_AI_MODEL_PROFILE.dimension, dtype=np.float32)
    new_vector[1] = 1.0
    repository.add_images(old_vector, [str(image_path)])

    metadata_repository = ImageIndexRepository(db_path, key=_DATABASE_KEY)
    try:
        metadata_repository.conn.execute(
            """
            CREATE TRIGGER test_fail_vec1_view
            BEFORE INSERT ON image_embedding_map
            WHEN NEW.view_key = 'top_left'
            BEGIN
                SELECT RAISE(ABORT, 'simulated vector batch failure');
            END
            """
        )
        metadata_repository.conn.commit()
    finally:
        metadata_repository.close()

    # Act / Assert
    with pytest.raises(sqlcipher3.IntegrityError, match="simulated vector batch failure"):
        repository.upsert_images(
            np.stack([new_vector, new_vector]),
            [str(image_path), str(image_path)],
            view_ids=["full", "top_left"],
        )

    assert repository.get_vector_count() == 1
    assert np.allclose(repository.get_vector(str(image_path)), old_vector)
    repository.close()


def test_ai_vec1_repository_profile_mismatch_rejects_reuse(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photos" / "profile.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image_path])
    initial = _make_repository(db_path, vec1_extension_path)
    initial.close()

    # Act / Assert
    with pytest.raises(AiVec1IndexError, match="metadata is incompatible"):
        _make_repository(
            db_path,
            vec1_extension_path,
            profile=LEGACY_OPENAI_CLIP_PROFILE,
        )


def test_ai_vec1_repository_nonfinite_and_zero_vectors_are_rejected(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photos" / "invalid.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image_path])
    repository = _make_repository(db_path, vec1_extension_path)
    zero_vector = np.zeros(DEFAULT_AI_MODEL_PROFILE.dimension, dtype=np.float32)
    nonfinite_vector = zero_vector.copy()
    nonfinite_vector[0] = np.nan

    # Act / Assert
    with pytest.raises(ValueError, match="non-zero finite norms"):
        repository.add_images(zero_vector, [str(image_path)])
    with pytest.raises(ValueError, match="finite values"):
        repository.add_images(nonfinite_vector, [str(image_path)])
    assert repository.get_vector_count() == 0
    repository.close()


@pytest.mark.parametrize("scope_size", [6, 12, 24])
def test_ai_vec1_repository_exact_search_matches_numpy_in_scoped_multiview_queries(
    tmp_path: Path,
    vec1_extension_path: Path,
    scope_size: int,
) -> None:
    # Arrange
    image_paths = [tmp_path / "photos" / f"{i:02}.jpg" for i in range(24)]
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, image_paths)
    vec1 = _make_repository(db_path, vec1_extension_path)
    rng = np.random.default_rng(2026)
    vectors = rng.standard_normal((len(image_paths) * 2, 512)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    query = np.zeros(512, dtype=np.float32)
    query[0] = 1
    for i, score in enumerate([0.1799, 0.1801, 0.1999, 0.2001, 0.2199, 0.2201]):
        vectors[i * 2] = 0
        vectors[i * 2, 0] = score
        vectors[i * 2, 1] = np.sqrt(1 - score * score)
        vectors[i * 2 + 1] = -query
    row_paths = [str(path) for path in image_paths for _ in range(2)]
    view_ids = ["full", "top_left"] * len(image_paths)
    scope = {str(path) for path in image_paths[:scope_size]}

    try:
        vec1.add_images(vectors, row_paths, view_ids=view_ids)

        # Act / Assert
        for threshold in (0.18, 0.20, 0.22):
            actual = vec1.search_filtered(query, scope, top_k=None, threshold=threshold)
            oracle = []
            for image_index, image_path in enumerate(image_paths[:scope_size]):
                view_scores = vectors[image_index * 2 : image_index * 2 + 2].astype(
                    np.float64
                )
                scores = (view_scores @ query.astype(np.float64)) / np.linalg.norm(
                    view_scores, axis=1
                )
                score = float(np.max(scores))
                if score >= threshold:
                    oracle.append((str(image_path), score))
            oracle.sort(key=lambda hit: (-hit[1], hit[0]))
            assert [path for path, _ in actual] == [path for path, _ in oracle]
            assert [score for _, score in actual] == pytest.approx(
                [score for _, score in oracle], abs=1e-5
            )
        expected_capped = vec1.search_filtered(query, scope, top_k=None, threshold=0.18)[:2]
        actual_capped = vec1.search_filtered(query, scope, top_k=2, threshold=0.18)
        assert [path for path, _ in actual_capped] == [path for path, _ in expected_capped]
    finally:
        vec1.close()


def test_ai_vec1_repository_equal_scores_match_legacy_path_order(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    paths = [tmp_path / "z.jpg", tmp_path / "a.jpg"]
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, paths)
    repo = _make_repository(db_path, vec1_extension_path)
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1
    try:
        repo.add_images(np.stack([vector, vector]), [str(path) for path in paths])

        # Act
        result = repo.search(vector)

        # Assert
        assert [path for path, _ in result] == sorted(str(path) for path in paths)
    finally:
        repo.close()


def test_ai_vec1_repository_float32_threshold_boundaries_match_numpy(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    thresholds = (0.18, 0.20, 0.22)
    paths = [tmp_path / f"{index}.jpg" for index in range(9)]
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, paths)
    vec1 = _make_repository(db_path, vec1_extension_path)
    query = np.zeros(512, dtype=np.float32)
    query[0] = 1.0
    vectors = []
    for threshold in thresholds:
        value = np.float32(threshold)
        for component in (
            np.nextafter(value, np.float32(-1)),
            value,
            np.nextafter(value, np.float32(1)),
        ):
            vector = np.zeros(512, dtype=np.float32)
            vector[0] = component
            vector[1] = np.sqrt(1 - float(component) ** 2)
            vector /= np.linalg.norm(vector)
            vectors.append(vector)
    rows = [str(path) for path in paths]
    try:
        vec1.add_images(np.stack(vectors), rows)

        # Act / Assert
        for threshold in thresholds:
            expected = {
                path for path, vector in zip(rows, vectors, strict=True)
                if float(vector @ query) >= threshold
            }
            actual = vec1.search_filtered(query, set(rows), top_k=None, threshold=threshold)
            assert {path for path, _ in actual} == expected
    finally:
        vec1.close()


def test_ai_vec1_repository_failed_schema_creation_rolls_back(
    tmp_path: Path,
    vec1_extension_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [])

    def fail_metadata(*args: object) -> None:
        raise RuntimeError("simulated initialization failure")

    with monkeypatch.context() as patch:
        patch.setattr(AiVec1Repository, "_insert_metadata", fail_metadata)
        with pytest.raises(RuntimeError, match="simulated initialization failure"):
            _make_repository(db_path, vec1_extension_path)

    # Act / Assert
    repository = _make_repository(db_path, vec1_extension_path)
    try:
        assert repository.get_vector_count() == 0
    finally:
        repository.close()


def test_ai_vec1_repository_live_metadata_deletion_updates_vector_count(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image_path = tmp_path / "photos" / "deleted.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image_path])
    repository = _make_repository(db_path, vec1_extension_path)
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    repository.add_images(vector, [str(image_path)])
    metadata = ImageIndexRepository(db_path, key=_DATABASE_KEY)
    try:
        # Act
        metadata.delete_by_path_prefix(str(image_path.parent))

        # Assert
        assert repository.get_vector_count() == 0
        assert repository.search(vector) == []
    finally:
        metadata.close()
        repository.close()
