"""Tests for AiIndexerService — mocks open_clip so torch is not required."""
from __future__ import annotations

import builtins
from contextlib import nullcontext
import gzip
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.indexing.ai_indexer_service import AiIndexerService
from exif_turbo.utils.preview_cache import preview_cache_name_from_stamp, preview_cache_path, preview_dir
from exif_turbo.utils.thumb_crypto import ThumbCrypto


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


def _write_jpeg(path: Path, size: tuple[int, int]) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(64, 96, 128)).save(path, "JPEG")


class _FakeTensor:
    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def float(self) -> "_FakeTensor":
        return self

    def numpy(self) -> np.ndarray:
        return self._array


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
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_model",
        fake_model,
    )
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_preprocess",
        fake_preprocess,
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


@pytest.mark.parametrize(
    ("encrypted", "key"),
    [(False, ""), (True, "secret")],
)
def test_ai_indexer_service_build_index_prefers_cached_preview_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    encrypted: bool,
    key: str,
) -> None:
    # Arrange
    import torch

    repo = _make_repo(tmp_path)
    cache_dir = tmp_path / "thumbs"
    source_path = tmp_path / "photos" / "source.jpg"
    _write_jpeg(source_path, (40, 25))

    preview_path = preview_cache_path(str(source_path), cache_dir)
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    preview_bytes = BytesIO()
    _write_jpeg(tmp_path / "preview-source.jpg", (9, 5))
    with open(tmp_path / "preview-source.jpg", "rb") as stream:
        preview_bytes.write(stream.read())
    if encrypted:
        crypto = ThumbCrypto(key, cache_dir)
        preview_path.with_suffix(".jpg.enc").write_bytes(
            crypto.encrypt(preview_bytes.getvalue())
        )
    else:
        preview_path.write_bytes(preview_bytes.getvalue())

    seen_sizes: list[tuple[int, int]] = []

    def _fake_preprocess(img):  # type: ignore[no-untyped-def]
        seen_sizes.append(img.size)
        return torch.zeros(3, 224, 224)

    fake_model = MagicMock()
    fake_model.encode_image.return_value = torch.from_numpy(
        np.stack([_fake_vec()])
    ).float()

    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_model",
        fake_model,
    )
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_preprocess",
        _fake_preprocess,
    )

    service = AiIndexerService(
        repo,
        preview_cache_dir=cache_dir,
        preview_cache_key=key,
    )

    # Act
    indexed, errors = service.build_index([str(source_path)])

    # Assert
    assert (indexed, errors, seen_sizes) == (1, 0, [(9, 5)])


def test_ai_indexer_service_build_index_uses_db_stamp_to_load_cached_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import torch

    repo = _make_repo(tmp_path)
    cache_dir = tmp_path / "thumbs"
    source_path = tmp_path / "photos" / "source.jpg"
    _write_jpeg(source_path, (40, 25))

    stamp = (123.0, 456)
    preview_name = preview_cache_name_from_stamp(str(source_path), stamp[0], stamp[1])
    preview_path = preview_dir(cache_dir) / preview_name
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jpeg(preview_path, (9, 5))
    source_path.unlink()

    seen_sizes: list[tuple[int, int]] = []

    def _fake_preprocess(img):  # type: ignore[no-untyped-def]
        seen_sizes.append(img.size)
        return torch.zeros(3, 224, 224)

    fake_model = MagicMock()
    fake_model.encode_image.return_value = torch.from_numpy(
        np.stack([_fake_vec()])
    ).float()

    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_model",
        fake_model,
    )
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_preprocess",
        _fake_preprocess,
    )

    service = AiIndexerService(repo, preview_cache_dir=cache_dir)

    # Act
    indexed, errors = service.build_index([str(source_path)], stamps={str(source_path): stamp})

    # Assert
    assert (indexed, errors, seen_sizes) == (1, 0, [(9, 5)])


def test_ai_indexer_service_build_index_falls_back_to_original_when_preview_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import torch

    repo = _make_repo(tmp_path)
    cache_dir = tmp_path / "thumbs"
    source_path = tmp_path / "photos" / "source.jpg"
    _write_jpeg(source_path, (40, 25))

    preview_path = preview_cache_path(str(source_path), cache_dir)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"not-a-jpeg")

    seen_sizes: list[tuple[int, int]] = []

    def _fake_preprocess(img):  # type: ignore[no-untyped-def]
        seen_sizes.append(img.size)
        return torch.zeros(3, 224, 224)

    fake_model = MagicMock()
    fake_model.encode_image.return_value = torch.from_numpy(
        np.stack([_fake_vec()])
    ).float()

    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_model",
        fake_model,
    )
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_preprocess",
        _fake_preprocess,
    )

    service = AiIndexerService(repo, preview_cache_dir=cache_dir)

    # Act
    indexed, errors = service.build_index([str(source_path)])

    # Assert
    assert (indexed, errors, seen_sizes) == (1, 0, [(40, 25)])


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


def test_ai_indexer_service_encode_text_downloads_bpe_vocab_into_repo_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    service = AiIndexerService(repo)

    fake_tokenizer = MagicMock(return_value="TOKENS")
    fake_open_clip = SimpleNamespace(
        SimpleTokenizer=MagicMock(return_value=fake_tokenizer),
    )
    fake_torch = SimpleNamespace(no_grad=nullcontext)
    fake_model = MagicMock()
    fake_model.encode_text.return_value = _FakeTensor(_fake_vec().reshape(1, -1))

    monkeypatch.setitem(sys.modules, "open_clip", fake_open_clip)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_model",
        fake_model,
    )
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_preprocess",
        MagicMock(),
    )

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b"fake-bpe-data"

    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service.urllib.request.urlopen",
        lambda request, timeout=60: _FakeResponse(),
    )

    # Act
    vector = service.encode_text("forest trail")

    # Assert
    expected_bpe = tmp_path / "open_clip" / "bpe_simple_vocab_16e6.txt.gz"
    assert expected_bpe.exists()
    assert np.allclose(vector, _fake_vec())
    assert fake_open_clip.SimpleTokenizer.call_args.kwargs["bpe_path"] == str(expected_bpe)


def test_ai_indexer_service_model_load_uses_repo_storage_cache_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    service = AiIndexerService(repo)

    fake_model = MagicMock()
    fake_model.eval = MagicMock()
    fake_preprocess = MagicMock()
    fake_open_clip = SimpleNamespace(
        create_model_and_transforms=MagicMock(
            return_value=(fake_model, MagicMock(), fake_preprocess)
        )
    )

    monkeypatch.setitem(sys.modules, "open_clip", fake_open_clip)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_model",
        None,
    )
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_preprocess",
        None,
    )
    (tmp_path / "open_clip").mkdir(parents=True, exist_ok=True)
    (tmp_path / "open_clip" / "bpe_simple_vocab_16e6.txt.gz").write_bytes(
        b"fake-bpe-data"
    )

    # Act
    service._ensure_model_loaded()

    # Assert
    assert fake_open_clip.create_model_and_transforms.call_args.kwargs["cache_dir"] == str(
        tmp_path / "open_clip"
    )


def test_ai_indexer_service_model_load_imports_open_clip_with_user_bpe_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    repo = _make_repo(tmp_path)
    service = AiIndexerService(repo)

    fake_model = MagicMock()
    fake_model.eval = MagicMock()
    fake_preprocess = MagicMock()
    fake_open_clip = SimpleNamespace(
        create_model_and_transforms=MagicMock(
            return_value=(fake_model, MagicMock(), fake_preprocess)
        )
    )
    bpe_payload = gzip.compress(b"#version: 0.2\na b\n")
    missing_bpe_path = (
        tmp_path
        / "frozen-app"
        / "_internal"
        / "open_clip"
        / "bpe_simple_vocab_16e6.txt.gz"
    )

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return bpe_payload

    original_import = builtins.__import__

    def _fake_import(
        name: str,
        globals=None,
        locals=None,
        fromlist=(),
        level: int = 0,
    ):
        if name == "open_clip":
            with gzip.open(missing_bpe_path, "rb") as stream:
                assert stream.read() == b"#version: 0.2\na b\n"
            return fake_open_clip
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service.urllib.request.urlopen",
        lambda request, timeout=60: _FakeResponse(),
    )
    monkeypatch.setattr(
        "builtins.__import__",
        _fake_import,
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_model",
        None,
    )
    monkeypatch.setattr(
        "exif_turbo.indexing.ai_indexer_service._cached_preprocess",
        None,
    )

    # Act
    service._ensure_model_loaded()

    # Assert
    assert fake_open_clip.create_model_and_transforms.call_args.kwargs["cache_dir"] == str(
        tmp_path / "open_clip"
    )
    assert (tmp_path / "open_clip" / "bpe_simple_vocab_16e6.txt.gz").exists()
