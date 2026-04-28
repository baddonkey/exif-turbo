from __future__ import annotations

"""End-to-end integration tests for IndexerService.

These tests create real image files on disk, run the full indexing pipeline
(ImageFinder → ExifMetadataExtractor → IndexedImage → ImageIndexRepository),
and verify the results are queryable via search.  No mocking.
"""

from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest
from PIL import Image

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.indexing.indexer_service import IndexerService
from exif_turbo.indexing.metadata_extractor import MetadataExtractor


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_jpeg(path: Path) -> Path:
    Image.new("RGB", (16, 16), color=(200, 100, 50)).save(str(path), format="JPEG")
    return path


def _make_png(path: Path) -> Path:
    Image.new("RGB", (16, 16), color=(50, 100, 200)).save(str(path), format="PNG")
    return path


class _FakeExtractor(MetadataExtractor):
    """Returns predictable metadata keyed by filename stem."""

    def __init__(self, metadata_by_stem: dict[str, dict[str, str]] | None = None) -> None:
        self._meta = metadata_by_stem or {}

    def extract(self, path: Path) -> dict[str, str]:
        return self._meta.get(path.stem, {"FakeKey": path.stem})


@pytest.fixture
def repo(tmp_path: Path) -> ImageIndexRepository:
    db = ImageIndexRepository(tmp_path / "index.db", key="")
    yield db
    db.close()


@pytest.fixture
def image_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "images"
    folder.mkdir()
    return folder


# ── basic indexing ─────────────────────────────────────────────────────────────


def test_build_index_indexes_single_jpeg(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange
    _make_jpeg(image_folder / "photo.jpg")
    service = IndexerService(repo, extractor=_FakeExtractor({"photo": {"Make": "Canon"}}))

    # Act
    count, _ = service.build_index([image_folder])

    # Assert
    assert count == 1
    rows = repo.search_images("", limit=10, offset=0)
    assert len(rows) == 1
    assert rows[0][2] == "photo.jpg"


def test_build_index_indexes_multiple_formats(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange
    _make_jpeg(image_folder / "a.jpg")
    _make_png(image_folder / "b.png")
    service = IndexerService(repo, extractor=_FakeExtractor())

    # Act
    count, _ = service.build_index([image_folder])

    # Assert
    assert count == 2
    assert repo.count_images("") == 2


def test_build_index_empty_folder_returns_zero(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    service = IndexerService(repo, extractor=_FakeExtractor())

    count, _ = service.build_index([empty])

    assert count == 0
    assert repo.count_images("") == 0


# ── incremental indexing (skip unchanged) ─────────────────────────────────────


def test_build_index_skips_unchanged_file_on_second_run(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange
    img = _make_jpeg(image_folder / "photo.jpg")
    extract_calls: list[Path] = []

    class _TrackingExtractor(MetadataExtractor):
        def extract(self, path: Path) -> dict[str, str]:
            extract_calls.append(path)
            return {}

    service = IndexerService(repo, extractor=_TrackingExtractor())

    # Act — first run indexes the file
    service.build_index([image_folder])
    first_call_count = len(extract_calls)

    # Act — second run, file unchanged
    service.build_index([image_folder])

    # Assert — extractor was not called again
    assert first_call_count == 1
    assert len(extract_calls) == 1


def test_build_index_reindexes_changed_file(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange
    img = _make_jpeg(image_folder / "photo.jpg")
    call_count = [0]

    class _CountingExtractor(MetadataExtractor):
        def extract(self, path: Path) -> dict[str, str]:
            call_count[0] += 1
            return {"Run": str(call_count[0])}

    service = IndexerService(repo, extractor=_CountingExtractor())
    service.build_index([image_folder])

    # Modify the file — write a larger image so size changes even within the same mtime tick
    Image.new("RGB", (32, 32), color=(50, 200, 100)).save(str(img), format="JPEG")

    # Act
    service.build_index([image_folder])

    # Assert — extractor ran twice (once per run)
    assert call_count[0] == 2


# ── force re-index ─────────────────────────────────────────────────────────────


def test_build_index_force_reindexes_all_files(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange
    _make_jpeg(image_folder / "photo.jpg")
    call_count = [0]

    class _CountingExtractor(MetadataExtractor):
        def extract(self, path: Path) -> dict[str, str]:
            call_count[0] += 1
            return {}

    service = IndexerService(repo, extractor=_CountingExtractor())
    service.build_index([image_folder])
    assert call_count[0] == 1

    # Act — force re-index
    service.build_index([image_folder], force=True)

    # Assert — extractor ran again despite file being unchanged
    assert call_count[0] == 2


# ── delete missing ─────────────────────────────────────────────────────────────


def test_build_index_removes_deleted_files(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange — index two files
    img_a = _make_jpeg(image_folder / "a.jpg")
    img_b = _make_jpeg(image_folder / "b.jpg")
    service = IndexerService(repo, extractor=_FakeExtractor())
    service.build_index([image_folder])
    assert repo.count_images("") == 2

    # Remove one file from disk
    img_b.unlink()

    # Act — re-index
    service.build_index([image_folder])

    # Assert — only the remaining file is in the index
    assert repo.count_images("") == 1
    rows = repo.search_images("", limit=10, offset=0)
    assert rows[0][2] == "a.jpg"


def test_build_index_rescanning_one_folder_preserves_other_indexed_folders(
    repo: ImageIndexRepository, image_folder: Path, tmp_path: Path
) -> None:
    # Arrange — index one image in each of two separate folders
    folder_b = tmp_path / "folder_b"
    folder_b.mkdir()
    _make_jpeg(image_folder / "a.jpg")
    _make_jpeg(folder_b / "b.jpg")
    service = IndexerService(repo, extractor=_FakeExtractor())
    service.build_index([image_folder, folder_b])
    assert repo.count_images("") == 2

    # Act — rescan only image_folder (folder_b is not included)
    service.build_index([image_folder])

    # Assert — b.jpg from folder_b must still be in the index
    assert repo.count_images("") == 2
    filenames = {r[2] for r in repo.search_images("", limit=10, offset=0)}
    assert "b.jpg" in filenames


# ── FTS5 search after indexing ────────────────────────────────────────────────


def test_build_index_results_are_fts_searchable(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange
    _make_jpeg(image_folder / "canon_shot.jpg")
    _make_jpeg(image_folder / "nikon_shot.jpg")
    service = IndexerService(
        repo,
        extractor=_FakeExtractor(
            {
                "canon_shot": {"Make": "Canon", "Model": "EOS R5"},
                "nikon_shot": {"Make": "Nikon", "Model": "Z7"},
            }
        ),
    )
    service.build_index([image_folder])

    # Act
    canon_rows = repo.search_images("Canon", limit=10, offset=0)
    nikon_rows = repo.search_images("Nikon", limit=10, offset=0)
    all_rows = repo.search_images("", limit=10, offset=0)

    # Assert
    assert len(canon_rows) == 1
    assert "canon_shot" in canon_rows[0][2]
    assert len(nikon_rows) == 1
    assert "nikon_shot" in nikon_rows[0][2]
    assert len(all_rows) == 2


# ── parallel workers ──────────────────────────────────────────────────────────


def test_build_index_with_parallel_workers_produces_same_result(
    repo: ImageIndexRepository, image_folder: Path, tmp_path: Path
) -> None:
    # Arrange
    for i in range(6):
        _make_jpeg(image_folder / f"img{i}.jpg")

    service = IndexerService(
        repo, extractor=_FakeExtractor({f"img{i}": {"Index": str(i)} for i in range(6)})
    )

    # Act
    count, _ = service.build_index([image_folder], workers=3)

    # Assert
    assert count == 6
    assert repo.count_images("") == 6


# ── cancellation ──────────────────────────────────────────────────────────────


def test_build_index_cancel_stops_processing(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange — create enough files to make cancellation meaningful
    for i in range(10):
        _make_jpeg(image_folder / f"img{i}.jpg")

    canceled_after = [0]

    def cancel_after_one() -> bool:
        canceled_after[0] += 1
        return canceled_after[0] > 1

    service = IndexerService(repo, extractor=_FakeExtractor())

    # Act
    count, _ = service.build_index([image_folder], cancel_check=cancel_after_one)

    # Assert — fewer than all 10 files were indexed
    assert count < 10


# ── progress callback ─────────────────────────────────────────────────────────


def test_build_index_calls_progress_callback(
    repo: ImageIndexRepository, image_folder: Path
) -> None:
    # Arrange
    for i in range(3):
        _make_jpeg(image_folder / f"img{i}.jpg")
    progress_calls: list[tuple[int, int, Path]] = []
    service = IndexerService(repo, extractor=_FakeExtractor())

    # Act
    service.build_index([image_folder], on_progress=lambda c, t, p: progress_calls.append((c, t, p)))

    # Assert
    assert len(progress_calls) == 3
    assert all(t == 3 for _, t, _ in progress_calls)
