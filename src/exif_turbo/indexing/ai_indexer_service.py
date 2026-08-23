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
from io import BytesIO
import logging
from pathlib import Path
import ssl
import threading
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple
import urllib.request

import numpy as np

from ..data.ai_vector_repository import AiVectorRepository
from ..models.ai_model_profile import AiModelProfile, DEFAULT_AI_MODEL_PROFILE
from ..utils.preview_cache import preview_cache_name_from_stamp, preview_cache_path, preview_dir
from ..utils.thumb_crypto import ThumbCrypto

if TYPE_CHECKING:
    from PIL import Image

_log = logging.getLogger(__name__)

_BATCH_SIZE = 32
CLIP_MODEL_NAME = DEFAULT_AI_MODEL_PROFILE.model_name
CLIP_PRETRAINED = DEFAULT_AI_MODEL_PROFILE.pretrained
CLIP_VECTOR_DIMENSION = DEFAULT_AI_MODEL_PROFILE.dimension
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
_cached_profile_identifier: str | None = None
_open_clip_import_lock = threading.Lock()


class AiIndexerService:
    """Encode images with CLIP and persist their embeddings."""

    def __init__(
        self,
        vector_repo: AiVectorRepository,
        cache_dir: Path | None = None,
        *,
        profile: AiModelProfile = DEFAULT_AI_MODEL_PROFILE,
        preview_cache_dir: Path | None = None,
        preview_cache_key: str = "",
    ) -> None:
        if vector_repo.profile != profile:
            raise ValueError("AI encoder profile must match vector repository profile")
        self._repo = vector_repo
        self._profile = profile
        self._cache_dir = (
            cache_dir
            if cache_dir is not None
            else vector_repo.storage_dir / _OPEN_CLIP_CACHE_DIRNAME
        )
        self._preview_cache_dir = preview_cache_dir
        self._preview_cache_key = preview_cache_key
        # Model loaded lazily on first call to build_index.
        self._model = None
        self._preprocess = None
        self._tokenizer = None

    # ── Public API ────────────────────────────────────────────────────────

    def build_index(
        self,
        image_paths: List[str],
        stamps: dict[str, tuple[float, int]] | None = None,
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
            (
                embeddings,
                batch_errors,
                successful_paths,
                row_paths,
                view_ids,
            ) = self._encode_batch(
                batch_paths,
                stamps=stamps,
            )
            errors += batch_errors

            if successful_paths:
                self._repo.add_images(embeddings, row_paths, view_ids=view_ids)
                indexed += len(successful_paths)

            done = min(batch_start + _BATCH_SIZE, total)
            if on_progress:
                last_path = batch_paths[-1] if batch_paths else ""
                on_progress(done, total, last_path)

        return indexed, errors

    def encode_text(self, text: str) -> "np.ndarray":
        """Return a normalized float32 vector for *text* (for search)."""
        return self.encode_texts([text], batch_size=1)[0]

    @property
    def profile(self) -> AiModelProfile:
        return self._profile

    def encode_texts(
        self, texts: List[str], batch_size: int = _BATCH_SIZE
    ) -> "np.ndarray":
        """Encode text in bounded batches as normalized float32 rows."""
        import torch  # noqa: PLC0415

        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not texts:
            return np.empty((0, self._profile.dimension), dtype=np.float32)
        self._ensure_model_loaded()
        tokenizer = self._get_tokenizer()
        batches: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            with torch.no_grad():
                tokens = tokenizer(texts[start : start + batch_size])
                encoded = self._model.encode_text(tokens).float().numpy()  # type: ignore[union-attr]
            vectors = np.asarray(encoded, dtype=np.float32)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if np.any(norms == 0):
                raise ValueError("CLIP returned a zero-length text vector")
            batches.append(np.ascontiguousarray(vectors / norms, dtype=np.float32))
        return np.concatenate(batches, axis=0)

    # ── Internals ─────────────────────────────────────────────────────────

    def _ensure_model_loaded(self) -> None:
        global _cached_model, _cached_preprocess, _cached_profile_identifier
        if self._model is not None:
            return
        if _cached_model is not None and _cached_profile_identifier in (
            None,
            self._profile.identifier,
        ):
            self._model = _cached_model
            self._preprocess = _cached_preprocess
            return
        import torch  # noqa: PLC0415

        open_clip = self._import_open_clip()

        _log.debug(
            "Loading CLIP model %s (%s)",
            self._profile.model_name,
            self._profile.pretrained,
        )
        model_kwargs: dict[str, str] = {"cache_dir": str(self._cache_dir)}
        if self._profile.pretrained:
            model_kwargs["pretrained"] = self._profile.pretrained
        model, _, preprocess = open_clip.create_model_and_transforms(
            self._profile.model_ref,
            **model_kwargs,
        )
        model.eval()
        _cached_model = model
        _cached_preprocess = preprocess
        _cached_profile_identifier = self._profile.identifier
        self._model = model
        self._preprocess = preprocess
        _log.debug("CLIP model loaded.")

    def _get_tokenizer(self):
        if self._tokenizer is not None:
            return self._tokenizer

        open_clip = self._import_open_clip()
        self._tokenizer = open_clip.get_tokenizer(
            self._profile.model_ref,
            cache_dir=str(self._cache_dir),
        )
        return self._tokenizer

    def _import_open_clip(self):
        if not self._profile.requires_legacy_bpe:
            with _open_clip_import_lock:
                import open_clip  # noqa: PLC0415

                return open_clip

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

        try:
            import certifi  # noqa: PLC0415
            ssl_ctx: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ssl_ctx = None

        for url in _BPE_VOCAB_URLS:
            try:
                _log.info("Downloading OpenCLIP tokenizer vocabulary from %s", url)
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "exif-turbo"},
                )
                if ssl_ctx is None:
                    response_ctx = urllib.request.urlopen(request, timeout=60)
                else:
                    try:
                        response_ctx = urllib.request.urlopen(
                            request,
                            timeout=60,
                            context=ssl_ctx,
                        )
                    except TypeError as exc:
                        if "context" not in str(exc):
                            raise
                        response_ctx = urllib.request.urlopen(request, timeout=60)
                with response_ctx as response:
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
            f"Could not download OpenCLIP tokenizer vocabulary into {self._cache_dir}: "
            f"{last_error}"
        ) from last_error

    def _encode_batch(
        self,
        paths: List[str],
        *,
        stamps: dict[str, tuple[float, int]] | None = None,
    ) -> Tuple["np.ndarray", int, List[str], List[str], List[str]]:
        """Return view embeddings and image/row identities for *paths*."""
        import torch  # noqa: PLC0415

        tensors = []
        successful: List[str] = []
        row_paths: List[str] = []
        view_ids: List[str] = []
        errors = 0

        for path in paths:
            try:
                img = self._load_rgb_image(path, stamp=stamps.get(path) if stamps else None)
                views = self._build_image_views(img)
                image_tensors = [
                    self._preprocess(view) for _view_id, view in views  # type: ignore[misc]
                ]
                tensors.extend(image_tensors)
                row_paths.extend(path for _view_id, _view in views)
                view_ids.extend(view_id for view_id, _view in views)
                successful.append(path)
            except Exception as exc:  # noqa: BLE001
                _log.warning("AI-Scan: could not open %s: %s", path, exc)
                errors += 1

        if not tensors:
            return (
                np.empty((0, self._profile.dimension), dtype=np.float32),
                errors,
                [],
                [],
                [],
            )

        encoded_batches: list[np.ndarray] = []
        for start in range(0, len(tensors), _BATCH_SIZE):
            batch = torch.stack(tensors[start : start + _BATCH_SIZE])
            with torch.no_grad():
                vecs = self._model.encode_image(batch).float()  # type: ignore[union-attr]
            encoded_batches.append(np.asarray(vecs.numpy(), dtype=np.float32))
        vecs_np = np.concatenate(encoded_batches, axis=0)
        norms = np.linalg.norm(vecs_np, axis=1, keepdims=True)
        vecs_np = vecs_np / np.where(norms > 0, norms, 1.0)
        return vecs_np.astype(np.float32), errors, successful, row_paths, view_ids

    @staticmethod
    def _build_image_views(image: "Image.Image") -> tuple[tuple[str, "Image.Image"], ...]:
        size = image.size
        if (
            not isinstance(size, tuple)
            or len(size) != 2
            or not all(isinstance(value, int) for value in size)
            or size[0] < 2
            or size[1] < 2
        ):
            return (("full", image),)
        width, height = size
        crop_width = max(1, round(width * 0.7))
        crop_height = max(1, round(height * 0.7))
        right = width - crop_width
        bottom = height - crop_height
        boxes = (
            ("top_left", (0, 0, crop_width, crop_height)),
            ("top_right", (right, 0, width, crop_height)),
            ("bottom_left", (0, bottom, crop_width, height)),
            ("bottom_right", (right, bottom, width, height)),
        )
        return (("full", image),) + tuple(
            (view_id, image.crop(box)) for view_id, box in boxes
        )

    def _load_rgb_image(
        self,
        path: str,
        *,
        stamp: tuple[float, int] | None = None,
    ) -> "Image.Image":
        from PIL import Image, ImageOps  # noqa: PLC0415

        preview = self._load_cached_preview(path, stamp=stamp)
        if preview is not None:
            return preview
        with Image.open(path) as img:
            return ImageOps.exif_transpose(img).convert("RGB")

    def _load_cached_preview(
        self,
        path: str,
        *,
        stamp: tuple[float, int] | None = None,
    ) -> "Image.Image | None":
        from PIL import Image  # noqa: PLC0415

        if self._preview_cache_dir is None:
            return None

        cache_path = self._resolve_preview_cache_path(path, stamp=stamp)
        try:
            if self._preview_cache_key:
                enc_path = cache_path.with_suffix(".jpg.enc")
                if enc_path.exists():
                    crypto = ThumbCrypto(self._preview_cache_key, self._preview_cache_dir)
                    data = crypto.decrypt(enc_path.read_bytes())
                    with Image.open(BytesIO(data)) as img:
                        return img.convert("RGB")

            if cache_path.exists():
                with Image.open(cache_path) as img:
                    return img.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            _log.warning("AI-Scan: could not read cached preview for %s: %s", path, exc)

        return None

    def _resolve_preview_cache_path(
        self,
        path: str,
        *,
        stamp: tuple[float, int] | None = None,
    ) -> Path:
        assert self._preview_cache_dir is not None
        if stamp is not None:
            name = preview_cache_name_from_stamp(path, stamp[0], stamp[1])
            return preview_dir(self._preview_cache_dir) / name

        return preview_cache_path(path, self._preview_cache_dir)


def image_paths_for_folder(
    folder_stamps: dict[str, tuple[float, int]],
) -> List[str]:
    """Convert a {path: (mtime, size)} dict from the repo into a plain path list."""
    return list(folder_stamps.keys())
