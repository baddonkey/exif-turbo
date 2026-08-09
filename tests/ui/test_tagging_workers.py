from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from exif_turbo.ui.workers import bulk_tag_worker as bulk_module
from exif_turbo.ui.workers import tgm_proposal_worker as proposal_module
from exif_turbo.ui.workers import tgm_update_worker as update_module
from exif_turbo.ui.workers import tgm_vector_build_worker as vector_module
from exif_turbo.ui.workers.bulk_tag_worker import BulkTagWorker
from exif_turbo.ui.workers.tgm_proposal_worker import TgmProposalWorker
from exif_turbo.ui.workers.tgm_update_worker import TgmUpdateWorker
from exif_turbo.ui.workers.tgm_vector_build_worker import TgmVectorBuildWorker
from exif_turbo.ui.workers import maintenance_worker as maintenance_module
from exif_turbo.ui.workers.maintenance_worker import MaintenanceWorker


class FakeRepository:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.closed = False

    def load(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_tgm_update_worker_canceled_before_run_emits_canceled(tmp_path: Path) -> None:
    # Arrange
    worker = TgmUpdateWorker(tmp_path / "images.db", "")
    canceled: list[bool] = []
    worker.canceled.connect(lambda: canceled.append(True))

    # Act
    worker.cancel()
    worker.run()

    # Assert
    assert canceled == [True]


def test_tgm_vector_build_worker_fake_service_emits_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    class FakeVectorService:
        def __init__(self, *args: object) -> None:
            pass

        def build(self, *, on_progress: object, cancel_check: object) -> object:
            on_progress(1, 1, "Forests")  # type: ignore[operator]
            return SimpleNamespace(completed=True, concept_count=1)

    monkeypatch.setattr(vector_module, "AiVectorRepository", FakeRepository)
    monkeypatch.setattr(vector_module, "TgmVectorRepository", FakeRepository)
    monkeypatch.setattr(vector_module, "TgmSnapshotRepository", FakeRepository)
    monkeypatch.setattr(vector_module, "AiIndexerService", FakeRepository)
    monkeypatch.setattr(vector_module, "TgmVectorIndexService", FakeVectorService)
    worker = TgmVectorBuildWorker(tmp_path / "images.db")
    progress: list[tuple[int, int]] = []
    results: list[object] = []
    worker.progress.connect(lambda done, total, _label: progress.append((done, total)))
    worker.result_ready.connect(results.append)

    # Act
    worker.run()

    # Assert
    assert progress == [(1, 1)]
    assert len(results) == 1


def test_tgm_proposal_worker_repository_error_emits_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    class FailingImageVectors:
        def __init__(self, *args: object) -> None:
            raise RuntimeError("vector index unavailable")

    monkeypatch.setattr(proposal_module, "ImageIndexRepository", FakeRepository)
    monkeypatch.setattr(proposal_module, "TgmSnapshotRepository", FakeRepository)
    monkeypatch.setattr(proposal_module, "AiVectorRepository", FailingImageVectors)
    worker = TgmProposalWorker(
        tmp_path / "images.db",
        "",
        ["/photos/photo.jpg"],
        threshold=0.24,
    )
    failures: list[str] = []
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == ["vector index unavailable"]


def test_bulk_tag_worker_fake_service_emits_result_and_closes_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    repositories: list[FakeRepository] = []

    class TrackingRepository(FakeRepository):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            repositories.append(self)

    result = SimpleNamespace(cancelled=False, succeeded_count=1)

    class FakeTaggingService:
        def __init__(self, *args: object) -> None:
            pass

        def add_concept_to_marked(self, *args: object, **kwargs: object) -> object:
            return result

    monkeypatch.setattr(bulk_module, "ImageIndexRepository", TrackingRepository)
    monkeypatch.setattr(bulk_module, "TaggingService", FakeTaggingService)
    monkeypatch.setattr(bulk_module, "TgmSnapshotRepository", FakeRepository)
    worker = BulkTagWorker(
        tmp_path / "images.db", "", "add", "loc-tgm:tgm000001"
    )
    results: list[object] = []
    worker.result_ready.connect(results.append)

    # Act
    worker.run()

    # Assert
    assert results == [result]
    assert repositories[0].closed is True


def test_maintenance_reset_removes_tgm_derivatives_and_preserves_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    db_path = tmp_path / "images.db"
    repository = maintenance_module.ImageIndexRepository(db_path)
    repository.close()
    tgm_dir = tmp_path / "tgm"
    tgm_dir.mkdir()
    (tgm_dir / "tgm-snapshot.json.gz").write_bytes(b"derived")
    sidecar = tmp_path / "photo.jpg.sidecar.json"
    sidecar.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        maintenance_module,
        "tgm_snapshot_path",
        lambda _db: tgm_dir / "tgm-snapshot.json.gz",
    )
    worker = MaintenanceWorker(db_path, "", "reset_database")
    finished: list[bool] = []
    worker.finished.connect(lambda: finished.append(True))

    # Act
    worker.run()

    # Assert
    assert finished == [True]
    assert not tgm_dir.exists()
    assert sidecar.exists()