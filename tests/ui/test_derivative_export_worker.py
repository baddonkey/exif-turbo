from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.ui.workers.derivative_export_worker import DerivativeExportWorker


class FakeMetadataWriter:
    def write_keywords(
        self,
        target: Path,
        labels: Sequence[str],
        *,
        forbidden_sources: Iterable[Path] = (),
    ) -> None:
        target.write_bytes(target.read_bytes() + b"-tagged")


def test_derivative_export_worker_emits_result_and_progress(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "images.db"
    source_root = tmp_path / "source"
    source_root.mkdir()
    image_path = source_root / "photo.jpg"
    image_path.write_bytes(b"original")
    repository = ImageIndexRepository(db_path)
    repository.upsert_image(
        str(image_path), image_path.name, image_path.stat().st_mtime, image_path.stat().st_size, {}, ""
    )
    repository.replace_accepted_tags_and_sidecar_state(
        str(image_path),
        ImageSidecar(
            source=SidecarSource(filename=image_path.name),
            updated_at="2026-08-09T12:00:00Z",
            tags=(
                ImageTag(
                    concept_id="loc-tgm:tgm000001",
                    label="Deer",
                    category="subject",
                    provenance=TagProvenance(
                        method="manual",
                        accepted_at="2026-08-09T12:00:00Z",
                        vocabulary_checksum="sha256:tgm",
                    ),
                ),
            ),
        ),
        sidecar_path=f"{image_path}.sidecar.json",
        sidecar_mtime_ns=1,
        sidecar_size=1,
        sidecar_checksum="sha256:test",
        sync_status="synced",
    )
    repository.close()
    worker = DerivativeExportWorker(
        db_path,
        "",
        {source_root: "source"},
        tmp_path / "output",
        image_paths=[image_path],
        metadata_writer=FakeMetadataWriter(),
    )
    progress: list[tuple[int, int]] = []
    results: list[object] = []
    failures: list[str] = []
    worker.progress.connect(lambda done, total, _item: progress.append((done, total)))
    worker.result_ready.connect(results.append)
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert progress == [(1, 1)]
    assert results == [worker.result]
    assert failures == []
    assert worker.result is not None
    assert worker.result.copied_count == 1
    assert (tmp_path / "output" / "photo.jpg").read_bytes() == b"original-tagged"