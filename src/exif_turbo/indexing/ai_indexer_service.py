"""Vectorise images using OpenCLIP (ViT-B/32) and add them to AiVectorRepository.

Usage::

    repo = AiVectorRepository(index_path, id_map_path)
    repo.load()
    service = AiIndexerService(repo)
    indexed, errors = service.build_index(
        image_paths,
        on_progress=lambda done, total, path: ...,
        cancel_check=lambda: False,
    )
    repo.save()
"""
from __future__ import annotations

import gzip
import logging
from pathlib import Path
import threading
from typing import Callable, List, Optional, Tuple
import urllib.request

import numpy as np

from ..data.ai_vector_repository import AiVectorRepository

_log = logging.getLogger(__name__)

_BATCH_SIZE = 32
_MODEL_NAME = "ViT-B-32"
_PRETRAINED = "openai"
_OPEN_CLIP_CACHE_DIRNAME = "open_clip"
_BPE_VOCAB_FILENAME = "bpe_simple_vocab_16e6.txt.gz"
_BPE_VOCAB_URLS = (
    "https://openaipublic.azureedge.net/clip/bpe_simple_vocab_16e6.txt.gz",
    "https://github.com/openai/CLIP/raw/main/clip/bpe_simple_vocab_16e6.txt.gz",
)

# Module-level cache — the CLIP model is ~350 MB and takes 10-30 s to load
# from disk.  Caching it here means every AiIndexerService / AiSearchWorker
# reuses the same loaded model, so the Python GIL is only held for the long
# torch.load() call once per app lifetime.
_cached_model = None
_cached_preprocess = None
_open_clip_import_lock = threading.Lock()


class AiIndexerService:
    """Encode images with CLIP and persist their embeddings."""

    def __init__(
        self,
        vector_repo: AiVectorRepository,
        cache_dir: Path | None = None,
    ) -> None:
        self._repo = vector_repo
        self._cache_dir = (
            cache_dir
            if cache_dir is not None
            else vector_repo.storage_dir / _OPEN_CLIP_CACHE_DIRNAME
        )
        # Model loaded lazily on first call to build_index.
        self._model = None
        self._preprocess = None
        self._tokenizer = None

    # ── Public API ────────────────────────────────────────────────────────

    def build_index(
        self,
        image_paths: List[str],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Tuple[int, int]:
        """Encode all *image_paths* that are not yet in the repo.

        Returns ``(indexed_count, error_count)``.
        Calls ``on_progress(done, total, current_path)`` after every batch.
        Calls ``cancel_check()`` before every batch; stops if it returns True.
        """
        already_indexed = self._repo.get_indexed_paths()
        pending = [p for p in image_paths if p not in already_indexed]
        total = len(pending)
        if total == 0:
            return 0, 0

        self._ensure_model_loaded()

        indexed = 0
        errors = 0

        for batch_start in range(0, total, _BATCH_SIZE):
            if cancel_check and cancel_check():
                break

            batch_paths = pending[batch_start : batch_start + _BATCH_SIZE]
            embeddings, batch_errors, successful_paths = self._encode_batch(
                batch_paths
            )
            errors += batch_errors

            if successful_paths:
                self._repo.add_images(embeddings, successful_paths)
                indexed += len(successful_paths)

            done = min(batch_start + _BATCH_SIZE, total)
            if on_progress:
                last_path = batch_paths[-1] if batch_paths else ""
                on_progress(done, total, last_path)

        return indexed, errors

    def encode_text(self, text: str) -> "np.ndarray":
        """Return a normalised 512-d float32 vector for *text* (for search)."""
        import torch  # noqa: PLC0415

        self._ensure_model_loaded()
        tokenizer = self._get_tokenizer()
        with torch.no_grad():
            tokens = tokenizer([text])
            vec = self._model.encode_text(tokens).float().numpy()  # type: ignore[union-attr]
        vec = vec / np.linalg.norm(vec, axis=1, keepdims=True)
        return vec.squeeze(0)

    # ── Internals ─────────────────────────────────────────────────────────

    def _ensure_model_loaded(self) -> None:
        global _cached_model, _cached_preprocess
        if _cached_model is not None:
            self._model = _cached_model
            self._preprocess = _cached_preprocess
            return
        import torch  # noqa: PLC0415

        open_clip = self._import_open_clip()

        _log.debug("Loading CLIP model %s (%s)…", _MODEL_NAME, _PRETRAINED)
        model, _, preprocess = open_clip.create_model_and_transforms(
            _MODEL_NAME,
            pretrained=_PRETRAINED,
            cache_dir=str(self._cache_dir),
        )
        model.eval()
        _cached_model = model
        _cached_preprocess = preprocess
        self._model = model
        self._preprocess = preprocess
        _log.debug("CLIP model loaded.")

    def _get_tokenizer(self):
        if self._tokenizer is not None:
            return self._tokenizer

        open_clip = self._import_open_clip()
        bpe_path = self._ensure_bpe_vocab_downloaded()
        self._tokenizer = open_clip.SimpleTokenizer(bpe_path=str(bpe_path))
        return self._tokenizer

    def _import_open_clip(self):
        bpe_path = self._ensure_bpe_vocab_downloaded()

        def _gzip_open_with_bpe_fallback(filename, *args, **kwargs):
            try:
                candidate_path = Path(filename)
            except TypeError:
                candidate_path = None

            if (
                candidate_path is not None
                and candidate_path.name == _BPE_VOCAB_FILENAME
                and not candidate_path.exists()
            ):
                return original_gzip_open(bpe_path, *args, **kwargs)

            return original_gzip_open(filename, *args, **kwargs)

        with _open_clip_import_lock:
            original_gzip_open = gzip.open
            gzip.open = _gzip_open_with_bpe_fallback
            try:
                import open_clip  # noqa: PLC0415

                return open_clip
            finally:
                gzip.open = original_gzip_open

    def _ensure_bpe_vocab_downloaded(self) -> Path:
        vocab_path = self._cache_dir / _BPE_VOCAB_FILENAME
        if vocab_path.exists():
            return vocab_path

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self._cache_dir / f"{_BPE_VOCAB_FILENAME}.tmp"
        last_error: Exception | None = None

        for url in _BPE_VOCAB_URLS:
            try:
                _log.info("Downloading OpenCLIP tokenizer vocabulary from %s", url)
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "exif-turbo"},
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    temp_path.write_bytes(response.read())
                temp_path.replace(vocab_path)
                return vocab_path
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                _log.warning(
                    "Could not download OpenCLIP tokenizer vocabulary from %s: %s",
                    url,
                    exc,
                )
                temp_path.unlink(missing_ok=True)

        raise RuntimeError(
            "Could not download OpenCLIP tokenizer vocabulary into "
            f"{self._cache_dir}"
        ) from last_error

    def _encode_batch(
        self, paths: List[str]
    ) -> Tuple["np.ndarray", int, List[str]]:
        """Return (embeddings, error_count, successful_paths) for *paths*."""
        import torch  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        tensors = []
        successful: List[str] = []
        errors = 0

        for path in paths:
            try:
                img = Image.open(path).convert("RGB")
                tensors.append(self._preprocess(img))  # type: ignore[misc]
                successful.append(path)
            except Exception as exc:  # noqa: BLE001
                _log.warning("AI-Scan: could not open %s: %s", path, exc)
                errors += 1

        if not tensors:
            return np.empty((0, 512), dtype=np.float32), errors, []

        batch = torch.stack(tensors)
        with torch.no_grad():
            vecs = self._model.encode_image(batch).float()  # type: ignore[union-attr]

        vecs_np = vecs.numpy()
        norms = np.linalg.norm(vecs_np, axis=1, keepdims=True)
        vecs_np = vecs_np / np.where(norms > 0, norms, 1.0)
        return vecs_np.astype(np.float32), errors, successful


def image_paths_for_folder(
    folder_stamps: dict[str, tuple[float, int]],
) -> List[str]:
    """Convert a {path: (mtime, size)} dict from the repo into a plain path list."""
    return list(folder_stamps.keys())
