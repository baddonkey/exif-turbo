#!/usr/bin/env python3
"""Calculate ranked-retrieval and threshold metrics for tag proposals."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any


class TaggingCalibrationError(RuntimeError):
    """The proposal evaluation input is invalid."""


_CONCEPT_ID_PATTERN = re.compile(r"^wikidata:Q[1-9]\d*$")


def _safe_ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _identifier_set(value: object, field: str) -> set[str]:
    if not isinstance(value, list) or not all(
        isinstance(identifier, str) and _CONCEPT_ID_PATTERN.fullmatch(identifier)
        for identifier in value
    ):
        raise TaggingCalibrationError(f"{field} must be an array of identifiers")
    identifiers = set(value)
    if len(identifiers) != len(value):
        raise TaggingCalibrationError(f"{field} must contain unique identifiers")
    return identifiers


def calibrate(
    evaluation: object,
    *,
    thresholds: tuple[float, ...],
) -> dict[str, Any]:
    if not isinstance(evaluation, dict) or evaluation.get("schema_version") != 1:
        raise TaggingCalibrationError("unsupported evaluation schema")
    images = evaluation.get("images")
    if not isinstance(images, list) or not images:
        raise TaggingCalibrationError("evaluation must contain images")
    if not thresholds or any(
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or threshold < -1.0
        or threshold > 1.0
        for threshold in thresholds
    ):
        raise TaggingCalibrationError(
            "thresholds must be finite cosine similarities between -1 and 1"
        )
    recall_sums = {5: 0.0, 10: 0.0, 20: 0.0}
    reciprocal_rank_sum = 0.0
    total_expected = 0
    normalized: list[tuple[set[str], set[str], list[tuple[str, float]]]] = []
    for image in images:
        if not isinstance(image, dict):
            raise TaggingCalibrationError("image evaluations must be objects")
        expected = _identifier_set(image.get("expected_qids"), "expected_qids")
        hard_negatives = _identifier_set(
            image.get("hard_negative_qids"), "hard_negative_qids"
        )
        if not expected or expected.intersection(hard_negatives):
            raise TaggingCalibrationError(
                "each image needs non-overlapping expected and hard-negative QIDs"
            )
        candidates_value = image.get("candidates")
        if not isinstance(candidates_value, list):
            raise TaggingCalibrationError("candidates must be an array")
        candidates: list[tuple[str, float]] = []
        seen: set[str] = set()
        for candidate in candidates_value:
            if not isinstance(candidate, dict):
                raise TaggingCalibrationError("candidate entries must be objects")
            concept_id = candidate.get("concept_id")
            score = candidate.get("score")
            if (
                not isinstance(concept_id, str)
                or _CONCEPT_ID_PATTERN.fullmatch(concept_id) is None
                or concept_id in seen
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or score < -1.0
                or score > 1.0
            ):
                raise TaggingCalibrationError(
                    "candidates need unique IDs and finite numeric scores"
                )
            seen.add(concept_id)
            candidates.append((concept_id, float(score)))
        candidates.sort(key=lambda value: (-value[1], value[0]))
        ranked_ids = [concept_id for concept_id, _score in candidates]
        for cutoff in recall_sums:
            recall_sums[cutoff] += _safe_ratio(
                len(expected.intersection(ranked_ids[:cutoff])),
                len(expected),
            )
        first_rank = next(
            (rank for rank, concept_id in enumerate(ranked_ids, start=1) if concept_id in expected),
            None,
        )
        reciprocal_rank_sum += 0.0 if first_rank is None else 1.0 / first_rank
        total_expected += len(expected)
        normalized.append((expected, hard_negatives, candidates))
    threshold_rows: list[dict[str, float | int]] = []
    for threshold in sorted(set(float(value) for value in thresholds)):
        true_positives = 0
        hard_negative_false_positives = 0
        for expected, hard_negatives, candidates in normalized:
            selected = {
                concept_id for concept_id, score in candidates if score >= threshold
            }
            true_positives += len(selected.intersection(expected))
            hard_negative_false_positives += len(
                selected.intersection(hard_negatives)
            )
        threshold_rows.append(
            {
                "threshold": threshold,
                "true_positives": true_positives,
                "hard_negative_false_positives": hard_negative_false_positives,
                "hard_negative_precision": round(
                    _safe_ratio(
                        true_positives,
                        true_positives + hard_negative_false_positives,
                    ),
                    6,
                ),
                "recall": round(_safe_ratio(true_positives, total_expected), 6),
            }
        )
    image_count = len(normalized)
    return {
        "schema_version": 1,
        "image_count": image_count,
        "expected_positive_count": total_expected,
        "recall_at_5": round(recall_sums[5] / image_count, 6),
        "recall_at_10": round(recall_sums[10] / image_count, 6),
        "recall_at_20": round(recall_sums[20] / image_count, 6),
        "mean_reciprocal_rank": round(reciprocal_rank_sum / image_count, 6),
        "thresholds": threshold_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--thresholds",
        default="0.10,0.15,0.20,0.25,0.30,0.35,0.40",
        help="comma-separated cosine similarity thresholds",
    )
    arguments = parser.parse_args()
    thresholds = tuple(float(value) for value in arguments.thresholds.split(","))
    evaluation = json.loads(arguments.evaluation.read_text(encoding="utf-8"))
    report = calibrate(evaluation, thresholds=thresholds)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())