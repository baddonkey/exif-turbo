"""Contract for AI vector storage."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Protocol, Set

import numpy as np

from ..models.ai_model_profile import AiModelProfile


class AiVectorIndexError(RuntimeError):
    """The persisted image-vector index is incomplete or incompatible."""


class AiVectorBackend(Protocol):
    """Operations used by AI indexing and search."""

    @property
    def profile(self) -> AiModelProfile: ...

    @property
    def dimension(self) -> int: ...

    @property
    def storage_dir(self) -> Path: ...

    def load(self) -> None: ...

    def reset(self) -> None: ...

    def rebuild(self) -> None: ...

    def save(self) -> None: ...

    def close(self) -> None: ...

    def get_indexed_paths(self) -> set[str]: ...

    def get_vector_count(self) -> int: ...

    def get_vector(self, image_path: str) -> np.ndarray | None: ...

    def get_view_vectors(self, image_path: str) -> Dict[str, np.ndarray]: ...

    def get_vectors(self, image_paths: List[str]) -> Dict[str, np.ndarray | None]: ...

    def add_images(
        self,
        embeddings: np.ndarray,
        paths: List[str],
        *,
        view_ids: List[str] | None = None,
    ) -> None: ...

    def upsert_images(
        self,
        embeddings: np.ndarray,
        paths: List[str],
        *,
        view_ids: List[str] | None = None,
    ) -> None: ...

    def delete_images(self, image_paths: Set[str]) -> None: ...

    def remove_folder(self, folder_path: str) -> None: ...

    def search(
        self,
        query_vec: np.ndarray,
        top_k: int = 800,
        threshold: float = 0.20,
    ) -> List[tuple[str, float]]: ...

    def search_filtered(
        self,
        query_vec: np.ndarray,
        allowed_paths: Set[str],
        *,
        top_k: int | None = 800,
        threshold: float = 0.20,
    ) -> List[tuple[str, float]]: ...
