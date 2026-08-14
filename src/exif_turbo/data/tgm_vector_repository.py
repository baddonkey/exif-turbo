from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from ..models.tgm_vector import TgmVectorFingerprint, TgmVectorHit


class TgmVectorIndexError(RuntimeError):
    """The persisted TGM term index is incomplete, corrupt, or inconsistent."""


class TgmVectorRepository:
    def __init__(
        self,
        index_path: Path,
        concept_map_path: Path,
        metadata_path: Path,
        *,
        dimension: int = 512,
    ) -> None:
        self._index_path = index_path
        self._concept_map_path = concept_map_path
        self._metadata_path = metadata_path
        self._dimension = dimension
        self._faiss = None
        self._index = None
        self._concept_ids: tuple[str, ...] = ()
        self._fingerprint: TgmVectorFingerprint | None = None

    @property
    def fingerprint(self) -> TgmVectorFingerprint | None:
        return self._fingerprint

    @property
    def count(self) -> int:
        return 0 if self._index is None else int(self._index.ntotal)

    def load(self) -> None:
        import faiss  # noqa: PLC0415

        self._faiss = faiss
        paths = (self._index_path, self._concept_map_path, self._metadata_path)
        existing = tuple(path.exists() for path in paths)
        if not any(existing):
            self._index = faiss.IndexFlatIP(self._dimension)
            self._concept_ids = ()
            self._fingerprint = None
            return
        if not all(existing):
            raise TgmVectorIndexError(
                "TGM vector index is incomplete; rebuild it from the active TGM snapshot"
            )

        try:
            metadata = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            concept_ids_raw = json.loads(
                self._concept_map_path.read_text(encoding="utf-8")
            )
            index = faiss.read_index(str(self._index_path))
            if not isinstance(metadata, dict) or not isinstance(concept_ids_raw, list):
                raise ValueError("metadata or concept map has the wrong shape")
            concept_ids = tuple(str(value) for value in concept_ids_raw)
            fingerprint = TgmVectorFingerprint.from_dict(metadata["fingerprint"])
            expected_count = int(metadata["count"])
            if fingerprint.dimension != self._dimension or index.d != self._dimension:
                raise ValueError(
                    f"expected {self._dimension}-dimensional vectors, found {index.d}"
                )
            if index.ntotal != len(concept_ids) or index.ntotal != expected_count:
                raise ValueError("FAISS count, concept map, and metadata count differ")
            if len(set(concept_ids)) != len(concept_ids):
                raise ValueError("concept map contains duplicate IDs")
            if self._sha256(self._index_path) != str(metadata["index_sha256"]):
                raise ValueError("FAISS index checksum does not match metadata")
            if self._sha256(self._concept_map_path) != str(metadata["map_sha256"]):
                raise ValueError("concept map checksum does not match metadata")
        except Exception as exc:  # noqa: BLE001
            raise TgmVectorIndexError(
                f"TGM vector index is corrupt or mismatched; rebuild required: {exc}"
            ) from exc

        self._index = index
        self._concept_ids = concept_ids
        self._fingerprint = fingerprint

    def replace_index(
        self,
        vectors: np.ndarray,
        concept_ids: list[str] | tuple[str, ...],
        fingerprint: TgmVectorFingerprint,
    ) -> None:
        if self._faiss is None:
            raise RuntimeError("load() must be called before replace_index()")
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self._dimension:
            raise ValueError(
                f"vectors must have shape (N, {self._dimension}), got {matrix.shape}"
            )
        if matrix.shape[0] != len(concept_ids):
            raise ValueError("vector and concept counts differ")
        if fingerprint.dimension != self._dimension:
            raise ValueError("fingerprint dimension does not match repository")
        if len(set(concept_ids)) != len(concept_ids):
            raise ValueError("concept IDs must be unique")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("zero-length TGM vectors cannot be indexed")
        matrix = np.ascontiguousarray(matrix / norms, dtype=np.float32)
        new_index = self._faiss.IndexFlatIP(self._dimension)
        new_index.add(matrix)

        parent = self._index_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        temp_paths: list[Path] = []
        try:
            index_temp = self._temporary_path(parent, self._index_path.name)
            map_temp = self._temporary_path(parent, self._concept_map_path.name)
            metadata_temp = self._temporary_path(parent, self._metadata_path.name)
            temp_paths.extend((index_temp, map_temp, metadata_temp))
            self._faiss.write_index(new_index, str(index_temp))
            map_temp.write_text(
                json.dumps(list(concept_ids), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            metadata_temp.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "count": len(concept_ids),
                        "fingerprint": fingerprint.to_dict(),
                        "index_sha256": self._sha256(index_temp),
                        "map_sha256": self._sha256(map_temp),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            os.replace(index_temp, self._index_path)
            os.replace(map_temp, self._concept_map_path)
            os.replace(metadata_temp, self._metadata_path)
        finally:
            for temp_path in temp_paths:
                temp_path.unlink(missing_ok=True)

        self._index = new_index
        self._concept_ids = tuple(concept_ids)
        self._fingerprint = fingerprint

    def search(
        self,
        image_vector: np.ndarray,
        *,
        top_k: int,
        threshold: float,
    ) -> tuple[TgmVectorHit, ...]:
        if self._index is None:
            raise RuntimeError("load() must be called before search()")
        if top_k <= 0 or self._index.ntotal == 0:
            return ()
        vector = np.asarray(image_vector, dtype=np.float32).reshape(1, -1)
        if vector.shape[1] != self._dimension:
            raise ValueError(f"image vector must have dimension {self._dimension}")
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            raise ValueError("image vector must not be zero-length")
        scores, ids = self._index.search(vector / norm, min(top_k, self._index.ntotal))
        return tuple(
            TgmVectorHit(
                concept_id=self._concept_ids[int(row_id)],
                score=float(score),
                rank=rank,
            )
            for rank, (score, row_id) in enumerate(zip(scores[0], ids[0]), start=1)
            if row_id >= 0 and float(score) >= threshold
        )

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