"""Benchmark encrypted Vec1 search using generated images and vectors only."""
from __future__ import annotations

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

import numpy as np

from exif_turbo.data.ai_vec1_repository import AiVec1Repository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.utils.process_memory import current_rss_bytes

_VIEWS: tuple[str, ...] = ("full", "top_left", "top_right", "bottom_left", "bottom_right")


def run_benchmark(
    extension: Path, *, image_count: int, batch_size: int, repeats: int
) -> dict[str, object]:
    if image_count <= 0 or batch_size <= 0 or repeats <= 0:
        raise ValueError("image count, batch size, and repeats must be positive")
    if not extension.is_file():
        raise FileNotFoundError("Vec1 extension is unavailable")
    rng = np.random.default_rng(20261127)
    with tempfile.TemporaryDirectory(prefix="exif-turbo-vec1-benchmark-") as work:
        root = Path(work)
        db_path = root / "index.db"
        key = "synthetic-benchmark-password"
        image_paths = [str(root / f"synthetic-{index:08}.jpg") for index in range(image_count)]
        metadata = ImageIndexRepository(db_path, key=key)
        try:
            for start in range(0, image_count, batch_size):
                metadata.upsert_images_batch([
                    (path, Path(path).name, 1.0, 100, {}, "", None, None)
                    for path in image_paths[start:start + batch_size]
                ])
        finally:
            metadata.close()
        vectors = AiVec1Repository(db_path, key, extension)
        try:
            vectors.load()
            started = time.perf_counter()
            for start in range(0, image_count, batch_size):
                paths = image_paths[start:start + batch_size]
                embeddings = rng.standard_normal((len(paths) * len(_VIEWS), 512)).astype(np.float32)
                vectors.add_images(
                    embeddings,
                    [path for path in paths for _ in _VIEWS],
                    view_ids=list(_VIEWS) * len(paths),
                )
            indexing_seconds = time.perf_counter() - started
            query = rng.standard_normal(512).astype(np.float32)
            scope = set(image_paths)
            vectors.search_filtered(query, scope, top_k=800, threshold=-1)
            durations = []
            count = 0
            for _ in range(repeats):
                started = time.perf_counter()
                results = vectors.search_filtered(query, scope, top_k=800, threshold=-1)
                durations.append((time.perf_counter() - started) * 1000)
                count = len(results)
            vectors.save()
        finally:
            vectors.close()
        disk_bytes = sum(
            path.stat().st_size
            for path in root.iterdir()
            if path.is_file() and (path.name == "index.db" or path.name.startswith("index.db-"))
        )
        return {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "seed": 20261127,
            "images": image_count,
            "vectors": image_count * len(_VIEWS),
            "dimensions": 512,
            "encrypted": True,
            "repeats": repeats,
            "results": count,
            "indexing_seconds": indexing_seconds,
            "query_p50_ms": float(np.percentile(durations, 50)),
            "query_p95_ms": float(np.percentile(durations, 95)),
            "database_bytes": disk_bytes,
            "process_rss_bytes": current_rss_bytes(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--images", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(
        args.extension, image_count=args.images, batch_size=args.batch_size, repeats=args.repeats,
    ), indent=2))


if __name__ == "__main__":
    main()
