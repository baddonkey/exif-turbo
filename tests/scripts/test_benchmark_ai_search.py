from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.benchmark_ai_search import run_benchmark


def test_ai_search_benchmark_reports_five_view_encrypted_search() -> None:
    # Arrange
    extension = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not extension:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")

    # Act
    result = run_benchmark(Path(extension), image_count=20, batch_size=7, repeats=2)

    # Assert
    assert result["images"] == 20
    assert result["vectors"] == 100
    assert result["encrypted"] is True
    assert result["results"] == 20
    assert result["database_bytes"] > 0
    assert result["query_p95_ms"] > 0
