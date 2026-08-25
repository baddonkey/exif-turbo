from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exif_turbo.config import bundled_public_figure_vocabulary_path
from exif_turbo.models.vocabulary import REQUIRED_VOCABULARY_LOCALES
from exif_turbo.tagging.vocabulary_snapshot_repository import (
    VocabularySnapshotRepository,
)


def test_bundled_public_figures_match_manifest_and_required_locales() -> None:
    # Arrange
    repository_root = Path(__file__).parents[2]
    manifest_path = (
        repository_root / "assets" / "wikidata" / "public-figure-manifest-v1.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Act
    snapshot = VocabularySnapshotRepository(
        bundled_public_figure_vocabulary_path()
    ).load()

    # Assert
    assert len(snapshot.concepts) == len(manifest["concepts"]) == 9_119
    assert snapshot.source_dump_uri == "https://www.wikidata.org/w/api.php"
    assert snapshot.source_dump_sha256 == manifest["source"]["dump_sha256"]
    assert snapshot.manifest_sha256 == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert [
        {
            "qid": concept.concept_id.removeprefix("wikidata:"),
            "category": concept.category.value,
        }
        for concept in snapshot.concepts
    ] == manifest["concepts"]
    assert all(
        {terms.locale for terms in concept.localized_terms}
        == REQUIRED_VOCABULARY_LOCALES
        for concept in snapshot.concepts
    )