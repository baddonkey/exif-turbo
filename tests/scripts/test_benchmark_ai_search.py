import pytest

from scripts.benchmark_ai_search import AiSearchBenchmark

def test_ai_search_benchmark_candidate_comparison_reports_quality_and_size() -> None:
    # Arrange
    benchmark = AiSearchBenchmark()

    # Act
    result = benchmark.compare_indexes(image_count=200, batch_size=50, queries=2)

    # Assert
    assert len(result["candidates"]) == 2
    for candidate in result["candidates"]:
        assert candidate["serialized_bytes"] < result["reference_serialized_bytes"]
        assert 0 <= candidate["mean_image_recall_at_100"] <= 1
        assert candidate["max_image_score_error"] >= 0


@pytest.mark.parametrize("encrypted", [False, True])
def test_ai_search_benchmark_small_library_preserves_search_results(encrypted: bool) -> None:
    # Arrange
    benchmark = AiSearchBenchmark()

    # Act
    result = benchmark.run(image_count=20, batch_size=7, encrypted=encrypted, repeats=2)

    # Assert
    assert result["images"] == 20
    assert result["raw_vector_bytes"] == 20 * 5 * 512 * 4
    assert result["disk_bytes"] > result["raw_vector_bytes"]
    assert result["peak_process_rss_bytes"] > 0
    assert len(result["session_warm_seconds"]) == 2