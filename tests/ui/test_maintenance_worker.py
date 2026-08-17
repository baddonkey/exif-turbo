"""Unit tests for MaintenanceWorker.

The worker's ``run()`` method is invoked directly (synchronously) so the
operation and its progress/cancelable/finished signals can be asserted
without spinning up a real QThread event loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from exif_turbo.config import tgm_snapshot_path
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.tagging.sidecar_repository import FilesystemSidecarRepository
from exif_turbo.ui.workers.maintenance_worker import MaintenanceWorker
from exif_turbo.utils.preview_cache import preview_cache_name_from_stamp, preview_dir


def _make_image(path: Path, color: tuple[int, int, int]) -> tuple[float, int]:
    Image.new("RGB", (8, 8), color=color).save(str(path), format="JPEG")
    stat = path.stat()
    return stat.st_mtime, stat.st_size


def _write_preview(cache_dir: Path, path: str, mtime: float, size: int) -> Path:
    pdir = preview_dir(cache_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    name = preview_cache_name_from_stamp(path, mtime, size)
    fpath = pdir / name
    fpath.write_bytes(b"preview")
    return fpath


@pytest.fixture
def folder_db(tmp_path: Path) -> tuple[Path, Path, int, str]:
    """DB with one indexed folder containing two images; returns ids + path."""
    db_path = tmp_path / "index.db"
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()

    folder_repo = IndexedFolderRepository(db_path, key="")
    folder = folder_repo.add(str(img_dir))
    folder_repo.close()

    repo = ImageIndexRepository(db_path, key="")
    for name, color in (("a.jpg", (200, 10, 10)), ("b.jpg", (10, 10, 200))):
        p = img_dir / name
        mtime, size = _make_image(p, color)
        repo.upsert_image(
            str(p), name, mtime, size, {"FileName": name}, name, folder_id=folder.id
        )
    repo.commit()
    repo.close()
    return db_path, img_dir, folder.id, str(img_dir)


def test_remove_folder_deletes_index_rows(
    qtbot: QtBot, folder_db: tuple[Path, Path, int, str], tmp_path: Path
) -> None:
    # Arrange
    db_path, _img_dir, folder_id, folder_path = folder_db
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    worker = MaintenanceWorker(
        db_path, "", "remove_folder",
        folder_id=folder_id, folder_path=folder_path, cache_dir=cache_dir,
    )
    finished: list[bool] = []
    worker.finished.connect(lambda: finished.append(True))

    # Act
    worker.run()

    # Assert
    repo = ImageIndexRepository(db_path, key="")
    img_count = repo.conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    repo.close()
    assert finished == [True]
    assert img_count == 0


def test_remove_folder_clears_cached_previews(
    qtbot: QtBot, folder_db: tuple[Path, Path, int, str], tmp_path: Path
) -> None:
    # Arrange
    db_path, img_dir, folder_id, folder_path = folder_db
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    repo = ImageIndexRepository(db_path, key="")
    stamps = repo.get_folder_stamps(folder_id)
    repo.close()
    preview_files = [
        _write_preview(cache_dir, p, m, s) for p, (m, s) in stamps.items()
    ]
    worker = MaintenanceWorker(
        db_path, "", "remove_folder",
        folder_id=folder_id, folder_path=folder_path, cache_dir=cache_dir,
    )

    # Act
    worker.run()

    # Assert
    assert all(not f.exists() for f in preview_files)


def test_reset_database_empties_index_and_folders(
    qtbot: QtBot, folder_db: tuple[Path, Path, int, str], tmp_path: Path
) -> None:
    # Arrange
    db_path, _img_dir, _folder_id, _folder_path = folder_db
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "junk.enc").write_bytes(b"x")
    worker = MaintenanceWorker(db_path, "", "reset_database", cache_dir=cache_dir)
    finished: list[bool] = []
    worker.finished.connect(lambda: finished.append(True))

    # Act
    worker.run()

    # Assert
    repo = ImageIndexRepository(db_path, key="")
    img_count = repo.conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    repo.close()
    folder_repo = IndexedFolderRepository(db_path, key="")
    folder_count = len(folder_repo.get_all())
    folder_repo.close()
    assert finished == [True]
    assert img_count == 0
    assert folder_count == 0
    assert not (cache_dir / "junk.enc").exists()


def test_reset_database_emits_vacuuming_substep(
    qtbot: QtBot, folder_db: tuple[Path, Path, int, str], tmp_path: Path
) -> None:
    # Arrange
    db_path, _img_dir, _folder_id, _folder_path = folder_db
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    worker = MaintenanceWorker(db_path, "", "reset_database", cache_dir=cache_dir)
    messages: list[str] = []
    worker.progress.connect(lambda _d, _t, msg: messages.append(msg))

    # Act
    worker.run()

    # Assert — a distinct vacuuming sub-step message is reported
    assert any("acuum" in m for m in messages)


def test_reset_database_flags_db_phase_not_cancelable(
    qtbot: QtBot, folder_db: tuple[Path, Path, int, str], tmp_path: Path
) -> None:
    # Arrange
    db_path, _img_dir, _folder_id, _folder_path = folder_db
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    worker = MaintenanceWorker(db_path, "", "reset_database", cache_dir=cache_dir)
    flags: list[bool] = []
    worker.cancelable.connect(lambda flag: flags.append(flag))

    # Act
    worker.run()

    # Assert — cache phase is cancelable (True) then the DB phase is not (False)
    assert flags == [True, False]


def test_reset_database_same_stem_preserves_other_database_tgm(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    # Arrange
    application_db = tmp_path / "application" / "index" / "index.db"
    temporary_db = tmp_path / "test-run" / "index.db"
    application_db.parent.mkdir(parents=True)
    temporary_db.parent.mkdir(parents=True)
    ImageIndexRepository(application_db, key="").close()
    ImageIndexRepository(temporary_db, key="").close()
    application_snapshot = tgm_snapshot_path(application_db)
    application_snapshot.parent.mkdir(parents=True)
    application_snapshot.write_bytes(b"persistent TGM")
    temporary_snapshot = tgm_snapshot_path(temporary_db)
    temporary_snapshot.parent.mkdir(parents=True)
    temporary_snapshot.write_bytes(b"temporary TGM")
    worker = MaintenanceWorker(temporary_db, "", "reset_database")

    # Act
    worker.run()

    # Assert
    assert application_snapshot.read_bytes() == b"persistent TGM"
    assert not temporary_snapshot.exists()


def test_refresh_sidecars_indexed_folder_updates_search_tags(
    qtbot: QtBot,
    folder_db: tuple[Path, Path, int, str],
) -> None:
    # Arrange
    db_path, image_dir, folder_id, _folder_path = folder_db
    image_path = image_dir / "a.jpg"
    sidecar = ImageSidecar(
        source=SidecarSource(filename=image_path.name),
        updated_at="2026-08-09T12:30:00Z",
        tags=(
            ImageTag(
                concept_id="loc-tgm:tgm000001",
                label="Mountain landscapes",
                category="subject",
                provenance=TagProvenance(
                    method="manual",
                    accepted_at="2026-08-09T12:30:00Z",
                    vocabulary_checksum="sha256:abc123",
                ),
            ),
        ),
        free_tags=("Travel",),
    )
    FilesystemSidecarRepository().write(
        image_path,
        sidecar,
        expected_revision=None,
    )
    worker = MaintenanceWorker(
        db_path,
        "",
        "refresh_sidecars",
        folder_id=folder_id,
    )
    finished: list[bool] = []
    progress: list[tuple[int, int]] = []
    worker.finished.connect(lambda: finished.append(True))
    worker.progress.connect(
        lambda done, total, _message: progress.append((done, total))
    )

    # Act
    worker.run()

    # Assert
    repo = ImageIndexRepository(db_path, key="")
    search_count = repo.count_images("Travel")
    repo.close()
    assert finished == [True]
    assert worker.sidecar_error_count == 0
    assert search_count == 1
    assert progress[0] == (0, 2)
    assert progress[-1] == (2, 2)


def test_refresh_sidecars_malformed_file_reports_error_and_finishes(
    qtbot: QtBot,
    folder_db: tuple[Path, Path, int, str],
) -> None:
    # Arrange
    db_path, image_dir, folder_id, _folder_path = folder_db
    sidecar_path = FilesystemSidecarRepository.sidecar_path(image_dir / "a.jpg")
    sidecar_path.write_text("{invalid JSON", encoding="utf-8")
    worker = MaintenanceWorker(
        db_path,
        "",
        "refresh_sidecars",
        folder_id=folder_id,
    )
    finished: list[bool] = []
    worker.finished.connect(lambda: finished.append(True))

    # Act
    worker.run()

    # Assert
    assert finished == [True]
    assert worker.sidecar_error_count == 1


def test_unknown_operation_emits_failed(qtbot: QtBot, tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "index.db"
    ImageIndexRepository(db_path, key="").close()
    worker = MaintenanceWorker(db_path, "", "bogus_op")
    errors: list[str] = []
    worker.failed.connect(lambda msg: errors.append(msg))

    # Act
    worker.run()

    # Assert
    assert len(errors) == 1
