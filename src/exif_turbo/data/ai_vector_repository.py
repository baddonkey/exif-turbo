"""Persist model-bound image embeddings in a FAISS inner-product index."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from collections.abc import Iterator
from typing import Dict, List, Set

import numpy as np

from ..models.ai_model_profile import AiModelProfile, DEFAULT_AI_MODEL_PROFILE
from .ai_vector_storage import AiVectorAuthenticationError, AiVectorStorage


class AiVectorIndexError(RuntimeError):
        """The persisted image-vector index is incomplete or incompatible."""


class AiVectorRepository:
    """Manages a single FAISS flat index plus an in-memory id→path mapping."""

    def __init__(
        self,
        index_path: Path,
        id_map_path: Path,
        metadata_path: Path | None = None,
        *,
        profile: AiModelProfile = DEFAULT_AI_MODEL_PROFILE,
        key: str = "",
    ) -> None:
        self._index_path = index_path
        self._id_map_path = id_map_path
        self._metadata_path = metadata_path or index_path.with_name("ai_index_meta.json")
        self._profile = profile
        self._dimension = profile.dimension
        self._key = key
        self._storage = AiVectorStorage(index_path, key)
        self._faiss = None
        self._index = None
        self._authenticated_snapshot = False
        # Maps str(sequential_faiss_id) to an image path and deterministic view.
        self._id_map: Dict[str, dict[str, str]] = {}
        self._path_map: Dict[str, List[int]] = {}

    @property
    def storage_dir(self) -> Path:
        """Directory containing this repository's persisted files."""
        return self._index_path.parent

    @property
    def profile(self) -> AiModelProfile:
        return self._profile

    @property
    def dimension(self) -> int:
        return self._dimension

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load existing index + map from disk; create empty ones if absent."""
        self._load(require_authenticated=False)

    def load_migration_source(self) -> None:
        """Load an authenticated snapshot without rewriting or deleting it."""
        self._load(require_authenticated=True)

    def _load(self, *, require_authenticated: bool) -> None:
        import faiss  # noqa: PLC0415

        self._authenticated_snapshot = False
        self._faiss = faiss
        paths = (self._index_path, self._id_map_path, self._metadata_path)
        existing = tuple(path.exists() for path in paths)
        encrypted = self._storage.path.exists()
        if require_authenticated and not encrypted:
            raise AiVectorIndexError("An authenticated AI snapshot is required for migration")
        if not encrypted and not any(existing):
            self._index = faiss.IndexFlatIP(self._dimension)
            self._id_map = {}
            self._path_map = {}
            return
        if not encrypted and not all(existing):
            raise AiVectorIndexError(
                "AI vector index has no compatible model metadata; "
                "run AI Full Rescan"
            )

        try:
            if encrypted:
                index_bytes, map_bytes, metadata_bytes = self._storage.load()
                index = faiss.deserialize_index(np.frombuffer(index_bytes, dtype=np.uint8))
            else:
                index_bytes = self._index_path.read_bytes()
                map_bytes = self._id_map_path.read_bytes()
                metadata_bytes = self._metadata_path.read_bytes()
                index = faiss.deserialize_index(np.frombuffer(index_bytes, dtype=np.uint8))
            raw_map = json.loads(map_bytes)
            metadata = json.loads(metadata_bytes)
            if not isinstance(raw_map, dict) or not isinstance(metadata, dict):
                raise ValueError("metadata or ID map has the wrong shape")
            if int(metadata["schema_version"]) != 2:
                raise ValueError("unsupported metadata schema")
            if str(metadata["model_fingerprint"]) != self._profile.identifier:
                raise ValueError(
                    f"index uses model {metadata['model_fingerprint']}, "
                    f"expected {self._profile.identifier}"
                )
            if require_authenticated and (
                metadata["model_name"] != self._profile.model_name
                or metadata["pretrained"] != self._profile.pretrained
                or metadata["view_strategy"] != "full-plus-four-corners-v1"
            ):
                raise ValueError("AI snapshot model or view strategy does not match")
            if int(metadata["dimension"]) != self._dimension or index.d != self._dimension:
                raise ValueError(
                    f"expected {self._dimension}-dimensional vectors, found {index.d}"
                )
            if not all(
                isinstance(value, dict)
                and set(value) == {"path", "view_id"}
                and isinstance(value["path"], str)
                and isinstance(value["view_id"], str)
                for value in raw_map.values()
            ):
                raise ValueError("ID map rows must contain path and view_id")
            id_map = {
                str(key): {"path": value["path"], "view_id": value["view_id"]}
                for key, value in raw_map.items()
            }
            if index.ntotal != len(id_map) or index.ntotal != int(metadata["count"]):
                raise ValueError("FAISS count, ID map, and metadata count differ")
            if hashlib.sha256(index_bytes).hexdigest() != str(metadata["index_sha256"]):
                raise ValueError("FAISS index checksum does not match metadata")
            if hashlib.sha256(map_bytes).hexdigest() != str(metadata["map_sha256"]):
                raise ValueError("ID map checksum does not match metadata")
        except (AiVectorIndexError, AiVectorAuthenticationError):
            raise
        except Exception as exc:  # noqa: BLE001
            raise AiVectorIndexError(
                f"AI vector index is incompatible or corrupt; run AI Full Rescan: {exc}"
            ) from exc

        self._index = index
        self._id_map = id_map
        self._rebuild_path_map()
        self._authenticated_snapshot = encrypted
        if not require_authenticated and self._key and (not encrypted or any(existing)):
            self._storage.migrate(*paths)

    def validate_migration_source(self) -> None:
        """Reject unauthenticated or unreconstructable migration sources."""
        if not self._authenticated_snapshot or self._faiss is None or self._index is None:
            raise AiVectorIndexError("An authenticated AI snapshot must be loaded first")
        if (
            type(self._index) is not self._faiss.IndexFlatIP
            or self._index.metric_type != self._faiss.METRIC_INNER_PRODUCT
        ):
            raise AiVectorIndexError("Only exact FAISS IndexFlatIP snapshots can be migrated")
        if len(self._id_map) != self._index.ntotal or any(
            str(index) not in self._id_map for index in range(self._index.ntotal)
        ):
            raise AiVectorIndexError("The AI snapshot has invalid vector identifiers")

    def iter_migration_vectors(self) -> Iterator[tuple[str, str, np.ndarray]]:
        """Yield losslessly reconstructed rows from an authenticated flat index."""
        self.validate_migration_source()
        assert self._index is not None
        seen: set[tuple[str, str]] = set()
        for index in range(self._index.ntotal):
            row = self._id_map[str(index)]
            identity = (row["path"], row["view_id"])
            if not identity[0] or not identity[1].strip() or identity in seen:
                raise AiVectorIndexError("The AI snapshot has invalid or duplicate image views")
            seen.add(identity)
            vector = np.empty(self._dimension, dtype=np.float32)
            self._index.reconstruct(index, vector)
            if not np.isfinite(vector).all() or not np.any(vector):
                raise AiVectorIndexError("The AI snapshot contains an invalid vector")
            norm = float(np.linalg.norm(vector.astype(np.float64)))
            if abs(norm - 1.0) > 1e-5:
                raise AiVectorIndexError("The AI snapshot contains a non-normalized vector")
            yield identity[0], identity[1], vector

    def reset(self) -> None:
        """Replace the loaded index with an empty index for the active model."""
        if self._faiss is None:
            raise RuntimeError("load() must be called before reset()")
        self._authenticated_snapshot = False
        self._index = self._faiss.IndexFlatIP(self._dimension)
        self._id_map = {}
        self._path_map = {}

    def rebuild(self) -> None:
        """Reconstruct the in-memory FAISS index from its persisted vectors."""
        if self._index is None:
            raise RuntimeError("load() must be called before rebuild()")
        self._replace_with_ids(list(range(self._index.ntotal)))

    def close(self) -> None:
        """Release the in-memory index and its path mappings."""
        self._faiss = None
        self._index = None
        self._authenticated_snapshot = False
        self._id_map = {}
        self._path_map = {}

    def save(self) -> None:
        """Persist the current index and id-map to disk."""
        if self._faiss is None or self._index is None:
            raise RuntimeError("load() must be called before save()")
        if self._key:
            serialized_index = self._faiss.serialize_index(self._index)
            index_bytes = memoryview(serialized_index)
            map_bytes = json.dumps(self._id_map, ensure_ascii=False).encode("utf-8")
            metadata_bytes = json.dumps(
                {
                    "schema_version": 2,
                    "model_fingerprint": self._profile.identifier,
                    "model_name": self._profile.model_name,
                    "pretrained": self._profile.pretrained,
                    "dimension": self._dimension,
                    "count": int(self._index.ntotal),
                    "image_count": len(self._path_map),
                    "view_strategy": "full-plus-four-corners-v1",
                    "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
                    "map_sha256": hashlib.sha256(map_bytes).hexdigest(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self._storage.save(index_bytes, map_bytes, metadata_bytes)
            paths = (self._index_path, self._id_map_path, self._metadata_path)
            if any(path.exists() for path in paths):
                self._storage.migrate(*paths)
            return
        if self._storage.path.exists():
            raise AiVectorAuthenticationError("Cannot replace an encrypted AI index without a password")
        parent = self._index_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        index_temp = self._temporary_path(parent, self._index_path.name)
        map_temp = self._temporary_path(parent, self._id_map_path.name)
        metadata_temp = self._temporary_path(parent, self._metadata_path.name)
        try:
            self._faiss.write_index(self._index, str(index_temp))
            map_temp.write_text(
            json.dumps(self._id_map, ensure_ascii=False, indent=None),
            encoding="utf-8",
            )
            metadata_temp.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "model_fingerprint": self._profile.identifier,
                        "model_name": self._profile.model_name,
                        "pretrained": self._profile.pretrained,
                        "dimension": self._dimension,
                        "count": int(self._index.ntotal),
                        "image_count": len(self._path_map),
                        "view_strategy": "full-plus-four-corners-v1",
                        "index_sha256": self._sha256(index_temp),
                        "map_sha256": self._sha256(map_temp),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            os.replace(index_temp, self._index_path)
            os.replace(map_temp, self._id_map_path)
            os.replace(metadata_temp, self._metadata_path)
        finally:
            index_temp.unlink(missing_ok=True)
            map_temp.unlink(missing_ok=True)
            metadata_temp.unlink(missing_ok=True)

    # ── Queries ───────────────────────────────────────────────────────────

    def get_indexed_paths(self) -> set[str]:
        """Return the set of image paths that already have a vector."""
        return set(self._path_map)

    def get_vector_count(self) -> int:
        if self._index is None:
            raise RuntimeError("load() must be called before get_vector_count()")
        return int(self._index.ntotal)

    def get_vector(self, image_path: str) -> "np.ndarray | None":
        """Return the full-view vector for *image_path*, or its first view."""
        if self._index is None:
            raise RuntimeError("load() must be called before get_vector()")
        row_ids = self._path_map.get(image_path)
        if not row_ids:
            return None
        row_id = next(
            (
                candidate
                for candidate in row_ids
                if self._id_map[str(candidate)]["view_id"] == "full"
            ),
            row_ids[0],
        )
        vector = np.empty(self._dimension, dtype=np.float32)
        self._index.reconstruct(row_id, vector)
        return vector

    def get_view_vectors(self, image_path: str) -> Dict[str, "np.ndarray"]:
        """Return every persisted view vector for *image_path*, keyed by view ID."""
        if self._index is None:
            raise RuntimeError("load() must be called before get_view_vectors()")
        vectors: Dict[str, np.ndarray] = {}
        for row_id in self._path_map.get(image_path, []):
            vector = np.empty(self._dimension, dtype=np.float32)
            self._index.reconstruct(row_id, vector)
            vectors[self._id_map[str(row_id)]["view_id"]] = vector
        return vectors

    def get_vectors(self, image_paths: List[str]) -> Dict[str, "np.ndarray | None"]:
        """Return vectors keyed by each requested path, preserving misses."""
        return {image_path: self.get_vector(image_path) for image_path in image_paths}

    # ── Mutations ─────────────────────────────────────────────────────────

    def add_images(
        self,
        embeddings: "np.ndarray",
        paths: List[str],
        *,
        view_ids: List[str] | None = None,
    ) -> None:
        """Append a batch of L2-normalised embeddings with their file paths.

        *embeddings* must be a float32 array of shape ``(N, dimension)``.
        *paths* must have length N.  Duplicate paths are not checked here —
        the caller (AiIndexerService) is responsible for skipping already-
        indexed images.
        """
        if self._index is None:
            raise RuntimeError("load() must be called before add_images()")
        n = len(paths)
        if n == 0:
            return
        row_view_ids = view_ids if view_ids is not None else ["full"] * n
        if len(row_view_ids) != n:
            raise ValueError("view_ids and paths must have the same length")
        if any(not view_id.strip() for view_id in row_view_ids):
            raise ValueError("view IDs must not be empty")
        rows = list(zip(paths, row_view_ids))
        if len(set(rows)) != len(rows):
            raise ValueError("path and view rows must be unique within a batch")
        if any(
            self._id_map[str(row_id)]["view_id"] == view_id
            for path, view_id in rows
            for row_id in self._path_map.get(path, [])
        ):
            raise ValueError("path and view row is already indexed")
        vecs = np.asarray(embeddings, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        if vecs.shape != (n, self._dimension):
            raise ValueError(
                f"embeddings must have shape ({n}, {self._dimension}), got {vecs.shape}"
            )
        start_id = self._index.ntotal
        self._authenticated_snapshot = False
        self._index.add(vecs)
        for i, (path, view_id) in enumerate(rows):
            row_id = start_id + i
            self._id_map[str(row_id)] = {"path": path, "view_id": view_id}
            self._path_map.setdefault(path, []).append(row_id)

    def upsert_images(
        self,
        embeddings: "np.ndarray",
        paths: List[str],
        *,
        view_ids: List[str] | None = None,
    ) -> None:
        """Atomically replace all vectors for the images represented in a batch."""
        if not paths:
            return
        if self._faiss is None or self._index is None:
            raise RuntimeError("load() must be called before upsert_images()")
        count = len(paths)
        row_view_ids = view_ids if view_ids is not None else ["full"] * count
        if len(row_view_ids) != count:
            raise ValueError("view_ids and paths must have the same length")
        if any(not view_id.strip() for view_id in row_view_ids):
            raise ValueError("view IDs must not be empty")
        rows = list(zip(paths, row_view_ids))
        if len(set(rows)) != len(rows):
            raise ValueError("path and view rows must be unique within a batch")
        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if vectors.shape != (count, self._dimension):
            raise ValueError(
                f"embeddings must have shape ({count}, {self._dimension}), "
                f"got {vectors.shape}"
            )

        replaced_paths = set(paths)
        keep_ids = [
            int(row_id)
            for row_id, row in self._id_map.items()
            if row["path"] not in replaced_paths
        ]
        retained = np.zeros((len(keep_ids), self._dimension), dtype=np.float32)
        retained_map: Dict[str, dict[str, str]] = {}
        for new_id, old_id in enumerate(keep_ids):
            self._index.reconstruct(old_id, retained[new_id])
            retained_map[str(new_id)] = self._id_map[str(old_id)]

        combined = np.concatenate((retained, vectors), axis=0)
        new_index = self._faiss.IndexFlatIP(self._dimension)
        new_index.add(combined)
        new_map = retained_map
        first_new_id = len(keep_ids)
        new_map.update(
            {
                str(first_new_id + row): {"path": path, "view_id": view_id}
                for row, (path, view_id) in enumerate(rows)
            }
        )
        self._authenticated_snapshot = False
        self._index = new_index
        self._id_map = new_map
        self._rebuild_path_map()

    def delete_images(self, image_paths: Set[str]) -> None:
        """Delete every view vector for the specified image paths."""
        if not image_paths:
            return
        if self._faiss is None or self._index is None:
            raise RuntimeError("load() must be called before delete_images()")
        keep_ids = [
            int(row_id)
            for row_id, row in self._id_map.items()
            if row["path"] not in image_paths
        ]
        if len(keep_ids) != self._index.ntotal:
            self._replace_with_ids(keep_ids)

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
            if not _is_inside(v["path"], folder)
        ]
        if len(keep_ids) == self._index.ntotal:
            return  # nothing to remove

        self._replace_with_ids(keep_ids)

    def _replace_with_ids(self, keep_ids: List[int]) -> None:
        if self._faiss is None or self._index is None:
            raise RuntimeError("load() must be called before rebuilding the index")

        self._authenticated_snapshot = False
        if not keep_ids:
            self._index = self._faiss.IndexFlatIP(self._dimension)
            self._id_map = {}
            self._path_map = {}
            return

        # Reconstruct surviving vectors by their sequential FAISS position.
        vecs = np.zeros((len(keep_ids), self._dimension), dtype=np.float32)
        for row, old_id in enumerate(keep_ids):
            self._index.reconstruct(old_id, vecs[row])

        new_index = self._faiss.IndexFlatIP(self._dimension)
        new_index.add(vecs)

        new_map: Dict[str, dict[str, str]] = {
            str(new_i): self._id_map[str(old_id)]
            for new_i, old_id in enumerate(keep_ids)
        }
        self._index = new_index
        self._id_map = new_map
        self._rebuild_path_map()

    def _rebuild_path_map(self) -> None:
        self._path_map = {}
        for row_id, row in self._id_map.items():
            self._path_map.setdefault(row["path"], []).append(int(row_id))

    # ── Search ────────────────────────────────────────────────────────────

    def search(
        self, query_vec: "np.ndarray", top_k: int = 800, threshold: float = 0.20
    ) -> List[tuple[str, float]]:
        """Return (path, score) pairs with cosine similarity >= *threshold*.

        Searches the top *top_k* candidates (capped at index size) then
        discards anything below *threshold*.  Results are sorted descending
        by score.

        *query_vec* must match the configured embedding dimension.
        It will be L2-normalised before searching.
        """
        return self._search_internal(query_vec, top_k=top_k, threshold=threshold)

    def search_filtered(
        self,
        query_vec: "np.ndarray",
        allowed_paths: Set[str],
        *,
        top_k: int | None = 800,
        threshold: float = 0.20,
    ) -> List[tuple[str, float]]:
        """Return ranked hits limited to *allowed_paths*.

        Filtering is applied before the final ``top_k`` cap so out-of-scope
        vectors cannot crowd out in-scope matches. Pass ``top_k=None`` to
        return every match above ``threshold``.
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
        top_k: int | None,
        threshold: float,
        allowed_paths: Set[str] | None = None,
    ) -> List[tuple[str, float]]:
        if self._index is None or self._index.ntotal == 0:
            return []
        vec = np.asarray(query_vec, dtype=np.float32).reshape(1, -1)
        if vec.shape[1] != self._dimension:
            raise ValueError(f"query vector must have dimension {self._dimension}")
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm

        def _collect_with_k(k: int) -> List[tuple[str, float]]:
            scores, ids = self._index.search(vec, k)
            pooled: Dict[str, float] = {}
            for score, idx in zip(scores[0], ids[0]):
                if idx < 0:
                    continue
                if float(score) < threshold:
                    break  # scores are descending — remaining rows are below threshold
                row = self._id_map.get(str(int(idx)))
                if row is None:
                    continue
                path = row["path"]
                if allowed_paths is not None and path not in allowed_paths:
                    continue
                pooled[path] = max(pooled.get(path, float("-inf")), float(score))
            results = sorted(pooled.items(), key=lambda item: (-item[1], item[0]))
            return results if top_k is None else results[:top_k]

        # Exact mode: caller wants all matches above threshold.
        if top_k is None:
            return _collect_with_k(self._index.ntotal)

        # Grow the row candidate pool until it contains enough unique paths.
        # Multiple high-scoring views for one image must not crowd out others.
        k = min(max(top_k * 5, 256), self._index.ntotal)
        while True:
            results = _collect_with_k(k)
            if len(results) >= top_k or k >= self._index.ntotal:
                return results
            k = min(k * 2, self._index.ntotal)

    @staticmethod
    def _temporary_path(parent: Path, target_name: str) -> Path:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{target_name}.", suffix=".tmp", dir=parent
        )
        os.close(descriptor)
        return Path(name)

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_inside(image_path: str, folder: Path) -> bool:
    """Return True when *image_path* is the folder itself or a descendant."""
    try:
        return Path(image_path).is_relative_to(folder)
    except ValueError:
        return False
