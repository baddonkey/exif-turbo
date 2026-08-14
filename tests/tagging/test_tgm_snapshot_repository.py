from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from exif_turbo.models.tgm import TgmCategory, TgmSourceFormat
from exif_turbo.tagging.tgm_importer import TgmImporter, TgmImportError
from exif_turbo.tagging.tgm_snapshot_repository import TgmSnapshotRepository


def _snapshot() -> object:
    raw = b"""<THESAURUS>
      <CONCEPT><DESCRIPTOR>Sunlight</DESCRIPTOR><UF>Sun rays</UF><TNR>tgm000001</TNR><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
      <CONCEPT><DESCRIPTOR>Posters</DESCRIPTOR><TNR>tgm000002</TNR><TTCForm>MARC 155/655</TTCForm></CONCEPT>
    </THESAURUS>"""
    return TgmImporter().import_bytes(
        raw,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        imported_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )


def test_tgm_snapshot_repository_activate_and_load_round_trips_snapshot(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = TgmSnapshotRepository(tmp_path / "tgm-snapshot.json.gz")
    snapshot = _snapshot()

    # Act
    repository.activate(snapshot)
    loaded = repository.load()

    # Assert
    assert loaded == snapshot
    assert repository.counts() == {
        TgmCategory.SUBJECT: 1,
        TgmCategory.GENRE_FORMAT: 1,
    }
    assert repository.metadata().raw_sha256 == snapshot.raw_sha256
    assert repository.metadata().raw_size_bytes > 0


def test_tgm_snapshot_repository_lookup_and_search_resolve_aliases(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = TgmSnapshotRepository(tmp_path / "tgm-snapshot.json.gz")
    repository.activate(_snapshot())

    # Act
    by_id = repository.get("loc-tgm:tgm000001")
    by_alias = repository.resolve_label("SUN RAYS")
    results = repository.search("rays")

    # Assert
    assert by_id is not None
    assert by_alias == by_id
    assert results == (by_id,)
    assert repository.list_selectable() == repository.load().concepts


def test_tgm_snapshot_repository_failed_candidate_preserves_active_snapshot(
    tmp_path: Path,
) -> None:
    # Arrange
    repository = TgmSnapshotRepository(tmp_path / "tgm-snapshot.json.gz")
    original = _snapshot()
    repository.activate(original)
    invalid = b"""<THESAURUS>
      <CONCEPT><DESCRIPTOR>First</DESCRIPTOR><TNR>tgm000001</TNR><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
      <CONCEPT><DESCRIPTOR>Second</DESCRIPTOR><TNR>tgm000001</TNR><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
    </THESAURUS>"""

    # Act / Assert
    with pytest.raises(TgmImportError):
        candidate = TgmImporter().import_bytes(
            invalid,
            source_url="https://example.test/tgm.xml",
            source_format=TgmSourceFormat.XML,
            imported_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )
        repository.activate(candidate)
    assert repository.load() == original