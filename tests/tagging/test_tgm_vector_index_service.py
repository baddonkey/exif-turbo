from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from exif_turbo.data.tgm_vector_repository import TgmVectorRepository
from exif_turbo.models.tgm import TgmCategory, TgmConcept, TgmSnapshot, TgmSourceFormat
from exif_turbo.tagging.tgm_prompt_builder import TgmPromptBuilder
from exif_turbo.tagging.tgm_snapshot_repository import TgmSnapshotRepository
from exif_turbo.tagging.tgm_vector_index_service import TgmVectorIndexService


def _concept(number: int, label: str, **kwargs: object) -> TgmConcept:
    return TgmConcept(
        concept_id=f"loc-tgm:tgm{number:06d}",
        tnr=f"tgm{number:06d}",
        label=label,
        categories=(TgmCategory.SUBJECT,),
        **kwargs,
    )


def _snapshot(checksum: str = "snapshot-a") -> TgmSnapshot:
    return TgmSnapshot(
        concepts=(_concept(1, "Forests"), _concept(2, "Deer")),
        diagnostics=(),
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        distribution_date=None,
        imported_at=datetime(2026, 8, 9, tzinfo=UTC),
        raw_sha256=checksum,
        raw_size_bytes=100,
    )


class _FakeEncoder:
    def encode_texts(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        vectors = np.zeros((len(texts), 512), dtype=np.float32)
        for index in range(len(texts)):
            vectors[index, index % 512] = 1.0
        return vectors


def _service(tmp_path: Path, checksum: str = "snapshot-a") -> tuple[
    TgmVectorIndexService, TgmVectorRepository, TgmSnapshotRepository
]:
    snapshots = TgmSnapshotRepository(tmp_path / "snapshot.json.gz")
    snapshots.activate(_snapshot(checksum))
    vectors = TgmVectorRepository(
        tmp_path / "terms.faiss",
        tmp_path / "concepts.json",
        tmp_path / "metadata.json",
    )
    vectors.load()
    service = TgmVectorIndexService(snapshots, vectors, _FakeEncoder())  # type: ignore[arg-type]
    return service, vectors, snapshots


def test_tgm_prompt_builder_uses_label_aliases_and_excludes_private_notes() -> None:
    # Arrange
    concept = _concept(
        1,
        "Forests",
        aliases=("Woods",),
        cataloger_notes=("private cataloger note",),
        history_notes=("private history note",),
    )

    # Act
    prompt = TgmPromptBuilder().build(concept)

    # Assert
    assert prompt == "A photograph depicting Forests; also known as Woods."
    assert "cataloger" not in prompt
    assert "history" not in prompt


def test_tgm_vector_index_service_fingerprint_detects_stale_snapshot(
    tmp_path: Path,
) -> None:
    # Arrange
    service, vectors, snapshots = _service(tmp_path)
    service.build(batch_size=1)
    snapshots.activate(_snapshot("snapshot-b"))

    # Act / Assert
    assert vectors.count == 2
    assert service.is_current() is False


def test_tgm_vector_index_service_cancellation_keeps_old_active_index(
    tmp_path: Path,
) -> None:
    # Arrange
    service, vectors, snapshots = _service(tmp_path)
    service.build(batch_size=1)
    old_fingerprint = vectors.fingerprint
    snapshots.activate(_snapshot("snapshot-b"))
    calls = 0

    def _cancel_after_first_batch() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    # Act
    result = service.build(batch_size=1, cancel_check=_cancel_after_first_batch)

    # Assert
    assert result.completed is False
    assert vectors.fingerprint == old_fingerprint