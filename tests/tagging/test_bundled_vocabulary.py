from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import exif_turbo

from exif_turbo.config import bundled_vocabulary_path
from exif_turbo.models.vocabulary import REQUIRED_VOCABULARY_LOCALES
from exif_turbo.tagging.vocabulary_snapshot_repository import (
    VocabularySnapshotRepository,
)


def test_bundled_vocabulary_matches_reviewed_manifest_and_required_locales() -> None:
    # Arrange
    repository_root = Path(__file__).parents[2]
    manifest_path = repository_root / "assets" / "wikidata" / "vocabulary-manifest-v2.json"
    source_path = (
        repository_root
        / "assets"
        / "wikidata"
        / "wikidata-visual-entities-v2.jsonl"
    )
    review_path = repository_root / "assets" / "wikidata" / "wikidata-review-v2.json"
    snapshot_path = bundled_vocabulary_path()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))

    # Act
    snapshot = VocabularySnapshotRepository(snapshot_path).load()
    with source_path.open("rb") as source_stream:
        source_sha256 = hashlib.file_digest(source_stream, "sha256").hexdigest()

    # Assert
    assert len(snapshot.concepts) == len(manifest["concepts"]) == 8_339
    assert snapshot_path.parent == Path(exif_turbo.__file__).parent / "assets"
    assert source_sha256 == manifest["source"]["dump_sha256"]
    assert snapshot.source_dump_sha256 == source_sha256
    assert snapshot.manifest_sha256 == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    snapshot_concepts = [
        {
            "qid": concept.concept_id.removeprefix("wikidata:"),
            "category": concept.category.value,
        }
        for concept in snapshot.concepts
    ]
    assert snapshot_concepts == manifest["concepts"]
    reviewed_concepts = sorted(
        (
            {"qid": row["qid"], "category": row["category"]}
            for row in review["rows"]
            if row["status"] == "included"
        ),
        key=lambda concept: int(concept["qid"][1:]),
    )
    assert reviewed_concepts == manifest["concepts"]
    base_rows = [
        row
        for row in review["rows"]
        if row["status"] == "included" and row["reasons"] != ["tgm_priority"]
    ]
    overflow_rows = [
        row
        for row in review["rows"]
        if row["status"] == "included" and row["reasons"] == ["tgm_priority"]
    ]
    assert len(base_rows) == review["target_count"] == 8_200
    assert len(overflow_rows) == review["selected_overflow"] == 139
    assert review["selected_count"] == 8_339
    assert review["target_shortfall"] == 0
    assert all(row["tgm_ids"] for row in overflow_rows)
    assert review["source_sha256"] == source_sha256
    assert all(
        {terms.locale for terms in concept.localized_terms}
        == REQUIRED_VOCABULARY_LOCALES
        for concept in snapshot.concepts
    )


def test_bundled_vocabulary_contains_zebra_visual_concept() -> None:
    # Arrange
    snapshot = VocabularySnapshotRepository(bundled_vocabulary_path()).load()

    # Act
    zebra = snapshot.concept_by_id("wikidata:Q32789")

    # Assert
    assert zebra is not None
    assert zebra.preferred_label("en") == "zebra"
    assert "zebras" in zebra.aliases("en")


def test_bundled_vocabulary_giraffe_search_returns_generic_concept() -> None:
    # Arrange
    repository = VocabularySnapshotRepository(bundled_vocabulary_path())

    # Act
    english_results = repository.search("giraffe", "en")
    german_results = repository.search("Giraffe", "de")

    # Assert
    assert [concept.concept_id for concept in english_results] == [
        "wikidata:Q862089"
    ]
    assert [concept.concept_id for concept in german_results] == [
        "wikidata:Q862089"
    ]


def test_bundled_vocabulary_contains_priority_visual_concepts() -> None:
    # Arrange
    repository_root = Path(__file__).parents[2]
    priority_path = (
        repository_root
        / "assets"
        / "wikidata"
        / "priority-visual-concepts-v2.json"
    )
    priority = json.loads(priority_path.read_text(encoding="utf-8"))
    snapshot = VocabularySnapshotRepository(bundled_vocabulary_path()).load()

    # Act
    missing_qids = [
        concept["qid"]
        for concept in priority["concepts"]
        if snapshot.concept_by_id(f"wikidata:{concept['qid']}") is None
    ]

    # Assert
    assert missing_qids == []


def test_bundled_vocabulary_regenerates_byte_identically(tmp_path: Path) -> None:
    # Arrange
    repository_root = Path(__file__).parents[2]
    manifest_path = repository_root / "assets" / "wikidata" / "vocabulary-manifest-v2.json"
    source_path = (
        repository_root
        / "assets"
        / "wikidata"
        / "wikidata-visual-entities-v2.jsonl"
    )
    regenerated_path = tmp_path / "wikidata-vocabulary-v2.json.gz"

    # Act
    subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts" / "generate_wikidata_snapshot.py"),
            "--manifest",
            str(manifest_path),
            "--dump",
            str(source_path),
            "--output",
            str(regenerated_path),
        ],
        check=True,
    )

    # Assert
    assert regenerated_path.read_bytes() == bundled_vocabulary_path().read_bytes()


def test_reviewed_vocabulary_inputs_regenerate_byte_identically(tmp_path: Path) -> None:
    # Arrange
    repository_root = Path(__file__).parents[2]
    assets_path = repository_root / "assets" / "wikidata"
    expected_manifest_path = assets_path / "vocabulary-manifest-v2.json"
    expected_review_path = assets_path / "wikidata-review-v2.json"
    regenerated_manifest_path = tmp_path / "vocabulary-manifest-v2.json"
    regenerated_review_path = tmp_path / "wikidata-review-v2.json"

    # Act
    subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts" / "curate_wikidata_vocabulary.py"),
            str(assets_path / "visual-domain-roots.json"),
            str(assets_path / "curation-overrides.json"),
            str(assets_path / "wikidata-visual-entities-v2.jsonl"),
            str(regenerated_manifest_path),
            str(regenerated_review_path),
            "--discovery",
            str(assets_path / "wikidata-discovery-v2.json"),
            "--tgm-discovery",
            str(assets_path / "wikidata-tgm-discovery-v2.json"),
            "--priority",
            str(assets_path / "priority-visual-concepts-v2.json"),
        ],
        check=True,
    )

    # Assert
    assert regenerated_manifest_path.read_bytes() == expected_manifest_path.read_bytes()
    assert regenerated_review_path.read_bytes() == expected_review_path.read_bytes()