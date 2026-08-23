from __future__ import annotations

import pytest

from scripts.calibrate_tagging_thresholds import TaggingCalibrationError, calibrate


def test_calibrate_tagging_thresholds_reports_ranked_and_threshold_metrics() -> None:
    # Arrange
    evaluation = {
        "schema_version": 1,
        "images": [
            {
                "image": "boat.jpg",
                "expected_qids": ["wikidata:Q1", "wikidata:Q2"],
                "hard_negative_qids": ["wikidata:Q9"],
                "candidates": [
                    {"concept_id": "wikidata:Q9", "score": 0.40},
                    {"concept_id": "wikidata:Q1", "score": 0.35},
                    {"concept_id": "wikidata:Q2", "score": 0.15},
                ],
            },
            {
                "image": "forest.jpg",
                "expected_qids": ["wikidata:Q3"],
                "hard_negative_qids": ["wikidata:Q8"],
                "candidates": [
                    {"concept_id": "wikidata:Q3", "score": 0.30},
                    {"concept_id": "wikidata:Q8", "score": 0.10},
                ],
            },
        ],
    }

    # Act
    report = calibrate(evaluation, thresholds=(0.2, 0.35))

    # Assert
    assert report["recall_at_5"] == 1.0
    assert report["mean_reciprocal_rank"] == pytest.approx(0.75)
    assert report["thresholds"] == [
        {
            "threshold": 0.2,
            "true_positives": 2,
            "hard_negative_false_positives": 1,
            "hard_negative_precision": 0.666667,
            "recall": 0.666667,
        },
        {
            "threshold": 0.35,
            "true_positives": 1,
            "hard_negative_false_positives": 1,
            "hard_negative_precision": 0.5,
            "recall": 0.333333,
        },
    ]


@pytest.mark.parametrize(
    ("expected_qids", "score"),
    [
        ("wikidata:Q1", 0.2),
        (["wikidata:Q1", "wikidata:Q1"], 0.2),
        (["wikidata:Q1"], True),
        (["wikidata:Q1"], float("nan")),
        (["wikidata:Q1"], float("inf")),
    ],
)
def test_calibrate_tagging_thresholds_invalid_input_raises(
    expected_qids: object,
    score: object,
) -> None:
    # Arrange
    evaluation = {
        "schema_version": 1,
        "images": [
            {
                "expected_qids": expected_qids,
                "hard_negative_qids": [],
                "candidates": [
                    {"concept_id": "wikidata:Q1", "score": score}
                ],
            }
        ],
    }

    # Act / Assert
    with pytest.raises(TaggingCalibrationError):
        calibrate(evaluation, thresholds=(0.2,))


@pytest.mark.parametrize(
    "thresholds",
    [(), (True,), (float("nan"),), (1.1,)],
)
def test_calibrate_tagging_thresholds_invalid_threshold_raises(
    thresholds: tuple[float, ...],
) -> None:
    # Arrange
    evaluation = {
        "schema_version": 1,
        "images": [
            {
                "expected_qids": ["wikidata:Q1"],
                "hard_negative_qids": [],
                "candidates": [],
            }
        ],
    }

    # Act / Assert
    with pytest.raises(TaggingCalibrationError, match="thresholds"):
        calibrate(evaluation, thresholds=thresholds)


@pytest.mark.parametrize(
    ("concept_id", "score"),
    [("not-a-qid", 0.2), ("wikidata:Q1", 1.1)],
)
def test_calibrate_tagging_thresholds_invalid_candidate_domain_raises(
    concept_id: str,
    score: float,
) -> None:
    # Arrange
    evaluation = {
        "schema_version": 1,
        "images": [
            {
                "expected_qids": ["wikidata:Q1"],
                "hard_negative_qids": [],
                "candidates": [{"concept_id": concept_id, "score": score}],
            }
        ],
    }

    # Act / Assert
    with pytest.raises(TaggingCalibrationError):
        calibrate(evaluation, thresholds=(0.2,))