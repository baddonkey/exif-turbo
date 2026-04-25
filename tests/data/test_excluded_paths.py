"""End-to-end tests for excluded_paths in ImageIndexRepository.

Verifies that images under disabled folders are filtered out of search
results when ``excluded_paths`` is provided.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository
from tests.conftest import make_jpeg


@pytest.fixture
def repo_with_images(tmp_path: Path) -> ImageIndexRepository:
    """DB with images in two separate sub-folders: 'alpha' and 'beta'."""
    db = ImageIndexRepository(tmp_path / "test.db", key="")

    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()

    for i in range(3):
        p = make_jpeg(alpha / f"alpha_{i}.jpg")
        db.upsert_image(str(p), p.name, float(i), i * 100, {"Make": "Canon"}, f"Canon alpha_{i} jpg")
    for i in range(2):
        p = make_jpeg(beta / f"beta_{i}.jpg")
        db.upsert_image(str(p), p.name, float(i), i * 100, {"Make": "Nikon"}, f"Nikon beta_{i} jpg")

    db.commit()
    yield db
    db.close()


# ── excluded_paths in search_images ─────────────────────────────────────────


def test_search_images_no_exclusions_returns_all_results(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    rows = repo_with_images.search_images("", limit=20, offset=0)
    assert len(rows) == 5


def test_search_images_excluded_path_hides_those_images(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    # Act — exclude the 'beta' folder
    excluded = [str(tmp_path / "beta")]
    rows = repo_with_images.search_images("", limit=20, offset=0, excluded_paths=excluded)

    # Assert — only 'alpha' images visible
    assert len(rows) == 3
    for row in rows:
        assert "alpha" in row[2]


def test_search_images_excluded_all_folders_returns_empty(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    excluded = [str(tmp_path / "alpha"), str(tmp_path / "beta")]
    rows = repo_with_images.search_images("", limit=20, offset=0, excluded_paths=excluded)
    assert len(rows) == 0


def test_search_images_fts_with_exclusion_filters_correctly(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    # Act — search for "Canon" but exclude alpha folder
    excluded = [str(tmp_path / "alpha")]
    rows = repo_with_images.search_images("Canon", limit=20, offset=0, excluded_paths=excluded)

    # Assert — no Canon results (all Canon images are in alpha)
    assert len(rows) == 0


def test_search_images_fts_without_exclusion_returns_fts_results(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    rows = repo_with_images.search_images("Canon", limit=20, offset=0)
    assert len(rows) == 3


# ── excluded_paths in count_images ───────────────────────────────────────────


def test_count_images_no_exclusions_returns_total(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    assert repo_with_images.count_images("") == 5


def test_count_images_with_exclusion_returns_reduced_count(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    excluded = [str(tmp_path / "beta")]
    count = repo_with_images.count_images("", excluded_paths=excluded)
    assert count == 3


def test_count_images_fts_with_exclusion_counts_correctly(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    excluded = [str(tmp_path / "alpha")]
    count = repo_with_images.count_images("Canon", excluded_paths=excluded)
    assert count == 0


# ── delete_by_path_prefix ────────────────────────────────────────────────────


def test_delete_by_path_prefix_removes_only_matching_images(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    # Act
    repo_with_images.delete_by_path_prefix(str(tmp_path / "beta"))

    # Assert
    rows = repo_with_images.search_images("", limit=20, offset=0)
    assert len(rows) == 3
    for row in rows:
        assert "alpha" in row[2]


def test_delete_by_path_prefix_removes_from_fts_index(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    # Act
    repo_with_images.delete_by_path_prefix(str(tmp_path / "beta"))

    # Assert — Nikon images (from beta) no longer searchable
    rows = repo_with_images.search_images("Nikon", limit=20, offset=0)
    assert len(rows) == 0


def test_delete_by_path_prefix_nonexistent_path_does_not_raise(
    repo_with_images: ImageIndexRepository, tmp_path: Path
) -> None:
    repo_with_images.delete_by_path_prefix(str(tmp_path / "nonexistent"))
    assert repo_with_images.count_images("") == 5
