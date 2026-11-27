"""Tests for encrypted Vec1 vector storage and retrieval."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import sqlcipher3

from exif_turbo.data._connection import open_encrypted_connection
from exif_turbo.data.ai_vec1_repository import (
    AiVec1IndexError,
    AiVec1MigrationCanceled,
    AiVec1Repository,
    AiVec1TrainingCanceled,
)
from exif_turbo.data.ai_vector_repository import AiVectorIndexError, AiVectorRepository
from exif_turbo.data.ai_vector_storage import (
    AiVectorAuthenticationError,
    AiVectorStorage,
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


def test_ai_vec1_repository_exact_search_matches_faiss_in_scoped_multiview_queries(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image_paths = [tmp_path / "photos" / f"{i:02}.jpg" for i in range(24)]
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, image_paths)
    vec1 = _make_repository(db_path, vec1_extension_path)
    faiss = AiVectorRepository(tmp_path / "vectors.faiss", tmp_path / "map.json")
    faiss.load()
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
    scope = {str(path) for path in image_paths[:12]}

    try:
        vec1.add_images(vectors, row_paths, view_ids=view_ids)
        faiss.add_images(vectors, row_paths, view_ids=view_ids)

        # Act / Assert
        for threshold in (0.18, 0.20, 0.22):
            expected = faiss.search_filtered(query, scope, top_k=None, threshold=threshold)
            actual = vec1.search_filtered(query, scope, top_k=None, threshold=threshold)
            oracle = []
            for image_index, image_path in enumerate(image_paths[:12]):
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
            assert [path for path, _ in actual] == [path for path, _ in expected]
            assert [path for path, _ in actual] == [path for path, _ in oracle]
            assert [score for _, score in actual] == pytest.approx(
                [score for _, score in expected], abs=1e-5
            )
            assert [score for _, score in actual] == pytest.approx(
                [score for _, score in oracle], abs=1e-5
            )
        expected_capped = faiss.search_filtered(query, scope, top_k=2, threshold=0.18)
        actual_capped = vec1.search_filtered(query, scope, top_k=2, threshold=0.18)
        assert [path for path, _ in actual_capped] == [path for path, _ in expected_capped]
    finally:
        vec1.close()
        faiss.close()


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


def test_ai_vec1_repository_float32_threshold_boundaries_match_faiss(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    thresholds = (0.18, 0.20, 0.22)
    paths = [tmp_path / f"{index}.jpg" for index in range(9)]
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, paths)
    vec1 = _make_repository(db_path, vec1_extension_path)
    faiss = AiVectorRepository(tmp_path / "vectors.faiss", tmp_path / "map.json")
    faiss.load()
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
        faiss.add_images(np.stack(vectors), rows)

        # Act / Assert
        for threshold in thresholds:
            expected = faiss.search_filtered(query, set(rows), top_k=None, threshold=threshold)
            actual = vec1.search_filtered(query, set(rows), top_k=None, threshold=threshold)
            assert {path for path, _ in actual} == {path for path, _ in expected}
    finally:
        vec1.close()
        faiss.close()


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


def test_ai_vec1_import_authenticated_snapshot_preserves_views_and_skips_missing(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image = tmp_path / "present.jpg"
    missing = tmp_path / "missing.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    index_path = tmp_path / "legacy.faiss"
    writer = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    writer.load()
    vectors = np.zeros((3, 512), dtype=np.float32)
    vectors[0, 0] = 1.0
    vectors[1, 1] = 1.0
    vectors[2, 2] = 1.0
    writer.add_images(
        vectors,
        [str(image), str(image), str(missing)],
        view_ids=["full", "top_left", "full"],
    )
    writer.save()
    writer.close()
    snapshot_path = index_path.with_name(index_path.name + ".enc")
    original_snapshot = snapshot_path.read_bytes()
    source = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    metadata = ImageIndexRepository(db_path, key=_DATABASE_KEY)
    progress: list[tuple[int, int]] = []
    visible_counts: list[int] = []

    def observe_progress(count: int, total: int) -> None:
        progress.append((count, total))
        visible_counts.append(
            int(metadata.conn.execute("SELECT count(*) FROM image_embedding_map").fetchone()[0])
        )

    try:
        # Act
        result = target.import_faiss_snapshot(source, on_progress=observe_progress)

        # Assert
        assert (result.source_vectors, result.imported_vectors, result.imported_images) == (3, 2, 1)
        assert result.missing_vectors == 1
        assert progress[-1] == (3, 3)
        assert visible_counts == [0, 0, 0]
        actual = target.get_view_vectors(str(image))
        assert set(actual) == {"full", "top_left"}
        assert actual["full"].tobytes() == vectors[0].tobytes()
        assert actual["top_left"].tobytes() == vectors[1].tobytes()
        assert snapshot_path.read_bytes() == original_snapshot
        repeated = target.import_faiss_snapshot(source)
        assert repeated.matched_existing
        assert repeated.imported_vectors == result.imported_vectors
        assert repeated.missing_vectors == result.missing_vectors
    finally:
        metadata.close()
        target.close()
        source.close()

    reopened = _make_repository(db_path, vec1_extension_path)
    try:
        assert reopened.get_vector_count() == 2
        source.load_migration_source()
        expected = source.search_filtered(vectors[0], {str(image)}, threshold=0.2)
        actual = reopened.search_filtered(vectors[0], {str(image)}, threshold=0.2)
        assert [path for path, _ in actual] == [path for path, _ in expected]
        assert [score for _, score in actual] == pytest.approx(
            [score for _, score in expected], abs=1e-5
        )
    finally:
        reopened.close()
        source.close()


def test_ai_vec1_staging_preserves_active_vectors_and_reports_unknown_content(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    missing = tmp_path / "missing.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    index_path = tmp_path / "legacy.faiss"
    source = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vectors = np.zeros((2, 512), dtype=np.float32)
    vectors[:, 0] = 1.0
    source.add_images(vectors, [str(image), str(missing)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    active = np.zeros(512, dtype=np.float32)
    active[1] = 1.0
    target.add_images(active, [str(image)])
    progress: list[tuple[int, int]] = []
    try:
        result = target.stage_faiss_snapshot(
            source, batch_size=1, on_progress=lambda done, total: progress.append((done, total))
        )

        assert (result.source_vectors, result.staged_vectors, result.missing_vectors) == (2, 1, 1)
        assert result.staged_images == result.unknown_content_images == 1
        assert progress == [(1, 2), (2, 2)]
        np.testing.assert_array_equal(target.get_vector(str(image)), active)
        assert target._connection().execute(
            "SELECT complete FROM ai_vec1_staging_status"
        ).fetchone() == (1,)
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_cancellation_removes_stage_and_preserves_active_index(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    target.add_images(vector, [str(image)])
    completed: list[int] = []
    try:
        with pytest.raises(AiVec1MigrationCanceled):
            target.stage_faiss_snapshot(
                source, batch_size=1, on_progress=lambda done, total: completed.append(done),
                cancel_check=lambda: bool(completed),
            )

        assert target.get_vector_count() == 1
        assert target._connection().execute(
            "SELECT count(*) FROM sqlite_master WHERE name='ai_vec1_staging_status'"
        ).fetchone() == (0,)
        assert target.stage_faiss_snapshot(source).staged_vectors == 1
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_canceled_replacement_preserves_completed_stage(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    index_path = tmp_path / "legacy.faiss"
    map_path = tmp_path / "map.json"
    source = AiVectorRepository(index_path, map_path, key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    replacement = AiVectorRepository(
        tmp_path / "replacement.faiss", tmp_path / "replacement-map.json", key=_DATABASE_KEY
    )
    replacement.load()
    other = np.zeros(512, dtype=np.float32)
    other[1] = 1.0
    replacement.add_images(other, [str(image)])
    replacement.save()
    replacement.close()
    replacement.load_migration_source()
    try:
        target.stage_faiss_snapshot(source)
        progress: list[int] = []
        with pytest.raises(AiVec1MigrationCanceled):
            target.stage_faiss_snapshot(
                replacement, batch_size=1,
                on_progress=lambda done, total: progress.append(done),
                cancel_check=lambda: bool(progress),
            )

        assert target.verify_staged_snapshot(source).staged_vectors == 1
        assert target.stage_faiss_snapshot(replacement).staged_vectors == 1
        assert target.verify_staged_snapshot(replacement).staged_vectors == 1
        with pytest.raises(AiVec1IndexError, match="does not match"):
            target.verify_staged_snapshot(source)
    finally:
        replacement.close()
        target.close()
        source.close()


def test_ai_vec1_staging_replacement_failure_rolls_back_completed_stage(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        target.stage_faiss_snapshot(source)

        def deny_rename(
            action: int, arg1: str | None, arg2: str | None,
            database: str | None, trigger: str | None,
        ) -> int:
            return sqlcipher3.SQLITE_DENY if action == sqlcipher3.SQLITE_ALTER_TABLE else sqlcipher3.SQLITE_OK

        target._connection().set_authorizer(deny_rename)
        try:
            with pytest.raises(sqlcipher3.DatabaseError, match="authorized"):
                target.stage_faiss_snapshot(source)
        finally:
            target._connection().set_authorizer(None)

        assert target.verify_staged_snapshot(source).staged_vectors == 1
        assert target._connection().execute(
            "SELECT count(*) FROM sqlite_master WHERE name='ai_vec1_build_status'"
        ).fetchone() == (0,)
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_failed_backup_preserves_previous_completed_stage(
    tmp_path: Path, vec1_extension_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        target.stage_faiss_snapshot(source)
        old_build = target._connection().execute(
            "SELECT build_id FROM ai_vec1_staging_status"
        ).fetchone()
        disk = shutil.disk_usage(tmp_path)
        checks: list[int] = []

        def disk_usage(_path: Path) -> object:
            checks.append(1)
            return disk if len(checks) == 1 else disk._replace(free=0)

        with monkeypatch.context() as patch:
            patch.setattr("exif_turbo.data.ai_vec1_repository.shutil.disk_usage", disk_usage)
            with pytest.raises(AiVec1IndexError, match="backup verification"):
                target.stage_faiss_snapshot(source, verify_backup=True)

        assert target._connection().execute(
            "SELECT build_id FROM ai_vec1_staging_status"
        ).fetchone() == old_build
        assert target.verify_staged_snapshot(source).staged_vectors == 1
        assert not list(tmp_path.glob(".index.db.vec1-backup-*"))
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_superseded_attempt_preserves_new_completed_stage(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    first = _make_repository(db_path, vec1_extension_path)
    second = _make_repository(db_path, vec1_extension_path)
    try:
        def finish_other_attempt(_done: int, _total: int) -> None:
            assert second.stage_faiss_snapshot(source).staged_vectors == 1

        with pytest.raises(AiVec1IndexError, match="metadata database changed"):
            first.stage_faiss_snapshot(source, batch_size=1, on_progress=finish_other_attempt)

        assert second.verify_staged_snapshot(source).staged_vectors == 1
    finally:
        first.close()
        second.close()
        source.close()


def test_ai_vec1_reopened_staging_verification_rejects_modified_vector(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    target.stage_faiss_snapshot(source)
    target.close()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        assert target.verify_staged_snapshot(source).staged_vectors == 1
        other = np.zeros(512, dtype=np.float32)
        other[1] = 1.0
        with target._connection():
            target._connection().execute(
                "UPDATE ai_vec1_staging_vectors SET embedding = ? WHERE rowid = 1",
                (other.tobytes(),),
            )

        with pytest.raises(AiVec1IndexError, match="does not match"):
            target.verify_staged_snapshot(source)
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_verification_rejects_different_snapshot_with_same_known_vectors(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    vectors = np.zeros((2, 512), dtype=np.float32)
    vectors[:, 0] = 1.0
    sources = []
    for number in (1, 2):
        source = AiVectorRepository(
            tmp_path / f"source{number}.faiss", tmp_path / f"map{number}.json", key=_DATABASE_KEY
        )
        source.load()
        source.add_images(vectors, [str(image), str(tmp_path / f"missing{number}.jpg")])
        source.save()
        source.close()
        source.load_migration_source()
        sources.append(source)
    target = _make_repository(db_path, vec1_extension_path)
    try:
        target.stage_faiss_snapshot(sources[0])
        target.close()
        target = _make_repository(db_path, vec1_extension_path)

        with pytest.raises(AiVec1IndexError, match="does not match the snapshot"):
            target.verify_staged_snapshot(sources[1])
        assert target.verify_staged_snapshot(sources[0]).staged_vectors == 1
    finally:
        target.close()
        for source in sources:
            source.close()


def test_ai_vec1_staging_verification_rejects_updated_image_stamp(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        target.stage_faiss_snapshot(source)
        target.close()
        images = ImageIndexRepository(db_path, key=_DATABASE_KEY)
        try:
            images.upsert_image(str(image), "image.jpg", 2.0, 100, {}, "")
        finally:
            images.close()
        target = _make_repository(db_path, vec1_extension_path)

        with pytest.raises(AiVec1IndexError, match="image changed"):
            target.verify_staged_snapshot(source)
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_online_encrypted_backup_restores_verified_stage(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "staging-backup-marker.jpg"
    db_path = tmp_path / "index.db"
    backup_path = tmp_path / "backup.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        target.stage_faiss_snapshot(source)
        destination = open_encrypted_connection(backup_path, _DATABASE_KEY)
        try:
            target._connection().backup(destination)
        finally:
            destination.close()
        restored = _make_repository(backup_path, vec1_extension_path)
        try:
            assert restored.verify_staged_snapshot(source).staged_vectors == 1
        finally:
            restored.close()
        assert str(image).encode() not in backup_path.read_bytes()
        assert vector.tobytes() not in backup_path.read_bytes()
        with pytest.raises(sqlcipher3.DatabaseError):
            ImageIndexRepository(backup_path, key="incorrect-backup-password")
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_backup_verification_cleans_temporary_encrypted_copy(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        expected = target.stage_faiss_snapshot(source)

        assert target.verify_staged_backup(source) == expected
        assert not list(tmp_path.glob(".index.db.vec1-backup-*"))
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_backup_cancel_preserves_stage_and_removes_copy(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        target.stage_faiss_snapshot(source)
        checks: list[int] = []

        def cancel_during_backup() -> bool:
            checks.append(1)
            return len(checks) > 1

        with pytest.raises(AiVec1MigrationCanceled):
            target.verify_staged_backup(source, cancel_check=cancel_during_backup)

        assert target.verify_staged_snapshot(source).staged_vectors == 1
        assert not list(tmp_path.glob(".index.db.vec1-backup-*"))
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_backup_rejects_modified_stage_and_removes_copy(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        target.stage_faiss_snapshot(source)
        vector[0], vector[1] = 0.0, 1.0
        with target._connection():
            target._connection().execute(
                "UPDATE ai_vec1_staging_vectors SET embedding = ? WHERE rowid = 1",
                (vector.tobytes(),),
            )

        with pytest.raises(AiVec1IndexError, match="does not match"):
            target.verify_staged_backup(source)
        assert not list(tmp_path.glob(".index.db.vec1-backup-*"))
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_rejects_concurrent_metadata_changes(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)

    def update_metadata(done: int, total: int) -> None:
        other = ImageIndexRepository(db_path, key=_DATABASE_KEY)
        try:
            other.upsert_image(str(tmp_path / "new.jpg"), "new.jpg", 1.0, 100, {}, "")
        finally:
            other.close()

    try:
        with pytest.raises(AiVec1IndexError, match="metadata database changed"):
            target.stage_faiss_snapshot(source, batch_size=1, on_progress=update_metadata)

        assert target.get_vector_count() == 0
        assert target._connection().execute(
            "SELECT count(*) FROM sqlite_master WHERE name='ai_vec1_staging_status'"
        ).fetchone() == (0,)
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_rejects_source_modified_during_staging(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    source = AiVectorRepository(tmp_path / "legacy.faiss", tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        def mutate_source(_done: int, _total: int) -> None:
            source.add_images(vector, [str(tmp_path / "another.jpg")])

        with pytest.raises(AiVectorIndexError, match="authenticated AI snapshot"):
            target.stage_faiss_snapshot(source, batch_size=1, on_progress=mutate_source)

        assert target._connection().execute(
            "SELECT count(*) FROM sqlite_master WHERE name='ai_vec1_build_status'"
        ).fetchone() == (0,)
        assert target.get_vector_count() == 0
    finally:
        target.close()
        source.close()


def test_ai_vec1_staging_rejects_unauthenticated_source_without_discarding_stage(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    image = tmp_path / "image.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    index_path = tmp_path / "legacy.faiss"
    source = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    target.stage_faiss_snapshot(source)
    plaintext = AiVectorRepository(tmp_path / "other.faiss", tmp_path / "other-map.json")
    plaintext.load()
    try:
        with pytest.raises(AiVectorIndexError, match="authenticated"):
            target.stage_faiss_snapshot(plaintext)

        assert target._connection().execute(
            "SELECT complete, staged_vectors FROM ai_vec1_staging_status"
        ).fetchone() == (1, 1)
    finally:
        plaintext.close()
        target.close()
        source.close()


def test_ai_vec1_staging_interrupted_process_can_restart_without_changing_active_index(
    tmp_path: Path, vec1_extension_path: Path
) -> None:
    images = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, images)
    index_path = tmp_path / "legacy.faiss"
    map_path = tmp_path / "map.json"
    source = AiVectorRepository(index_path, map_path, key=_DATABASE_KEY)
    source.load()
    vectors = np.zeros((2, 512), dtype=np.float32)
    vectors[:, 0] = 1.0
    source.add_images(vectors, [str(path) for path in images])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    target.add_images(vectors[0], [str(images[0])])
    target.stage_faiss_snapshot(source)
    target.close()
    source.close()
    code = """
import os
import sys
from pathlib import Path
from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.data.ai_vec1_repository import AiVec1Repository
db, index, mapping, extension, key = sys.argv[1:]
source = AiVectorRepository(Path(index), Path(mapping), key=key)
source.load_migration_source()
target = AiVec1Repository(Path(db), key, Path(extension))
target.load()
target.stage_faiss_snapshot(source, batch_size=1, on_progress=lambda count, total: os._exit(79))
"""

    child = subprocess.run(
        [sys.executable, "-c", code, str(db_path), str(index_path),
         str(map_path), str(vec1_extension_path), _DATABASE_KEY],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False,
    )
    target = _make_repository(db_path, vec1_extension_path)
    try:
        source.load_migration_source()
        assert child.returncode == 79
        assert target.get_vector_count() == 1
        assert target._connection().execute(
            "SELECT complete FROM ai_vec1_build_status"
        ).fetchone() == (0,)
        assert target.verify_staged_snapshot(source).staged_vectors == 2
        assert target.stage_faiss_snapshot(source, batch_size=1).staged_vectors == 2
        assert target.get_vector_count() == 1
    finally:
        target.close()
        source.close()


def test_ai_vec1_import_cancellation_rolls_back_and_can_retry(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    images = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, images)
    index_path = tmp_path / "legacy.faiss"
    source = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vectors = np.zeros((2, 512), dtype=np.float32)
    vectors[:, 0] = 1.0
    source.add_images(vectors, [str(path) for path in images])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    progress: list[int] = []
    try:
        # Act / Assert
        with pytest.raises(AiVec1MigrationCanceled):
            target.import_faiss_snapshot(
                source,
                cancel_check=lambda: bool(progress),
                on_progress=lambda count, total: progress.append(count),
            )
        assert target.get_vector_count() == 0
        result = target.import_faiss_snapshot(source)
        assert result.imported_vectors == 2
    finally:
        target.close()
        source.close()


def test_ai_vec1_import_nonempty_destination_preserves_existing_vectors(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image = tmp_path / "present.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    index_path = tmp_path / "legacy.faiss"
    source = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    original = np.zeros(512, dtype=np.float32)
    original[1] = 1.0
    target.add_images(original, [str(image)])
    try:
        # Act / Assert
        with pytest.raises(AiVec1IndexError, match="does not match"):
            target.import_faiss_snapshot(source)
        assert target.get_vector_count() == 1
        assert np.array_equal(target.get_vector(str(image)), original)
    finally:
        target.close()
        source.close()


def test_ai_vec1_import_insufficient_disk_space_preserves_source_and_target(
    tmp_path: Path,
    vec1_extension_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    image = tmp_path / "present.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    index_path = tmp_path / "legacy.faiss"
    source = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    snapshot = index_path.with_name(index_path.name + ".enc")
    original = snapshot.read_bytes()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    disk = shutil.disk_usage(tmp_path)
    try:
        # Act / Assert
        with monkeypatch.context() as patch:
            patch.setattr(
                "exif_turbo.data.ai_vec1_repository.shutil.disk_usage",
                lambda _: disk._replace(free=0),
            )
            with pytest.raises(AiVec1IndexError, match="Insufficient disk space"):
                target.import_faiss_snapshot(source)
        assert target.get_vector_count() == 0
        assert snapshot.read_bytes() == original
        assert target.import_faiss_snapshot(source).imported_vectors == 1
        with monkeypatch.context() as patch:
            patch.setattr(
                "exif_turbo.data.ai_vec1_repository.shutil.disk_usage",
                lambda _: disk._replace(free=0),
            )
            assert target.import_faiss_snapshot(source).matched_existing
    finally:
        target.close()
        source.close()


def test_ai_vec1_import_extra_existing_view_rejects_retry(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image = tmp_path / "present.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    index_path = tmp_path / "legacy.faiss"
    source = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    source.add_images(vector, [str(image)])
    source.save()
    source.close()
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    target.add_images(
        np.stack([vector, vector]),
        [str(image), str(image)],
        view_ids=["full", "top_left"],
    )
    try:
        # Act / Assert
        with pytest.raises(AiVec1IndexError, match="does not match"):
            target.import_faiss_snapshot(source)
        assert target.get_vector_count() == 2
    finally:
        target.close()
        source.close()


def test_ai_vec1_import_process_exit_recovers_and_can_retry(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    images = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, images)
    index_path = tmp_path / "legacy.faiss"
    map_path = tmp_path / "map.json"
    writer = AiVectorRepository(index_path, map_path, key=_DATABASE_KEY)
    writer.load()
    vectors = np.zeros((2, 512), dtype=np.float32)
    vectors[:, 0] = 1.0
    writer.add_images(vectors, [str(path) for path in images])
    writer.save()
    writer.close()
    snapshot = index_path.with_name(index_path.name + ".enc")
    original = snapshot.read_bytes()
    code = """
import os
import sys
from pathlib import Path
from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.data.ai_vec1_repository import AiVec1Repository
db, index, mapping, extension, key = sys.argv[1:]
source = AiVectorRepository(Path(index), Path(mapping), key=key)
source.load_migration_source()
target = AiVec1Repository(Path(db), key, Path(extension))
target.load()
target.import_faiss_snapshot(source, on_progress=lambda count, total: os._exit(79))
"""

    # Act
    child = subprocess.run(
        [
            sys.executable, "-c", code, str(db_path), str(index_path),
            str(map_path), str(vec1_extension_path), _DATABASE_KEY,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    target = _make_repository(db_path, vec1_extension_path)
    source = AiVectorRepository(index_path, map_path, key=_DATABASE_KEY)
    try:
        # Assert
        assert child.returncode == 79
        assert target.get_vector_count() == 0
        assert snapshot.read_bytes() == original
        source.load_migration_source()
        assert target.import_faiss_snapshot(source).imported_vectors == 2
    finally:
        target.close()
        source.close()


def test_ai_vec1_import_wrong_password_never_changes_destination(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [])
    index_path = tmp_path / "legacy.faiss"
    writer = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    writer.load()
    writer.save()
    writer.close()
    wrong = AiVectorRepository(index_path, tmp_path / "map.json", key="wrong-password")
    target = _make_repository(db_path, vec1_extension_path)
    try:
        # Act / Assert
        with pytest.raises(AiVectorAuthenticationError):
            wrong.load_migration_source()
        assert target.get_vector_count() == 0
    finally:
        wrong.close()
        target.close()


def test_ai_vec1_import_duplicate_views_rolls_back_partial_import(
    tmp_path: Path,
    vec1_extension_path: Path,
) -> None:
    # Arrange
    image = tmp_path / "present.jpg"
    db_path = tmp_path / "index.db"
    _create_indexed_images(db_path, [image])
    index_path = tmp_path / "legacy.faiss"
    source = AiVectorRepository(index_path, tmp_path / "map.json", key=_DATABASE_KEY)
    source.load()
    vectors = np.zeros((2, 512), dtype=np.float32)
    vectors[0, 0] = 1.0
    vectors[1, 1] = 1.0
    source.add_images(vectors, [str(image)] * 2, view_ids=["full", "top_left"])
    source.save()
    source.close()
    storage = AiVectorStorage(index_path, _DATABASE_KEY)
    index, mapping, raw_metadata = storage.load()
    rows = json.loads(mapping)
    rows["1"]["view_id"] = "full"
    updated_mapping = json.dumps(rows).encode()
    metadata = json.loads(raw_metadata)
    metadata["map_sha256"] = hashlib.sha256(updated_mapping).hexdigest()
    storage.save(index, updated_mapping, json.dumps(metadata).encode())
    source.load_migration_source()
    target = _make_repository(db_path, vec1_extension_path)
    try:
        # Act / Assert
        with pytest.raises(AiVectorIndexError, match="duplicate image views"):
            target.import_faiss_snapshot(source)
        assert target.get_vector_count() == 0
    finally:
        target.close()
        source.close()
