from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.prepare_wikidata_public_figure_manifest import (
    PublicFigureManifestPreparer,
)


def test_public_figure_manifest_preparer_emits_snapshot_generator_input(
    tmp_path: Path,
) -> None:
    # Arrange
    discovery_path = tmp_path / "discovery.json"
    discovery_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "identity_snapshot_version": 3,
                "created_at": "2026-08-24T00:00:00+00:00",
                "complete": True,
                "concepts": [
                    {"qid": "Q43274", "identity_types": ["monarchs"]},
                    {"qid": "Q42", "identity_types": ["artists_writers"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    entities_path = tmp_path / "entities.jsonl"
    labels = {
        locale: {"language": locale, "value": f"name-{locale}"}
        for locale in ("de", "en", "fr", "it")
    }
    entities_path.write_text(
        json.dumps({"id": "Q42", "labels": labels})
        + "\n"
        + json.dumps({"id": "Q43274", "labels": labels})
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "manifest.json"

    # Act
    document = PublicFigureManifestPreparer().prepare(
        discovery_path,
        entities_path,
        output_path,
    )

    # Assert
    assert document["snapshot_version"] == 3
    assert document["source"]["name"] == "Wikidata public figures"
    assert document["source"]["dump_uri"] == "https://www.wikidata.org/w/api.php"
    assert document["source"]["dump_sha256"] == hashlib.sha256(
        entities_path.read_bytes()
    ).hexdigest()
    assert document["source"]["excluded_missing_required_labels"] == 0
    assert document["concepts"] == [
        {"qid": "Q42", "category": "subject"},
        {"qid": "Q43274", "category": "subject"},
    ]
    assert json.loads(output_path.read_text(encoding="utf-8")) == document


def test_public_figure_manifest_preparer_missing_required_label_excludes_qid(
    tmp_path: Path,
) -> None:
    # Arrange
    discovery_path = tmp_path / "discovery.json"
    discovery_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "identity_snapshot_version": 1,
                "created_at": "2026-08-24T00:00:00+00:00",
                "complete": True,
                "concepts": [{"qid": "Q2105"}, {"qid": "Q42"}],
            }
        ),
        encoding="utf-8",
    )
    complete_labels = {
        locale: {"language": locale, "value": f"name-{locale}"}
        for locale in ("de", "en", "fr", "it")
    }
    incomplete_labels = dict(complete_labels)
    del incomplete_labels["de"]
    entities_path = tmp_path / "entities.jsonl"
    entities_path.write_text(
        json.dumps({"id": "Q2105", "labels": incomplete_labels})
        + "\n"
        + json.dumps({"id": "Q42", "labels": complete_labels})
        + "\n",
        encoding="utf-8",
    )

    # Act
    document = PublicFigureManifestPreparer().prepare(
        discovery_path,
        entities_path,
        tmp_path / "manifest.json",
    )

    # Assert
    assert document["concepts"] == [{"qid": "Q42", "category": "subject"}]
    assert document["source"]["excluded_missing_required_labels"] == 1