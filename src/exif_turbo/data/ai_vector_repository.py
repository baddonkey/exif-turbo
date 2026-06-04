"""Persist CLIP embeddings in a FAISS flat inner-product index.

Layout on disk (both files live in the same directory as the SQLite DB):
  ai_index.faiss   — raw FAISS index (IndexFlatIP, dim=512)
  ai_id_map.json   — {"0": "/path/img.jpg", "1": ...}  (FAISS row id → path)

All vectors stored here are L2-normalised so inner-product search equals
cosine similarity.  Sequential integer IDs (0, 1, 2, …) are assigned by
IndexFlatIP.add() and are the keys in the JSON id-map.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Set

import numpy as np

_log = logging.getLogger(__name__)

_DIM = 512  # ViT-B/32 CLIP embedding dimension


class AiVectorRepository:
    """Manages a single FAISS flat index plus an in-memory id→path mapping."""

    def __init__(self, index_path: Path, id_map_path: Path) -> None:
        self._index_path = index_path
        self._id_map_path = id_map_path
        self._faiss = None
        self._index = None
        # Maps str(sequential_faiss_id) → absolute image path.
        self._id_map: Dict[str, str] = {}

    @property
    def storage_dir(self) -> Path:
        """Directory containing this repository's persisted files."""
        return self._index_path.parent

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load existing index + map from disk; create empty ones if absent."""
        import faiss  # noqa: PLC0415

        self._faiss = faiss
        if self._index_path.exists() and self._id_map_path.exists():
            try:
                self._index = faiss.read_index(str(self._index_path))
                raw = json.loads(self._id_map_path.read_text(encoding="utf-8"))
                self._id_map = {str(k): v for k, v in raw.items()}
                _log.debug(
                    "AI index loaded: %d vectors from %s",
                    self._index.ntotal,
                    self._index_path,
                )
                return
            except Exception as exc:  # noqa: BLE001
                _log.warning("AI index corrupt, rebuilding from scratch: %s", exc)

        self._index = faiss.IndexFlatIP(_DIM)
        self._id_map = {}

    def save(self) -> None:
        """Persist the current index and id-map to disk."""
        if self._faiss is None or self._index is None:
            raise RuntimeError("load() must be called before save()")
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self._index, str(self._index_path))
        self._id_map_path.write_text(
            json.dumps(self._id_map, ensure_ascii=False, indent=None),
            encoding="utf-8",
        )

    # ── Queries ───────────────────────────────────────────────────────────

    def get_indexed_paths(self) -> set[str]:
        """Return the set of image paths that already have a vector."""
        return set(self._id_map.values())

    # ── Mutations ─────────────────────────────────────────────────────────

    def add_images(self, embeddings: "np.ndarray", paths: List[str]) -> None:
        """Append a batch of L2-normalised embeddings with their file paths.

        *embeddings* must be a float32 array of shape (N, 512).
        *paths* must have length N.  Duplicate paths are not checked here —
        the caller (AiIndexerService) is responsible for skipping already-
        indexed images.
        """
        if self._index is None:
            raise RuntimeError("load() must be called before add_images()")
        n = len(paths)
        if n == 0:
            return
        vecs = np.asarray(embeddings, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        start_id = self._index.ntotal
        self._index.add(vecs)
        for i, path in enumerate(paths):
            self._id_map[str(start_id + i)] = path

    def remove_folder(self, folder_path: str) -> None:
        """Remove every vector whose path is inside *folder_path*.

        IndexFlatIP does not support in-place deletion, so surviving vectors
        are reconstructed and a new index is built from scratch.
        """
        if self._faiss is None or self._index is None or self._index.ntotal == 0:
            return

        folder = Path(folder_path)
        keep_ids: List[int] = [
            int(k)
            for k, v in self._id_map.items()
            if not _is_inside(v, folder)
        ]
        if len(keep_ids) == self._index.ntotal:
            return  # nothing to remove

        if not keep_ids:
            self._index = self._faiss.IndexFlatIP(_DIM)
            self._id_map = {}
            return

        # Reconstruct surviving vectors by their sequential FAISS position.
        vecs = np.zeros((len(keep_ids), _DIM), dtype=np.float32)
        for row, old_id in enumerate(keep_ids):
            self._index.reconstruct(old_id, vecs[row])

        new_index = self._faiss.IndexFlatIP(_DIM)
        new_index.add(vecs)

        new_map: Dict[str, str] = {
            str(new_i): self._id_map[str(old_id)]
            for new_i, old_id in enumerate(keep_ids)
        }
        self._index = new_index
        self._id_map = new_map

    # ── Search ────────────────────────────────────────────────────────────

    def search(
        self, query_vec: "np.ndarray", top_k: int = 800, threshold: float = 0.20
    ) -> List[tuple[str, float]]:
        """Return (path, score) pairs with cosine similarity >= *threshold*.

        Searches the top *top_k* candidates (capped at index size) then
        discards anything below *threshold*.  Results are sorted descending
        by score.

        *query_vec* must be a float32 array of shape (512,) or (1, 512).
        It will be L2-normalised before searching.
        """
        return self._search_internal(query_vec, top_k=top_k, threshold=threshold)

    def search_filtered(
        self,
        query_vec: "np.ndarray",
        allowed_paths: Set[str],
        *,
        top_k: int = 800,
        threshold: float = 0.20,
    ) -> List[tuple[str, float]]:
        """Return ranked hits limited to *allowed_paths*.

        Filtering is applied before the final ``top_k`` cap so out-of-scope
        vectors cannot crowd out in-scope matches.
        """
        if not allowed_paths:
            return []
        return self._search_internal(
            query_vec,
            top_k=top_k,
            threshold=threshold,
            allowed_paths=allowed_paths,
        )

    def _search_internal(
        self,
        query_vec: "np.ndarray",
        *,
        top_k: int,
        threshold: float,
        allowed_paths: Set[str] | None = None,
    ) -> List[tuple[str, float]]:
        if self._index is None or self._index.ntotal == 0:
            return []
        vec = np.asarray(query_vec, dtype=np.float32).reshape(1, -1)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        k = self._index.ntotal if allowed_paths is not None else min(top_k, self._index.ntotal)
        scores, ids = self._index.search(vec, k)
        results: List[tuple[str, float]] = []
        for score, idx in zip(scores[0], ids[0]):
            if idx < 0:
                continue
            if float(score) < threshold:
                break  # results are sorted descending — no more hits above threshold
            path = self._id_map.get(str(int(idx)))
            if path is None:
                continue
            if allowed_paths is not None and path not in allowed_paths:
                continue
            results.append((path, float(score)))
            if len(results) >= top_k:
                break
        return results


def _is_inside(image_path: str, folder: Path) -> bool:
    """Return True when *image_path* is the folder itself or a descendant."""
    try:
        return Path(image_path).is_relative_to(folder)
    except ValueError:
        return False
