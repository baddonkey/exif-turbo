from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pytest

from exif_turbo.tagging.vocabulary_snapshot_repository import (
    VocabularySnapshotRepository,
)
from scripts.generate_wikidata_snapshot import (
    WikidataGenerationError,
    WikidataSnapshotGenerator,
)


def _entity(qid: str, *, missing_locale: str | None = None) -> dict[str, object]:
    labels = {
        "en": {"language": "en", "value": "Forest"},
        "de": {"language": "de", "value": "Wald"},
        "fr": {"language": "fr", "value": "Forêt"},
        "it": {"language": "it", "value": "Foresta"},
    }
    if missing_locale is not None:
        labels.pop(missing_locale)
    return {
        "id": qid,
        "labels": labels,
        "aliases": {
            "en": [
                {"language": "en", "value": "Woods"},
                {"language": "en", "value": "Woodland"},
            ],
            "de": [{"language": "de", "value": "Forst"}],
            "fr": [{"language": "fr", "value": "Bois"}],
            "it": [{"language": "it", "value": "Bosco"}],
        },
    }


def _write_manifest(path: Path, dump_path: Path, qids: tuple[str, ...]) -> None:
    manifest = {
        "schema_version": 1,
        "snapshot_version": 1,
        "created_at": "2026-08-23T00:00:00+00:00",
        "source": {
            "name": "Wikidata",
            "dump_uri": "https://dumps.wikimedia.org/wikidatawiki/entities/test.json",
            "dump_sha256": hashlib.sha256(dump_path.read_bytes()).hexdigest(),
            "license_id": "CC0-1.0",
        },
        "concepts": [
            {"qid": qid, "category": "subject"} for qid in qids
        ],
    }
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_wikidata_generator_json_array_emits_byte_identical_snapshot(
    tmp_path: Path,
) -> None:
    # Arrange
    dump_path = tmp_path / "wikidata.json"
    dump_path.write_text(
        json.dumps([_entity("Q999"), _entity("Q4421")], ensure_ascii=False),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, dump_path, ("Q4421",))
    first_path = tmp_path / "first.json.gz"
    second_path = tmp_path / "second.json.gz"
    generator = WikidataSnapshotGenerator()

    # Act
    first = generator.generate(manifest_path, dump_path, first_path)
    second = generator.generate(manifest_path, dump_path, second_path)

    # Assert
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first == second
    assert first.created_at == datetime(2026, 8, 23, tzinfo=UTC)
    assert tuple(concept.concept_id for concept in first.concepts) == (
        "wikidata:Q4421",
    )
    assert VocabularySnapshotRepository(first_path).load() == first


def test_wikidata_generator_json_lines_missing_qid_raises_error(
    tmp_path: Path,
) -> None:
    # Arrange
    dump_path = tmp_path / "wikidata.jsonl"
    dump_path.write_text(json.dumps(_entity("Q1")) + "\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, dump_path, ("Q2",))

    # Act / Assert
    with pytest.raises(WikidataGenerationError, match="missing QIDs: Q2"):
        WikidataSnapshotGenerator().generate(
            manifest_path, dump_path, tmp_path / "snapshot.json.gz"
        )


def test_wikidata_generator_deleted_qid_raises_error(tmp_path: Path) -> None:
    # Arrange
    dump_path = tmp_path / "wikidata.jsonl"
    dump_path.write_text(json.dumps({"id": "Q2", "deleted": True}), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, dump_path, ("Q2",))

    # Act / Assert
    with pytest.raises(WikidataGenerationError, match="deleted QID: Q2"):
        WikidataSnapshotGenerator().generate(
            manifest_path, dump_path, tmp_path / "snapshot.json.gz"
        )


def test_wikidata_generator_missing_required_language_raises_error(
    tmp_path: Path,
) -> None:
    # Arrange
    dump_path = tmp_path / "wikidata.jsonl"
    dump_path.write_text(
        json.dumps(_entity("Q4421", missing_locale="it")), encoding="utf-8"
    )
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, dump_path, ("Q4421",))

    # Act / Assert
    with pytest.raises(WikidataGenerationError, match="Q4421.*it"):
        WikidataSnapshotGenerator().generate(
            manifest_path, dump_path, tmp_path / "snapshot.json.gz"
        )


def test_wikidata_generator_redirect_to_earlier_entity_uses_canonical_qid(
    tmp_path: Path,
) -> None:
    # Arrange
    dump_path = tmp_path / "wikidata.jsonl"
    dump_path.write_text(
        "\n".join(
            (
                json.dumps(_entity("Q4421"), ensure_ascii=False),
                json.dumps({"id": "Q10", "redirect": {"to": "Q4421"}}),
            )
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, dump_path, ("Q10",))

    # Act
    snapshot = WikidataSnapshotGenerator().generate(
        manifest_path, dump_path, tmp_path / "snapshot.json.gz"
    )

    # Assert
    assert tuple(concept.concept_id for concept in snapshot.concepts) == (
        "wikidata:Q4421",
    )