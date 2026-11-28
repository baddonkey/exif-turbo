"""Persist CLIP vectors in the encrypted metadata database using Vec1."""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import numpy as np
import sqlcipher3

from ..config import database_data_dir
from ..models.ai_model_profile import DEFAULT_AI_MODEL_PROFILE, AiModelProfile
from ._connection import open_encrypted_connection
from .ai_vector_backend import AiVectorIndexError

_VEC1_VERSION = "0.8"
_SCHEMA_VERSION = 1
_MIGRATION_NAME = "ai-vec1-schema-v1"
_VIEW_STRATEGY = "full-plus-four-corners-v1"
_INDEX_PARAMETERS = {"distance": "cos", "index": "none"}


def _preprocessing_description() -> str:
    return (
        "open_clip.create_model_and_transforms:eval-transform/"
        f"open-clip-torch-{version('open-clip-torch')}"
    )


class AiVec1IndexError(AiVectorIndexError):
    """The Vec1 tables or model metadata are missing or incompatible."""


class AiVec1TrainingCanceled(Exception):
    """A Vec1 training transaction was canceled."""


class AiVec1Repository:
    """Store image vectors and their image/view mapping in SQLCipher."""

    def __init__(
        self,
        db_path: Path,
        key: str,
        extension_path: Path,
        *,
        profile: AiModelProfile = DEFAULT_AI_MODEL_PROFILE,
    ) -> None:
        self._db_path = db_path
        self._key = key
        self._extension_path = extension_path
        self._profile = profile
        self._conn: sqlcipher3.Connection | None = None

    @property
    def profile(self) -> AiModelProfile:
        return self._profile

    @property
    def dimension(self) -> int:
        return self._profile.dimension

    @property
    def storage_dir(self) -> Path:
        return database_data_dir(self._db_path)

    def load(self) -> None:
        """Open the SQLCipher database, register Vec1, and validate its schema."""
        if self._conn is not None:
            return
        if sys.byteorder != "little":
            raise AiVec1IndexError("Vec1 storage requires a little-endian host")
        if not self._extension_path.is_file():
            raise FileNotFoundError("The Vec1 extension binary is unavailable")

        conn = open_encrypted_connection(self._db_path, self._key)
        try:
            self._load_extension(conn)
            vec1_info = str(conn.execute("SELECT vec1_info()").fetchone()[0])
            vec1_version = self._version_from_info(vec1_info)
            if vec1_version != _VEC1_VERSION:
                raise AiVec1IndexError(
                    f"Vec1 version {_VEC1_VERSION} is required; found {vec1_version}"
                )
            self._initialize_schema(conn, vec1_version)
            with conn:
                self._drain_pending_deletes(conn)
        except BaseException:
            conn.close()
            raise
        self._conn = conn

    def _load_extension(self, conn: sqlcipher3.Connection) -> None:
        conn.enable_load_extension(True)
        try:
            conn.load_extension(str(self._extension_path))
        finally:
            conn.enable_load_extension(False)

    @staticmethod
    def _version_from_info(info: str) -> str:
        parts = info.split()
        if len(parts) < 2 or parts[0] != "version":
            raise AiVec1IndexError("Vec1 returned unrecognized version information")
        return parts[1]

    def _initialize_schema(
        self,
        conn: sqlcipher3.Connection,
        vec1_version: str,
    ) -> None:
        conn.execute("BEGIN IMMEDIATE")
        images_exist = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images'"
        ).fetchone()
        if images_exist is None:
            raise AiVec1IndexError(
                "The metadata image schema must be initialized before Vec1"
            )

        schema_objects = {
            "ai_vector_index_metadata",
            "image_embedding_map",
            "ai_vector_pending_deletes",
            "image_vectors",
        }
        existing_objects = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('ai_vector_index_metadata', 'image_embedding_map', "
                "'ai_vector_pending_deletes', 'image_vectors')"
            ).fetchall()
        }
        if existing_objects and existing_objects != schema_objects:
            raise AiVec1IndexError("The Vec1 schema is incomplete")

        with conn:
            if not existing_objects:
                conn.execute(
                    """
                    CREATE TABLE ai_vector_index_metadata (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        schema_version INTEGER NOT NULL,
                        model_generation INTEGER NOT NULL,
                        model_identifier TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        pretrained TEXT NOT NULL,
                        dimension INTEGER NOT NULL CHECK (dimension > 0),
                        view_strategy TEXT NOT NULL,
                        preprocessing TEXT NOT NULL,
                        normalization TEXT NOT NULL,
                        distance_metric TEXT NOT NULL,
                        byte_order TEXT NOT NULL,
                        vec1_version TEXT NOT NULL,
                        index_parameters TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE image_embedding_map (
                        vector_id INTEGER PRIMARY KEY,
                        image_id INTEGER NOT NULL
                            REFERENCES images(id) ON DELETE CASCADE,
                        view_key TEXT NOT NULL CHECK (trim(view_key) <> ''),
                        UNIQUE (image_id, view_key)
                    )
                    """
                )
                conn.execute(
                    "CREATE TABLE ai_vector_pending_deletes "
                    "(vector_id INTEGER PRIMARY KEY)"
                )
                conn.execute(
                    "CREATE VIRTUAL TABLE image_vectors USING vec1(embedding)"
                )
                conn.execute(
                    "INSERT INTO image_vectors(cmd, arg) VALUES('rebuild', ?)",
                    (json.dumps(_INDEX_PARAMETERS, sort_keys=True),),
                )
                conn.execute(
                    """
                    CREATE TRIGGER image_embedding_map_pending_delete
                    AFTER DELETE ON image_embedding_map
                    BEGIN
                        INSERT OR IGNORE INTO ai_vector_pending_deletes(vector_id)
                        VALUES (old.vector_id);
                    END
                    """
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS completed_migrations "
                    "(name TEXT PRIMARY KEY, completed_at TEXT NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP)"
                )
                conn.execute(
                    "INSERT OR IGNORE INTO completed_migrations(name) VALUES (?)",
                    (_MIGRATION_NAME,),
                )
                self._insert_metadata(conn, vec1_version)
            else:
                trigger_exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='trigger' "
                    "AND name='image_embedding_map_pending_delete'"
                ).fetchone()
                if trigger_exists is None:
                    raise AiVec1IndexError("The Vec1 deletion trigger is missing")
                self._validate_metadata(conn, vec1_version)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS ai_vector_backend ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
                "active TEXT NOT NULL CHECK(active = 'vec1'), "
                "revision INTEGER NOT NULL)"
            )
            conn.execute(
                "INSERT INTO ai_vector_backend VALUES(1, 'vec1', 0) "
                "ON CONFLICT(singleton) DO NOTHING"
            )
            state = conn.execute(
                "SELECT active FROM ai_vector_backend WHERE singleton = 1"
            ).fetchone()
            if state != ("vec1",):
                raise AiVec1IndexError("The AI index needs a full rescan")
            for event in ("INSERT", "UPDATE", "DELETE"):
                conn.execute(
                    f"CREATE TRIGGER IF NOT EXISTS ai_vector_backend_revision_{event.lower()} "
                    f"AFTER {event} ON image_embedding_map BEGIN "
                    "UPDATE ai_vector_backend SET revision = revision + 1 "
                    "WHERE singleton = 1 AND active = 'vec1'; END"
                )

    def _metadata_values(self, vec1_version: str) -> tuple[object, ...]:
        return (
            _SCHEMA_VERSION,
            1,
            self._profile.identifier,
            self._profile.model_name,
            self._profile.pretrained,
            self._profile.dimension,
            _VIEW_STRATEGY,
            _preprocessing_description(),
            "l2-float32",
            "cos",
            sys.byteorder,
            vec1_version,
            json.dumps(_INDEX_PARAMETERS, sort_keys=True, separators=(",", ":")),
        )

    def _insert_metadata(
        self,
        conn: sqlcipher3.Connection,
        vec1_version: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO ai_vector_index_metadata(
                singleton, schema_version, model_generation, model_identifier,
                model_name, pretrained, dimension, view_strategy, preprocessing,
                normalization, distance_metric, byte_order, vec1_version,
                index_parameters
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._metadata_values(vec1_version),
        )

    def _validate_metadata(
        self,
        conn: sqlcipher3.Connection,
        vec1_version: str,
    ) -> None:
        row = conn.execute(
            """
            SELECT schema_version, model_generation, model_identifier,
                   model_name, pretrained, dimension, view_strategy,
                   preprocessing, normalization, distance_metric, byte_order,
                   vec1_version, index_parameters
            FROM ai_vector_index_metadata WHERE singleton = 1
            """
        ).fetchone()
        expected = self._metadata_values(vec1_version)
        if row is None or tuple(row[:-1]) != expected[:-1]:
            raise AiVec1IndexError(
                "The Vec1 index metadata is incompatible; rebuild the AI index"
            )
        try:
            parameters = json.loads(row[-1])
        except (TypeError, ValueError) as exc:
            raise AiVec1IndexError("The Vec1 index parameters are invalid") from exc
        if parameters != _INDEX_PARAMETERS and not (
            isinstance(parameters, dict)
            and parameters.get("index") == "trained"
            and parameters.get("distance") == "cos"
            and parameters.get("quantizer") == "none"
            and parameters.get("codesize") == 0
            and type(parameters.get("nbucket")) is int
            and 2 <= parameters["nbucket"] <= 256
            and set(parameters) == {"index", "distance", "quantizer", "codesize", "nbucket"}
        ):
            raise AiVec1IndexError("The Vec1 index parameters are incompatible")

    @staticmethod
    def _drain_pending_deletes(conn: sqlcipher3.Connection) -> None:
        pending = conn.execute(
            "SELECT 1 FROM ai_vector_pending_deletes LIMIT 1"
        ).fetchone()
        if pending is None:
            return
        conn.execute(
            "DELETE FROM image_vectors WHERE rowid IN "
            "(SELECT vector_id FROM ai_vector_pending_deletes)"
        )
        conn.execute("DELETE FROM ai_vector_pending_deletes")

    def _connection(self) -> sqlcipher3.Connection:
        if self._conn is None:
            raise RuntimeError("load() must be called before using the repository")
        return self._conn

    @staticmethod
    def _validated_vectors(
        embeddings: np.ndarray,
        count: int,
        dimension: int,
    ) -> np.ndarray:
        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if vectors.shape != (count, dimension):
            raise ValueError(
                f"embeddings must have shape ({count}, {dimension}), got {vectors.shape}"
            )
        if not np.isfinite(vectors).all():
            raise ValueError("embeddings must contain only finite values")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if np.any(norms == 0) or not np.isfinite(norms).all():
            raise ValueError("embeddings must have non-zero finite norms")
        return np.ascontiguousarray(vectors / norms, dtype=np.float32)

    def add_images(
        self,
        embeddings: np.ndarray,
        paths: list[str],
        *,
        view_ids: list[str] | None = None,
    ) -> None:
        """Append normalized vectors for indexed images and their view keys."""
        if not paths:
            return
        conn = self._connection()
        count = len(paths)
        row_view_ids = view_ids if view_ids is not None else ["full"] * count
        if len(row_view_ids) != count:
            raise ValueError("view_ids and paths must have the same length")
        if any(not view_id.strip() for view_id in row_view_ids):
            raise ValueError("view IDs must not be empty")
        rows = list(zip(paths, row_view_ids))
        if len(set(rows)) != len(rows):
            raise ValueError("path and view rows must be unique within a batch")
        vectors = self._validated_vectors(embeddings, count, self.dimension)

        with conn:
            self._drain_pending_deletes(conn)
            image_ids: dict[str, int] = {}
            for path in dict.fromkeys(paths):
                row = conn.execute(
                    "SELECT id FROM images WHERE path = ?", (path,)
                ).fetchone()
                if row is None:
                    raise ValueError(
                        "every vector path must refer to an indexed image"
                    )
                image_ids[path] = int(row[0])

            for path, view_id in rows:
                existing = conn.execute(
                    "SELECT 1 FROM image_embedding_map "
                    "WHERE image_id = ? AND view_key = ?",
                    (image_ids[path], view_id),
                ).fetchone()
                if existing is not None:
                    raise ValueError("path and view row is already indexed")

            for (path, view_id), vector in zip(rows, vectors, strict=True):
                cursor = conn.execute(
                    "INSERT INTO image_embedding_map(image_id, view_key) "
                    "VALUES (?, ?)",
                    (image_ids[path], view_id),
                )
                conn.execute(
                    "INSERT INTO image_vectors(rowid, embedding) VALUES (?, ?)",
                    (cursor.lastrowid, vector.tobytes()),
                )

    def upsert_images(
        self,
        embeddings: np.ndarray,
        paths: list[str],
        *,
        view_ids: list[str] | None = None,
    ) -> None:
        """Replace all persisted views for the images represented in a batch."""
        if not paths:
            return
        conn = self._connection()
        count = len(paths)
        row_view_ids = view_ids if view_ids is not None else ["full"] * count
        if len(row_view_ids) != count:
            raise ValueError("view_ids and paths must have the same length")
        if any(not view_id.strip() for view_id in row_view_ids):
            raise ValueError("view IDs must not be empty")
        rows = list(zip(paths, row_view_ids))
        if len(set(rows)) != len(rows):
            raise ValueError("path and view rows must be unique within a batch")
        vectors = self._validated_vectors(embeddings, count, self.dimension)

        with conn:
            self._drain_pending_deletes(conn)
            image_ids: dict[str, int] = {}
            for path in dict.fromkeys(paths):
                row = conn.execute(
                    "SELECT id FROM images WHERE path = ?", (path,)
                ).fetchone()
                if row is None:
                    raise ValueError(
                        "every vector path must refer to an indexed image"
                    )
                image_ids[path] = int(row[0])

            conn.executemany(
                "DELETE FROM image_embedding_map WHERE image_id = ?",
                ((image_id,) for image_id in image_ids.values()),
            )
            self._drain_pending_deletes(conn)
            for (path, view_id), vector in zip(rows, vectors, strict=True):
                cursor = conn.execute(
                    "INSERT INTO image_embedding_map(image_id, view_key) "
                    "VALUES (?, ?)",
                    (image_ids[path], view_id),
                )
                conn.execute(
                    "INSERT INTO image_vectors(rowid, embedding) VALUES (?, ?)",
                    (cursor.lastrowid, vector.tobytes()),
                )

    def get_indexed_paths(self) -> set[str]:
        conn = self._connection()
        return {
            str(row[0])
            for row in conn.execute(
                """
                SELECT DISTINCT images.path
                FROM image_embedding_map
                JOIN images ON images.id = image_embedding_map.image_id
                ORDER BY images.path
                """
            ).fetchall()
        }

    def get_vector_count(self) -> int:
        conn = self._connection()
        return int(conn.execute("SELECT count(*) FROM image_embedding_map").fetchone()[0])

    def get_vector(self, image_path: str) -> np.ndarray | None:
        views = self.get_view_vectors(image_path)
        if not views:
            return None
        return views.get("full", next(iter(views.values())))

    def get_view_vectors(self, image_path: str) -> dict[str, np.ndarray]:
        conn = self._connection()
        rows = conn.execute(
            """
            SELECT image_embedding_map.view_key, image_vectors.embedding
            FROM image_embedding_map
            JOIN images ON images.id = image_embedding_map.image_id
            JOIN image_vectors
                ON image_vectors.rowid = image_embedding_map.vector_id
            WHERE images.path = ?
            ORDER BY image_embedding_map.vector_id
            """,
            (image_path,),
        ).fetchall()
        vectors: dict[str, np.ndarray] = {}
        for view_id, embedding in rows:
            vector = np.frombuffer(embedding, dtype=np.float32)
            if vector.size != self.dimension:
                raise AiVec1IndexError("A stored vector has an incompatible dimension")
            vectors[str(view_id)] = vector.copy()
        return vectors

    def get_vectors(self, image_paths: list[str]) -> dict[str, np.ndarray | None]:
        return {image_path: self.get_vector(image_path) for image_path in image_paths}


    def delete_images(self, image_paths: set[str]) -> None:
        if not image_paths:
            return
        conn = self._connection()
        with conn:
            self._materialize_paths(conn, image_paths)
            conn.execute(
                "DELETE FROM image_embedding_map WHERE image_id IN "
                "(SELECT images.id FROM images "
                "JOIN _ai_vec1_scope_paths ON _ai_vec1_scope_paths.path=images.path)"
            )
            self._drain_pending_deletes(conn)

    def remove_folder(self, folder_path: str) -> None:
        folder = os.path.normpath(folder_path)
        prefix = folder if folder.endswith(os.sep) else folder + os.sep
        path_expression = "lower(path)" if os.name == "nt" else "path"
        folder_expression = "lower(?)" if os.name == "nt" else "?"
        conn = self._connection()
        with conn:
            conn.execute(
                f"""
                DELETE FROM image_embedding_map
                WHERE image_id IN (
                    SELECT id FROM images
                    WHERE {path_expression} = {folder_expression}
                       OR instr({path_expression}, {folder_expression}) = 1
                )
                """,
                (folder, prefix),
            )
            self._drain_pending_deletes(conn)

    def reset(self) -> None:
        conn = self._connection()
        with conn:
            conn.execute("DELETE FROM image_embedding_map")
            self._drain_pending_deletes(conn)

    def rebuild(self) -> None:
        conn = self._connection()
        with conn:
            self._drain_pending_deletes(conn)
            conn.execute(
                "INSERT INTO image_vectors(cmd, arg) VALUES('rebuild', ?)",
                (json.dumps(_INDEX_PARAMETERS, sort_keys=True),),
            )
            conn.execute(
                "UPDATE ai_vector_index_metadata SET index_parameters = ? WHERE singleton = 1",
                (json.dumps(_INDEX_PARAMETERS, sort_keys=True, separators=(",", ":")),),
            )

    def train_index(
        self,
        *,
        cancel_check: Callable[[], bool] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        """Train a transactional cosine index without changing exact search."""
        conn = self._connection()

        def check_canceled() -> None:
            if cancel_check is not None and cancel_check():
                raise AiVec1TrainingCanceled("Vec1 index training canceled")

        def progress(stage: str) -> None:
            if on_progress is not None:
                on_progress(stage)
            check_canceled()

        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                self._drain_pending_deletes(conn)
                count = int(conn.execute("SELECT count(*) FROM image_embedding_map").fetchone()[0])
                if count < 128:
                    raise ValueError("Vec1 training requires at least 128 vectors")
                nbucket = min(256, max(2, count // 64))
                parameters = {
                    "nbucket": nbucket,
                    "codesize": 0,
                    "distance": "cos",
                    "quantizer": "none",
                }
                progress("training")
                conn.set_progress_handler(
                    lambda: int(cancel_check is not None and cancel_check()), 1000
                )
                model = conn.execute(
                    "SELECT vec1_train(embedding, ?) FROM image_vectors",
                    (json.dumps(parameters, sort_keys=True),),
                ).fetchone()[0]
                check_canceled()
                progress("rebuilding")
                conn.execute(
                    "INSERT INTO image_vectors(cmd, arg) VALUES('rebuild', ?)", (model,)
                )
                progress("rebuilt")
                metadata = {"index": "trained", **parameters}
                conn.execute(
                    "UPDATE ai_vector_index_metadata SET index_parameters = ? WHERE singleton = 1",
                    (json.dumps(metadata, sort_keys=True, separators=(",", ":")),),
                )
                check_canceled()
        except sqlcipher3.OperationalError as exc:
            if cancel_check is not None and cancel_check() and "interrupt" in str(exc).lower():
                raise AiVec1TrainingCanceled("Vec1 index training canceled") from exc
            raise
        finally:
            conn.set_progress_handler(None, 0)

    def search(
        self,
        query_vec: np.ndarray,
        top_k: int | None = 800,
        threshold: float = 0.20,
    ) -> list[tuple[str, float]]:
        return self._search_internal(
            query_vec,
            allowed_paths=None,
            top_k=top_k,
            threshold=threshold,
        )

    def search_filtered(
        self,
        query_vec: np.ndarray,
        allowed_paths: set[str],
        *,
        top_k: int | None = 800,
        threshold: float = 0.20,
    ) -> list[tuple[str, float]]:
        if not allowed_paths:
            return []
        return self._search_internal(
            query_vec,
            allowed_paths=allowed_paths,
            top_k=top_k,
            threshold=threshold,
        )

    def search_approximate(
        self,
        query_vec: np.ndarray,
        *,
        top_k: int,
        threshold: float = 0.20,
        nprobe: int,
    ) -> list[tuple[str, float]]:
        """Experimental global ANN search with exact image-level reranking."""
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not np.isfinite(threshold) or not -1.0 <= threshold <= 1.0:
            raise ValueError("threshold must be a finite cosine similarity")
        conn = self._connection()
        parameters = json.loads(conn.execute(
            "SELECT index_parameters FROM ai_vector_index_metadata WHERE singleton = 1"
        ).fetchone()[0])
        if parameters.get("index") != "trained":
            raise AiVec1IndexError("The Vec1 index has not been trained")
        if type(nprobe) is not int or not 1 <= nprobe <= parameters["nbucket"]:
            raise ValueError("nprobe must be between 1 and the number of buckets")
        query = self._validated_vectors(query_vec, 1, self.dimension)[0].tobytes()
        with conn:
            self._drain_pending_deletes(conn)
            count = self.get_vector_count()
            if count == 0:
                return []
            candidates = min(count, max(64, top_k * 5))
            while True:
                options = json.dumps({"K": candidates, "nprobe": nprobe})
                rows = conn.execute(
                    "SELECT images.path, vec1_cos_distance(v.embedding, ?) "
                    "FROM image_vectors(?, ?) AS v "
                    "JOIN image_embedding_map AS m ON m.vector_id = v.rowid "
                    "JOIN images ON images.id = m.image_id",
                    (query, query, options),
                )
                pooled: dict[str, float] = {}
                for path, distance in rows:
                    score = 1.0 - float(distance)
                    if score >= threshold and (path not in pooled or score > pooled[path]):
                        pooled[str(path)] = score
                ordered = sorted(pooled.items(), key=lambda item: (-item[1], item[0]))
                if len(ordered) >= top_k or candidates == count:
                    return ordered[:top_k]
                candidates = min(count, candidates * 2)

    def _search_internal(
        self,
        query_vec: np.ndarray,
        *,
        allowed_paths: set[str] | None,
        top_k: int | None,
        threshold: float,
    ) -> list[tuple[str, float]]:
        if top_k is not None and top_k <= 0:
            raise ValueError("top_k must be positive or None")
        if not np.isfinite(threshold) or not -1.0 <= threshold <= 1.0:
            raise ValueError("threshold must be a finite cosine similarity")
        query = self._validated_vectors(query_vec, 1, self.dimension)[0]
        conn = self._connection()

        with conn:
            self._drain_pending_deletes(conn)
            source = """
                FROM image_vectors
                CROSS JOIN image_embedding_map
                    ON image_embedding_map.vector_id = image_vectors.rowid
                CROSS JOIN images ON images.id = image_embedding_map.image_id
            """
            if allowed_paths is not None:
                self._materialize_paths(conn, allowed_paths)
                indexed_images = int(conn.execute(
                    "SELECT count(*) FROM ("
                    "SELECT DISTINCT image_id FROM image_embedding_map)"
                ).fetchone()[0])
                if len(allowed_paths) * 2 < indexed_images:
                    source = """
                        FROM _ai_vec1_scope_paths AS scope
                        CROSS JOIN images ON images.path = scope.path
                        CROSS JOIN image_embedding_map
                            ON image_embedding_map.image_id = images.id
                        CROSS JOIN image_vectors
                            ON image_vectors.rowid = image_embedding_map.vector_id
                    """
                else:
                    source += """
                        JOIN _ai_vec1_scope_paths AS scope ON scope.path = images.path
                    """

            query_sql = f"""
                WITH image_scores AS (
                    SELECT images.id AS image_id, images.path,
                           MIN(vec1_cos_distance(image_vectors.embedding, ?))
                               AS distance
                    {source}
                    GROUP BY images.id, images.path
                )
                SELECT path, 1.0 - distance AS score
                FROM image_scores
                WHERE distance <= ?
                ORDER BY distance, path
            """
            parameters: tuple[object, ...] = (
                query.tobytes(),
                1.0 - threshold,
            )
            if top_k is not None:
                query_sql += " LIMIT ?"
                parameters += (top_k,)
            return [
                (str(path), float(score))
                for path, score in conn.execute(query_sql, parameters).fetchall()
            ]

    @staticmethod
    def _materialize_paths(
        conn: sqlcipher3.Connection,
        paths: set[str],
    ) -> None:
        conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _ai_vec1_scope_paths "
            "(path TEXT PRIMARY KEY)"
        )
        conn.execute("DELETE FROM _ai_vec1_scope_paths")
        conn.executemany(
            "INSERT OR IGNORE INTO _ai_vec1_scope_paths(path) VALUES (?)",
            ((path,) for path in paths),
        )

    def save(self) -> None:
        self._connection().commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
