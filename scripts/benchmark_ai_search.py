"""Synthetic five-view FAISS benchmark; never loads a model or source image."""
from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
import zlib

import numpy as np

from exif_turbo.data.ai_search_session import AiSearchSession
from exif_turbo.data.ai_vector_repository import AiVectorRepository


class _MemoryCounters(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32), ("faults", ctypes.c_uint32),
        ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
        ("peak_paged_pool", ctypes.c_size_t), ("paged_pool", ctypes.c_size_t),
        ("peak_nonpaged_pool", ctypes.c_size_t), ("nonpaged_pool", ctypes.c_size_t),
        ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t),
    ]


class AiSearchBenchmark:
    _VIEWS = ("full", "top_left", "top_right", "bottom_left", "bottom_right")

    def compare_indexes(self, image_count: int, batch_size: int, queries: int) -> dict[str, object]:
        import faiss

        faiss.omp_set_num_threads(1)
        generator = np.random.default_rng(42)
        exact = faiss.IndexFlatIP(512)
        for offset in range(0, image_count, batch_size):
            count = min(batch_size, image_count - offset)
            vectors = generator.standard_normal((count * 5, 512), dtype=np.float32)
            vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
            exact.add(vectors)
        query_vectors = generator.standard_normal((queries, 512), dtype=np.float32)
        query_vectors /= np.linalg.norm(query_vectors, axis=1, keepdims=True)
        reference: list[np.ndarray] = []
        for query in query_vectors:
            scores, rows = exact.search(query.reshape(1, -1), exact.ntotal)
            pooled = np.full(image_count, -np.inf, dtype=np.float32)
            np.maximum.at(pooled, rows[0] // 5, scores[0])
            reference.append(pooled)
        results: list[dict[str, object]] = []
        for name, quantizer in (
            ("float16", faiss.ScalarQuantizer.QT_fp16),
            ("scalar8", faiss.ScalarQuantizer.QT_8bit),
        ):
            candidate = faiss.IndexScalarQuantizer(512, quantizer, faiss.METRIC_INNER_PRODUCT)
            training = exact.reconstruct_n(0, min(exact.ntotal, 50000))
            started = time.perf_counter()
            candidate.train(training)
            del training
            for offset in range(0, exact.ntotal, batch_size * 5):
                candidate.add(exact.reconstruct_n(offset, min(batch_size * 5, exact.ntotal - offset)))
            build_seconds = time.perf_counter() - started
            recall: list[float] = []
            errors: list[float] = []
            changes = {str(threshold): 0 for threshold in (0.18, 0.20, 0.22)}
            started = time.perf_counter()
            for query, expected in zip(query_vectors, reference):
                scores, rows = candidate.search(query.reshape(1, -1), candidate.ntotal)
                actual = np.full(image_count, -np.inf, dtype=np.float32)
                np.maximum.at(actual, rows[0] // 5, scores[0])
                top_k = min(100, image_count)
                reference_ids = set(np.argsort(-expected, kind="stable")[:top_k])
                candidate_ids = set(np.argsort(-actual, kind="stable")[:top_k])
                recall.append(len(reference_ids & candidate_ids) / top_k)
                errors.append(float(np.max(np.abs(actual - expected))))
                for threshold in (0.18, 0.20, 0.22):
                    changes[str(threshold)] += int(np.count_nonzero((actual >= threshold) != (expected >= threshold)))
            query_seconds = time.perf_counter() - started
            results.append({
                "index": name, "serialized_bytes": int(faiss.serialize_index(candidate).nbytes),
                "build_seconds": build_seconds, "all_image_query_seconds": query_seconds,
                "mean_image_recall_at_100": statistics.mean(recall),
                "max_image_score_error": max(errors), "threshold_eligibility_changes": changes,
            })
            del candidate
            gc.collect()
        mapping = {
            str(image * 5 + view): {"path": f"/synthetic/library/{image:08d}.jpg", "view_id": view_id}
            for image in range(image_count) for view, view_id in enumerate(self._VIEWS)
        }
        original_mapping = json.dumps(mapping).encode("utf-8")
        del mapping
        compact_mapping = json.dumps(
            {"views": self._VIEWS, "paths": [f"/synthetic/library/{image:08d}.jpg" for image in range(image_count)]},
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "images": image_count, "queries": queries, "views_per_image": 5, "dimension": 512,
            "reference_serialized_bytes": int(faiss.serialize_index(exact).nbytes),
            "candidates": results, "mapping_bytes": len(original_mapping),
            "mapping_zlib_bytes": len(zlib.compress(original_mapping)),
            "compact_full_five_view_mapping_bytes": len(compact_mapping),
            "compact_mapping_limitation": "assumes complete ordered five-view groups; not a production format",
            "peak_process_rss_bytes": self._peak_rss(), "faiss": faiss.__version__,
            "python": platform.python_version(), "platform": platform.platform(),
            "quality_limitation": "independent synthetic vectors/queries; no semantic relevance certification",
        }

    @staticmethod
    def _peak_rss() -> int:
        if sys.platform == "win32":
            counters = _MemoryCounters()
            counters.size = ctypes.sizeof(counters)
            function = ctypes.windll.psapi.GetProcessMemoryInfo
            function.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MemoryCounters), ctypes.c_uint32]
            function.restype = ctypes.c_int
            if not function(ctypes.c_void_p(-1), ctypes.byref(counters), counters.size):
                raise ctypes.WinError()
            return int(counters.peak_working_set)
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)

    def run(self, image_count: int, batch_size: int, encrypted: bool, repeats: int) -> dict[str, object]:
        import faiss

        faiss.omp_set_num_threads(1)
        key = "synthetic-benchmark-password" if encrypted else ""
        with tempfile.TemporaryDirectory(prefix="exif-turbo-ai-benchmark-") as name:
            root = Path(name)
            paths = (root / "ai_index.faiss", root / "ai_id_map.json", root / "ai_index_meta.json")
            repository = AiVectorRepository(*paths, key=key)
            repository.load()
            generator = np.random.default_rng(42)
            batch_seconds = 0.0
            legacy_scan_seconds = 0.0
            query = np.zeros(512, dtype=np.float32)
            for offset in range(0, image_count, batch_size):
                count = min(batch_size, image_count - offset)
                vectors = generator.standard_normal((count * 5, 512), dtype=np.float32)
                vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
                image_paths = [f"/synthetic/library/{offset + image:08d}.jpg" for image in range(count)]
                row_paths = [path for path in image_paths for _view in self._VIEWS]
                view_ids = list(self._VIEWS) * count
                if offset == 0:
                    query = vectors[0].copy()
                start = time.perf_counter()
                existing_rows = {(row["path"], row["view_id"]) for row in repository._id_map.values()}
                if any(row in existing_rows for row in zip(row_paths, view_ids)):
                    raise RuntimeError("Synthetic benchmark generated duplicate views")
                legacy_scan_seconds += time.perf_counter() - start
                del existing_rows
                start = time.perf_counter()
                repository.add_images(vectors, row_paths, view_ids=view_ids)
                batch_seconds += time.perf_counter() - start
            start = time.perf_counter()
            repository.save()
            save_seconds = time.perf_counter() - start
            disk_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
            del repository, vectors
            gc.collect()
            baseline_times: list[float] = []
            expected: list[tuple[str, float]] = []
            for _repeat in range(repeats):
                start = time.perf_counter()
                loaded = AiVectorRepository(*paths, key=key)
                loaded.load()
                expected = loaded.search(query, top_k=2000, threshold=0.0)
                baseline_times.append(time.perf_counter() - start)
                del loaded
                gc.collect()
            session = AiSearchSession(*paths)
            start = time.perf_counter()
            with session.repository(key) as loaded:
                actual = loaded.search(query, top_k=2000, threshold=0.0)
            cold_seconds = time.perf_counter() - start
            warm_times: list[float] = []
            for _repeat in range(repeats):
                start = time.perf_counter()
                with session.repository(key) as loaded:
                    actual = loaded.search(query, top_k=2000, threshold=0.0)
                warm_times.append(time.perf_counter() - start)
                if actual != expected:
                    raise RuntimeError("Cached search changed ranking or scores")
            peak_rss = self._peak_rss()
            session.close()
            return {
                "images": image_count, "views_per_image": 5, "dimension": 512,
                "mode": "encrypted" if encrypted else "plaintext", "batch_images": batch_size,
                "raw_vector_bytes": image_count * 5 * 512 * 4, "disk_bytes": disk_bytes,
                "append_seconds": batch_seconds, "legacy_full_row_scan_seconds": legacy_scan_seconds,
                "modeled_legacy_append_seconds": batch_seconds + legacy_scan_seconds,
                "save_seconds": save_seconds, "reload_search_seconds": baseline_times,
                "reload_search_median_seconds": statistics.median(baseline_times),
                "session_cold_seconds": cold_seconds, "session_warm_seconds": warm_times,
                "session_warm_median_seconds": statistics.median(warm_times),
                "peak_process_rss_bytes": peak_rss, "results": len(expected),
                "python": platform.python_version(), "platform": platform.platform(),
                "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                "faiss": faiss.__version__, "faiss_threads": 1, "repeats": repeats,
            }

    @classmethod
    def main(cls) -> None:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--images", type=int, default=10000)
        parser.add_argument("--batch-size", type=int, default=256)
        parser.add_argument("--repeats", type=int, default=3)
        parser.add_argument("--encrypted", action="store_true")
        parser.add_argument("--compare-indexes", action="store_true")
        parser.add_argument("--output", type=Path)
        options = parser.parse_args()
        if min(options.images, options.batch_size, options.repeats) <= 0:
            parser.error("images, batch-size, and repeats must be positive")
        benchmark = cls()
        result = (
            benchmark.compare_indexes(options.images, options.batch_size, options.repeats)
            if options.compare_indexes else
            benchmark.run(options.images, options.batch_size, options.encrypted, options.repeats)
        )
        text = json.dumps(result, indent=2)
        if options.output is not None:
            options.output.parent.mkdir(parents=True, exist_ok=True)
            options.output.write_text(text + "\n", encoding="utf-8")
        print(text, flush=True)


if __name__ == "__main__":
    AiSearchBenchmark.main()