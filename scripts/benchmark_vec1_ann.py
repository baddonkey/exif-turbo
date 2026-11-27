"""Compare synthetic Vec1 ANN candidates against exact NumPy neighbors."""
from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np
import sqlcipher3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", type=Path, required=True)
    args = parser.parse_args()
    if not args.extension.is_file():
        parser.error("--extension must name a Vec1 library")

    rng = np.random.default_rng(20261127)
    vectors = rng.standard_normal((1600, 512)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    queries = rng.standard_normal((8, 512)).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)

    conn = sqlcipher3.connect(":memory:")
    try:
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.enable_load_extension(True)
        try:
            conn.load_extension(str(args.extension.resolve()))
        finally:
            conn.enable_load_extension(False)
        vec1_info = conn.execute("SELECT vec1_info()").fetchone()[0]
        conn.execute("CREATE VIRTUAL TABLE vectors USING vec1(embedding)")
        conn.executemany(
            "INSERT INTO vectors(rowid, embedding) VALUES (?, ?)",
            ((i + 1, vector.tobytes()) for i, vector in enumerate(vectors)),
        )
        conn.commit()
        parameters = {"nbucket": 16, "codesize": 0, "distance": "cos", "quantizer": "none"}
        start = time.perf_counter()
        model = conn.execute(
            "SELECT vec1_train(embedding, ?) FROM vectors",
            (json.dumps(parameters),),
        ).fetchone()[0]
        training_seconds = time.perf_counter() - start
        start = time.perf_counter()
        conn.execute("INSERT INTO vectors(cmd, arg) VALUES('rebuild', ?)", (model,))
        conn.commit()
        rebuild_seconds = time.perf_counter() - start

        results = []
        for nprobe in (0.25, 16):
            recalls = []
            durations_ms = []
            for query in queries:
                scores = vectors @ query
                expected = set((np.argsort(-scores, kind="stable")[:100] + 1).tolist())
                blob = query.tobytes()
                start = time.perf_counter()
                rows = conn.execute(
                    "SELECT rowid FROM vectors(?, ?) "
                    "ORDER BY vec1_cos_distance(embedding, ?) LIMIT 100",
                    (blob, json.dumps({"K": 200, "nprobe": nprobe}), blob),
                ).fetchall()
                durations_ms.append((time.perf_counter() - start) * 1000)
                recalls.append(len(expected & {row[0] for row in rows}) / 100)
            results.append({
                "nprobe": nprobe,
                "mean_recall_at_100": float(np.mean(recalls)),
                "min_recall_at_100": min(recalls),
                "p50_query_ms": float(np.percentile(durations_ms, 50)),
                "p95_query_ms": float(np.percentile(durations_ms, 95)),
            })
        print(json.dumps({
            "platform": platform.platform(),
            "python": platform.python_version(),
            "vec1": vec1_info,
            "reference": "NumPy exact cosine",
            "seed": 20261127,
            "vectors": len(vectors),
            "dimensions": vectors.shape[1],
            "queries": len(queries),
            "candidates": 200,
            "training_parameters": parameters,
            "training_seconds": training_seconds,
            "rebuild_seconds": rebuild_seconds,
            "results": results,
        }, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
