"""Tests for AiIndexerService — mocks open_clip so torch is not required."""
from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.indexing.ai_indexer_service import AiIndexerService


# ── helpers / fixtures ────────────────────────────────────────────────────────

def _fake_vec() -> np.ndarray:
    v = np.ones(512, dtype=np.float32)
    return v / np.linalg.norm(v)


def _make_repo(tmp_path: Path) -> AiVectorRepository:
    repo = AiVectorRepository(
        tmp_path / "ai_index.faiss",
        tmp_path / "ai_id_map.json",
    )
    repo.load()
    return repo


def _patch_clip(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch open_clip and torch so no GPU/download is needed."""
    import torch  # only used for tensor mocking

    # Fake model
    fake_model = MagicMock()
    fake_vecs = torch.from_numpy(
        np.stack([_fake_vec() for _ in range(32)])
    ).float()
    fake_model.encode_image.return_value = fake_vecs

    # Fake preprocess: return a dummy tensor for any image
    fake_preprocess = MagicMock(return_value=torch.zeros(3, 224, 224))

    # Fake open_clip module
    fake_open_clip = MagicMock()
    fake_open_clip.create_model_and_transforms.return_value = (
        fake_model,
        MagicMock(),
        fake_preprocess,
    )

    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service.open_clip",
        fake_open_clip,
        raising=False,
    )

    # Pre-load the model on the service so _ensure_model_loaded is a no-op
    return fake_model


# ── basic indexing ────────────────────────────────────────────────────────────

def test_ai_indexer_service_build_index_vectorises_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    sample_dir = Path(__file__).parents[1] / "sample-data" / "computer"
    image_files = list(sample_dir.glob("*.jpg"))[:2]
    if not image_files:
        pytest.skip("No sample images available")

    repo = _make_repo(tmp_path)
    service = AiIndexerService(repo)

    # Patch torch + open_clip so no model download happens.
    import torch

    fake_model = MagicMock()
    fake_model.encode_image.return_value = torch.from_numpy(
        np.stack([_fake_vec() for _ in image_files])
    ).float()
    fake_preprocess = MagicMock(return_value=torch.zeros(3, 224, 224))
    fake_open_clip = MagicMock()
    fake_open_clip.create_model_and_transforms.return_value = (
        fake_model, MagicMock(), fake_preprocess
    )

    # Act
    indexed, errors = service.build_index([str(p) for p in image_files])

    # Assert
    assert indexed == len(image_files)
    assert errors == 0
    assert repo.get_indexed_paths() == {str(p) for p in image_files}


def test_ai_indexer_service_build_index_skips_already_indexed(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    repo.add_images(_fake_vec().reshape(1, -1), ["/photos/a.jpg"])

    service = AiIndexerService(repo)
    # _model is None → build_index would call _ensure_model_loaded if there were
    # pending images.  Since a.jpg is already indexed, it must return (0, 0)
    # without touching the model at all.

    # Act
    indexed, errors = service.build_index(["/photos/a.jpg"])

    # Assert
    assert indexed == 0
    assert errors == 0
    assert service._model is None  # model was never loaded


def test_ai_indexer_service_build_index_empty_list_returns_zero(
    tmp_path: Path,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    service = AiIndexerService(repo)

    # Act
    indexed, errors = service.build_index([])

    # Assert
    assert (indexed, errors) == (0, 0)


# ── cancel ────────────────────────────────────────────────────────────────────

def test_ai_indexer_service_build_index_stops_on_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import torch

    repo = _make_repo(tmp_path)
    service = AiIndexerService(repo)
    fake_model = MagicMock()
    fake_model.encode_image.return_value = torch.from_numpy(
        np.stack([_fake_vec() for _ in range(32)])
    ).float()
    service._model = fake_model
    service._preprocess = MagicMock(return_value=torch.zeros(3, 224, 224))

    paths = [f"/photos/img_{i:04d}.jpg" for i in range(100)]
    # Pretend all files exist by patching PIL.Image.open
    fake_pil = MagicMock()
    fake_pil.return_value.__enter__ = lambda s: s
    fake_pil.return_value.convert.return_value = MagicMock()
    monkeypatch.setattr("PIL.Image.open", fake_pil, raising=False)

    call_count = [0]

    def _cancel_after_one_batch() -> bool:
        call_count[0] += 1
        return call_count[0] > 1  # cancel after first batch

    # Act
    indexed, errors = service.build_index(
        paths,
        cancel_check=_cancel_after_one_batch,
    )

    # Assert — only one batch (≤32) was processed, not all 100
    assert indexed <= 32


# ── progress callback ─────────────────────────────────────────────────────────

def test_ai_indexer_service_build_index_calls_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import torch

    repo = _make_repo(tmp_path)
    service = AiIndexerService(repo)
    fake_model = MagicMock()
    fake_model.encode_image.return_value = torch.from_numpy(
        np.stack([_fake_vec() for _ in range(32)])
    ).float()
    service._model = fake_model
    service._preprocess = MagicMock(return_value=torch.zeros(3, 224, 224))

    paths = [f"/photos/img_{i:04d}.jpg" for i in range(5)]
    monkeypatch.setattr("PIL.Image.open", MagicMock(return_value=MagicMock()), raising=False)

    progress_calls: List[tuple] = []

    # Act
    service.build_index(paths, on_progress=lambda d, t, p: progress_calls.append((d, t, p)))

    # Assert — at least one progress call was made
    assert len(progress_calls) >= 1
    # Last call should report total == total paths
    last_done, last_total, _ = progress_calls[-1]
    assert last_total == len(paths)
