from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.curate_wikidata_vocabulary import (
    WikidataCurationError,
    WikidataVocabularyCurator,
)


def _claim(property_id: str, qid: str) -> dict[str, object]:
    return {
        "mainsnak": {
            "property": property_id,
            "datavalue": {"value": {"id": qid}},
        }
    }


def _external_id_claim(
    property_id: str,
    value: str,
    *,
    rank: str = "normal",
) -> dict[str, object]:
    return {
        "rank": rank,
        "mainsnak": {
            "property": property_id,
            "datavalue": {"value": value},
        }
    }


def _entity(
    qid: str,
    label: str,
    *,
    parent: str | None = None,
    description: str = "visible object",
    missing_locale: str | None = None,
    tgm_id: str | None = None,
    tgm_rank: str = "normal",
) -> dict[str, object]:
    labels = {
        locale: {"language": locale, "value": f"{label}-{locale}"}
        for locale in ("en", "de", "fr", "it")
        if locale != missing_locale
    }
    claims = {} if parent is None else {"P279": [_claim("P279", parent)]}
    if tgm_id is not None:
        claims["P5160"] = [
            _external_id_claim("P5160", tgm_id, rank=tgm_rank)
        ]
    return {
        "id": qid,
        "labels": labels,
        "descriptions": {"en": {"language": "en", "value": description}},
        "claims": claims,
    }


def _write_inputs(
    tmp_path: Path,
    entities: list[dict[str, object]],
    *,
    include: list[str] | None = None,
    target_count: int = 4,
) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    roots_path = tmp_path / "roots.json"
    roots_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_version": 2,
                "created_at": "2026-08-23T00:00:00+00:00",
                "source_dump_uri": "fixture.jsonl",
                "target_count": target_count,
                "domains": [
                    {
                        "name": "objects",
                        "category": "subject",
                        "target_count": target_count,
                        "max_depth": 2,
                        "root_qids": ["Q1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "include": include or [],
                "exclude": [],
            }
        ),
        encoding="utf-8",
    )
    entities_path = tmp_path / "entities.jsonl"
    entities_path.write_text(
        "\n".join(json.dumps(entity) for entity in entities) + "\n",
        encoding="utf-8",
    )
    return roots_path, overrides_path, entities_path


def _tgm_discovery_document(
    roots_path: Path,
    concepts: list[dict[str, object]],
    *,
    complete: bool = True,
) -> dict[str, object]:
    items = {str(concept["qid"]): 1 for concept in concepts}
    assignments = {
        str(concept["qid"]): {
            "domain": concept["domain"],
            "category": concept["category"],
        }
        for concept in concepts
    }
    normalized_concepts = [
        {**concept, "popularity": items[str(concept["qid"])]}
        for concept in concepts
    ]
    return {
        "schema_version": 1,
        "snapshot_version": 2,
        "complete": complete,
        "property_id": "P5160",
        "roots_sha256": hashlib.sha256(roots_path.read_bytes()).hexdigest(),
        "enumeration_complete": True,
        "classification_offset": len(items),
        "items": items,
        "assignments": assignments,
        "concepts": normalized_concepts,
        "unmapped_qids": [],
    }


def _curate(
    tmp_path: Path,
    entities: list[dict[str, object]],
    *,
    include: list[str] | None = None,
    target_count: int = 4,
) -> tuple[dict[str, object], bytes, bytes]:
    roots, overrides, source = _write_inputs(
        tmp_path,
        entities,
        include=include,
        target_count=target_count,
    )
    manifest_path = tmp_path / "manifest.json"
    review_path = tmp_path / "review.json"
    review = WikidataVocabularyCurator().curate(
        roots,
        overrides,
        source,
        manifest_path,
        review_path,
    )
    return review, manifest_path.read_bytes(), review_path.read_bytes()


def test_wikidata_curator_repeated_run_is_deterministic_and_filters_candidates(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "root"),
        _entity("Q2", "visual-child", parent="Q1"),
        _entity("Q3", "incomplete", parent="Q1", missing_locale="it"),
        _entity(
            "Q4",
            "abstract",
            parent="Q1",
            description="academic discipline concerned with examples",
        ),
    ]

    # Act
    first = _curate(tmp_path / "first", entities)
    second = _curate(tmp_path / "second", entities)

    # Assert
    assert first[1:] == second[1:]
    assert first[0]["selected_count"] == 2
    statuses = {row["qid"]: row["status"] for row in first[0]["rows"]}
    assert statuses == {
        "Q1": "included",
        "Q2": "included",
        "Q3": "excluded",
        "Q4": "excluded",
    }


def test_wikidata_curator_label_collision_keeps_explicit_priority_winner(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "root"),
        _entity("Q2", "same", parent="Q1"),
        _entity("Q3", "same", parent="Q1"),
    ]

    # Act
    review, manifest_bytes, _review_bytes = _curate(
        tmp_path,
        entities,
        include=["Q2"],
    )
    manifest = json.loads(manifest_bytes)

    # Assert
    assert [concept["qid"] for concept in manifest["concepts"]] == ["Q1", "Q2"]
    statuses = {row["qid"]: row["status"] for row in review["rows"]}
    assert statuses["Q2"] == "included"
    assert statuses["Q3"] == "excluded"
    collisions = {row["qid"]: row["collisions"] for row in review["rows"]}
    assert collisions["Q2"] == ["Q3"]
    assert collisions["Q3"] == ["Q2"]


def test_wikidata_curator_forced_include_missing_locale_raises(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [
            _entity("Q1", "root"),
            _entity("Q2", "incomplete", parent="Q1", missing_locale="it"),
        ],
        include=["Q2"],
    )

    # Act / Assert
    with pytest.raises(WikidataCurationError, match="quality gates"):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
        )


def test_wikidata_curator_conflicting_forced_include_labels_raise(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [
            _entity("Q1", "root"),
            _entity("Q2", "same", parent="Q1"),
            _entity("Q3", "same", parent="Q1"),
        ],
        include=["Q2", "Q3"],
        target_count=3,
    )

    # Act / Assert
    with pytest.raises(WikidataCurationError, match="conflicting localized labels"):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
        )


def test_wikidata_curator_include_outside_configured_domains_raises(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [_entity("Q1", "root"), _entity("Q2", "unassigned")],
        include=["Q2"],
    )

    # Act / Assert
    with pytest.raises(WikidataCurationError, match="outside configured domains"):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
        )


def test_wikidata_curator_domain_quota_is_deterministic_and_keeps_override(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "root"),
        _entity("Q2", "first", parent="Q1"),
        _entity("Q3", "forced", parent="Q1"),
    ]

    # Act
    review, manifest_bytes, _review_bytes = _curate(
        tmp_path,
        entities,
        include=["Q3"],
        target_count=2,
    )
    manifest = json.loads(manifest_bytes)

    # Assert
    assert [concept["qid"] for concept in manifest["concepts"]] == ["Q1", "Q3"]
    assert review["target_shortfall"] == 0
    assert review["domain_counts"] == [
        {
            "domain": "objects",
            "target_count": 2,
            "eligible_count": 3,
            "selected_count": 2,
            "shortfall": 0,
            "overflow": 0,
        }
    ]


def test_wikidata_curator_priority_concept_consumes_existing_domain_quota(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "root"),
        _entity("Q2", "normal", parent="Q1"),
        _entity("Q3", "priority"),
    ]
    roots, overrides, source = _write_inputs(
        tmp_path,
        entities,
        target_count=2,
    )
    priority_path = tmp_path / "priority.json"
    priority_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_version": 2,
                "concepts": [
                    {
                        "qid": "Q3",
                        "domain": "objects",
                        "category": "subject",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"

    # Act
    review = WikidataVocabularyCurator().curate(
        roots,
        overrides,
        source,
        manifest_path,
        tmp_path / "review.json",
        priority_path=priority_path,
    )

    # Assert
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [concept["qid"] for concept in manifest["concepts"]] == ["Q1", "Q3"]
    assert review["selected_count"] == 2
    assert review["domain_counts"][0]["overflow"] == 0


def test_wikidata_curator_rebalances_unused_domain_quota(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "sparse-root"),
        _entity("Q10", "rich-root"),
        _entity("Q11", "rich-child-one", parent="Q10"),
        _entity("Q12", "rich-child-two", parent="Q10"),
    ]
    roots, overrides, source = _write_inputs(tmp_path, entities, target_count=3)
    roots_document = json.loads(roots.read_text(encoding="utf-8"))
    roots_document["domains"] = [
        {
            "name": "sparse",
            "category": "subject",
            "target_count": 2,
            "max_depth": 1,
            "root_qids": ["Q1"],
        },
        {
            "name": "rich",
            "category": "subject",
            "target_count": 1,
            "max_depth": 1,
            "root_qids": ["Q10"],
        },
    ]
    roots.write_text(json.dumps(roots_document), encoding="utf-8")

    # Act
    manifest_path = tmp_path / "manifest.json"
    review_path = tmp_path / "review.json"
    review = WikidataVocabularyCurator().curate(
        roots,
        overrides,
        source,
        manifest_path,
        review_path,
    )

    # Assert
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [concept["qid"] for concept in manifest["concepts"]] == [
        "Q1",
        "Q10",
        "Q11",
    ]
    assert review["selected_count"] == 3
    assert review["target_shortfall"] == 0


def test_wikidata_curator_rebalances_from_zero_quota_domain(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "sparse-root"),
        _entity("Q10", "overflow-root"),
        _entity("Q11", "overflow-child", parent="Q10"),
    ]
    roots, overrides, source = _write_inputs(tmp_path, entities, target_count=2)
    roots_document = json.loads(roots.read_text(encoding="utf-8"))
    roots_document["domains"] = [
        {
            "name": "sparse",
            "category": "subject",
            "target_count": 2,
            "max_depth": 1,
            "root_qids": ["Q1"],
        },
        {
            "name": "overflow",
            "category": "subject",
            "target_count": 0,
            "max_depth": 1,
            "root_qids": ["Q10"],
        },
    ]
    roots.write_text(json.dumps(roots_document), encoding="utf-8")

    # Act
    manifest_path = tmp_path / "manifest.json"
    review = WikidataVocabularyCurator().curate(
        roots,
        overrides,
        source,
        manifest_path,
        tmp_path / "review.json",
    )

    # Assert
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [concept["qid"] for concept in manifest["concepts"]] == ["Q1", "Q10"]
    assert review["target_shortfall"] == 0


def test_wikidata_curator_tgm_priority_expands_beyond_base_target(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "root"),
        _entity("Q2", "zebra", parent="Q1", tgm_id="tgm011910"),
    ]

    # Act
    review, manifest_bytes, _review_bytes = _curate(
        tmp_path,
        entities,
        target_count=1,
    )

    # Assert
    manifest = json.loads(manifest_bytes)
    assert [concept["qid"] for concept in manifest["concepts"]] == ["Q1", "Q2"]
    assert review["selected_count"] == 2
    assert review["selected_overflow"] == 1
    zebra_row = next(row for row in review["rows"] if row["qid"] == "Q2")
    assert zebra_row["reasons"] == ["tgm_priority"]


def test_wikidata_curator_deprecated_tgm_claim_does_not_expand_base(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "root"),
        _entity(
            "Q2",
            "deprecated",
            parent="Q1",
            tgm_id="tgm000002",
            tgm_rank="deprecated",
        ),
    ]

    # Act
    review, manifest_bytes, _review_bytes = _curate(
        tmp_path,
        entities,
        target_count=1,
    )

    # Assert
    manifest = json.loads(manifest_bytes)
    assert [concept["qid"] for concept in manifest["concepts"]] == ["Q1"]
    deprecated_row = next(row for row in review["rows"] if row["qid"] == "Q2")
    assert deprecated_row["tgm_ids"] == []


def test_wikidata_curator_numeric_tgm_claim_is_normalized_and_expands_base(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "root"),
        _entity("Q2", "numeric", parent="Q1", tgm_id="000002"),
    ]

    # Act
    review, _manifest_bytes, _review_bytes = _curate(
        tmp_path,
        entities,
        target_count=1,
    )

    # Assert
    numeric_row = next(row for row in review["rows"] if row["qid"] == "Q2")
    assert numeric_row["tgm_ids"] == ["tgm000002"]
    assert numeric_row["reasons"] == ["tgm_priority"]


def test_wikidata_curator_tgm_overflow_collision_records_both_qids(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "same"),
        _entity("Q2", "same", parent="Q1", tgm_id="tgm000002"),
    ]

    # Act
    review, _manifest_bytes, _review_bytes = _curate(
        tmp_path,
        entities,
        target_count=1,
    )

    # Assert
    rows = {row["qid"]: row for row in review["rows"]}
    assert rows["Q1"]["collisions"] == ["Q2"]
    assert rows["Q2"]["collisions"] == ["Q1"]
    assert rows["Q2"]["reasons"] == ["label_collision"]


def test_wikidata_curator_tgm_overflow_collision_records_all_qids(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "same"),
        _entity("Q2", "same", parent="Q1", tgm_id="tgm000002"),
        _entity("Q3", "same", parent="Q1", tgm_id="tgm000003"),
    ]

    # Act
    review, _manifest_bytes, _review_bytes = _curate(
        tmp_path,
        entities,
        target_count=1,
    )

    # Assert
    rows = {row["qid"]: row for row in review["rows"]}
    assert rows["Q1"]["collisions"] == ["Q2", "Q3"]
    assert rows["Q2"]["collisions"] == ["Q1", "Q3"]
    assert rows["Q3"]["collisions"] == ["Q1", "Q2"]

def test_wikidata_curator_quota_collision_records_all_non_tgm_qids(
    tmp_path: Path,
) -> None:
    # Arrange
    entities = [
        _entity("Q1", "same"),
        _entity("Q2", "same", parent="Q1"),
        _entity("Q3", "same", parent="Q1"),
    ]

    # Act
    review, _manifest_bytes, _review_bytes = _curate(
        tmp_path,
        entities,
        target_count=1,
    )

    # Assert
    rows = {row["qid"]: row for row in review["rows"]}
    assert rows["Q1"]["collisions"] == ["Q2", "Q3"]
    assert rows["Q2"]["collisions"] == ["Q1", "Q3"]
    assert rows["Q3"]["collisions"] == ["Q1", "Q2"]


def test_wikidata_curator_tgm_discovery_adds_undiscovered_concept_after_baseline(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [
            _entity("Q1", "baseline"),
            _entity("Q2", "zebra", tgm_id="tgm011910"),
        ],
        target_count=1,
    )
    tgm_discovery_path = tmp_path / "tgm-discovery.json"
    tgm_discovery_path.write_text(
        json.dumps(
            _tgm_discovery_document(
                roots,
                [
                    {
                        "qid": "Q2",
                        "domain": "objects",
                        "category": "subject",
                        "priority": 1,
                    }
                ],
            )
        ),
        encoding="utf-8",
    )

    # Act
    manifest_path = tmp_path / "manifest.json"
    review = WikidataVocabularyCurator().curate(
        roots,
        overrides,
        source,
        manifest_path,
        tmp_path / "review.json",
        tgm_discovery_path=tgm_discovery_path,
    )

    # Assert
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [concept["qid"] for concept in manifest["concepts"]] == ["Q1", "Q2"]
    assert review["selected_count"] == 2
    zebra_row = next(row for row in review["rows"] if row["qid"] == "Q2")
    assert zebra_row["reasons"] == ["tgm_priority"]


def test_wikidata_curator_tgm_only_graph_concept_preserves_base_identity(
    tmp_path: Path,
) -> None:
    # Arrange
    base_entities = [
        _entity("Q1", "root"),
        _entity("Q20", "base", parent="Q1"),
    ]
    expanded_entities = [
        *base_entities,
        _entity("Q2", "tgm", parent="Q1", tgm_id="tgm000002"),
    ]
    roots, overrides, source = _write_inputs(
        tmp_path,
        expanded_entities,
        target_count=2,
    )
    broad_discovery_path = tmp_path / "broad-discovery.json"
    broad_discovery_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_version": 2,
                "completed_domains": ["objects"],
                "concepts": [
                    {
                        "qid": "Q1",
                        "domain": "objects",
                        "category": "subject",
                        "priority": 1,
                    },
                    {
                        "qid": "Q20",
                        "domain": "objects",
                        "category": "subject",
                        "priority": 2,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    tgm_discovery_path = tmp_path / "tgm-discovery.json"
    tgm_discovery_path.write_text(
        json.dumps(
            _tgm_discovery_document(
                roots,
                [
                    {
                        "qid": "Q2",
                        "domain": "objects",
                        "category": "subject",
                        "priority": 1,
                    }
                ],
            )
        ),
        encoding="utf-8",
    )

    # Act
    manifest_path = tmp_path / "manifest.json"
    review = WikidataVocabularyCurator().curate(
        roots,
        overrides,
        source,
        manifest_path,
        tmp_path / "review.json",
        discovery_path=broad_discovery_path,
        tgm_discovery_path=tgm_discovery_path,
    )

    # Assert
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [concept["qid"] for concept in manifest["concepts"]] == [
        "Q1",
        "Q2",
        "Q20",
    ]
    tgm_row = next(row for row in review["rows"] if row["qid"] == "Q2")
    assert tgm_row["reasons"] == ["tgm_priority"]


def test_wikidata_curator_incomplete_tgm_discovery_raises(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [_entity("Q1", "root")],
        target_count=1,
    )
    tgm_discovery_path = tmp_path / "tgm-discovery.json"
    tgm_discovery_path.write_text(
        json.dumps(_tgm_discovery_document(roots, [], complete=False)),
        encoding="utf-8",
    )

    # Act / Assert
    with pytest.raises(
        WikidataCurationError,
        match="TGM discovery is incomplete or mismatched",
    ):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
            tgm_discovery_path=tgm_discovery_path,
        )


def test_wikidata_curator_inconsistent_complete_tgm_discovery_raises(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [_entity("Q1", "root")],
        target_count=1,
    )
    document = _tgm_discovery_document(
        roots,
        [
            {
                "qid": "Q1",
                "domain": "objects",
                "category": "subject",
                "priority": 1,
            }
        ],
    )
    document["concepts"] = []
    tgm_discovery_path = tmp_path / "tgm-discovery.json"
    tgm_discovery_path.write_text(json.dumps(document), encoding="utf-8")

    # Act / Assert
    with pytest.raises(
        WikidataCurationError,
        match="inconsistent TGM discovery concepts",
    ):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
            tgm_discovery_path=tgm_discovery_path,
        )


def test_wikidata_curator_tgm_discovery_without_current_claim_raises(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [_entity("Q1", "root")],
        target_count=1,
    )
    document = _tgm_discovery_document(
        roots,
        [
            {
                "qid": "Q1",
                "domain": "objects",
                "category": "subject",
                "priority": 1,
            }
        ],
    )
    tgm_discovery_path = tmp_path / "tgm-discovery.json"
    tgm_discovery_path.write_text(json.dumps(document), encoding="utf-8")

    # Act / Assert
    with pytest.raises(WikidataCurationError, match="lacks a current P5160 claim"):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
            tgm_discovery_path=tgm_discovery_path,
        )


def test_wikidata_curator_tgm_discovery_with_modified_priority_raises(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [_entity("Q1", "root", tgm_id="tgm000001")],
        target_count=1,
    )
    document = _tgm_discovery_document(
        roots,
        [
            {
                "qid": "Q1",
                "domain": "objects",
                "category": "subject",
                "priority": 2,
            }
        ],
    )
    tgm_discovery_path = tmp_path / "tgm-discovery.json"
    tgm_discovery_path.write_text(json.dumps(document), encoding="utf-8")

    # Act / Assert
    with pytest.raises(
        WikidataCurationError,
        match="inconsistent TGM discovery concepts",
    ):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
            tgm_discovery_path=tgm_discovery_path,
        )


def test_wikidata_curator_tgm_discovery_with_boolean_popularity_raises(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [_entity("Q1", "root", tgm_id="tgm000001")],
        target_count=1,
    )
    document = _tgm_discovery_document(
        roots,
        [
            {
                "qid": "Q1",
                "domain": "objects",
                "category": "subject",
                "priority": 1,
            }
        ],
    )
    document["concepts"][0]["popularity"] = True  # type: ignore[index]
    tgm_discovery_path = tmp_path / "tgm-discovery.json"
    tgm_discovery_path.write_text(json.dumps(document), encoding="utf-8")

    # Act / Assert
    with pytest.raises(
        WikidataCurationError,
        match="inconsistent TGM discovery concepts",
    ):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
            tgm_discovery_path=tgm_discovery_path,
        )


def test_wikidata_curator_forced_includes_exceeding_quota_raises(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [_entity("Q1", "root"), _entity("Q2", "child", parent="Q1")],
        include=["Q1", "Q2"],
        target_count=1,
    )

    # Act / Assert
    with pytest.raises(WikidataCurationError, match="forced includes"):
        WikidataVocabularyCurator().curate(
            roots,
            overrides,
            source,
            tmp_path / "manifest.json",
            tmp_path / "review.json",
        )


def test_wikidata_curator_include_assignment_adds_undiscovered_concept(
    tmp_path: Path,
) -> None:
    # Arrange
    roots, overrides, source = _write_inputs(
        tmp_path,
        [_entity("Q1", "root"), _entity("Q2", "priority")],
        target_count=2,
    )
    overrides.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "include": [],
                "include_assignments": [
                    {
                        "qid": "Q2",
                        "domain": "objects",
                        "category": "subject",
                    }
                ],
                "exclude": [],
            }
        ),
        encoding="utf-8",
    )

    # Act
    manifest_path = tmp_path / "manifest.json"
    review = WikidataVocabularyCurator().curate(
        roots,
        overrides,
        source,
        manifest_path,
        tmp_path / "review.json",
    )

    # Assert
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [concept["qid"] for concept in manifest["concepts"]] == ["Q1", "Q2"]
    priority_row = next(row for row in review["rows"] if row["qid"] == "Q2")
    assert priority_row["reasons"] == ["explicitly_included"]