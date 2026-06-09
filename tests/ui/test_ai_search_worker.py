from __future__ import annotations

from pathlib import Path

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository
from exif_turbo.ui.workers.ai_search_worker import AiSearchWorker
from tests.conftest import make_jpeg


def _seed_folder(db_path: Path, folder_path: Path, *, enabled: bool) -> int:
    folder_repo = IndexedFolderRepository(db_path, key="")
    folder = folder_repo.add(str(folder_path))
    folder_repo.update_status(folder.id, "indexed", image_count=1)
    if not enabled:
        folder_repo.set_enabled(folder.id, enabled=False)
    folder_repo.close()
    return folder.id


def _seed_image(
    db_path: Path,
    image_path: Path,
    folder_id: int,
    camera_make: str,
    *,
    captured_at: float | None = None,
) -> None:
    repo = ImageIndexRepository(db_path, key="")
    stat = image_path.stat()
    repo.upsert_image(
        str(image_path),
        image_path.name,
        stat.st_mtime,
        stat.st_size,
        {"Make": camera_make},
        f"{camera_make} {image_path.name}",
        folder_id=folder_id,
        captured_at=captured_at,
    )
    repo.commit()
    repo.close()


class _FakeAiVectorRepository:
    hits: list[tuple[str, float]] = []
    last_top_k: int | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def load(self) -> None:
        pass

    def search(self, _query_vec, top_k: int = 800, threshold: float = 0.20):  # type: ignore[no-untyped-def]
        return [hit for hit in self.hits if hit[1] >= threshold][:top_k]

    def search_filtered(  # type: ignore[no-untyped-def]
        self,
        _query_vec,
        allowed_paths,
        *,
        top_k: int | None = 800,
        threshold: float = 0.20,
    ):
        _FakeAiVectorRepository.last_top_k = top_k
        filtered = [
            hit for hit in self.hits
            if hit[1] >= threshold and hit[0] in allowed_paths
        ]
        return filtered[:top_k]


class _FakeAiIndexerService:
    def __init__(self, _vector_repo) -> None:  # type: ignore[no-untyped-def]
        pass

    def encode_text(self, _query_text: str) -> object:
        return object()


def test_ai_search_worker_excludes_disabled_folder_hits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    enabled_dir = tmp_path / "enabled"
    disabled_dir = tmp_path / "disabled"
    enabled_dir.mkdir()
    disabled_dir.mkdir()

    enabled_path = make_jpeg(enabled_dir / "enabled.jpg")
    disabled_path = make_jpeg(disabled_dir / "disabled.jpg")

    enabled_folder_id = _seed_folder(db_path, enabled_dir, enabled=True)
    disabled_folder_id = _seed_folder(db_path, disabled_dir, enabled=False)
    _seed_image(db_path, enabled_path, enabled_folder_id, "Canon")
    _seed_image(db_path, disabled_path, disabled_folder_id, "Nikon")

    _FakeAiVectorRepository.hits = [
        (str(disabled_path), 0.95),
        (str(enabled_path), 0.90),
    ]
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiVectorRepository",
        _FakeAiVectorRepository,
    )
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiIndexerService",
        _FakeAiIndexerService,
    )

    emitted: list[tuple[list[tuple[int, str, str, str, int, float]], int, list, int]] = []
    failures: list[str] = []
    worker = AiSearchWorker(db_path, "", "tree", 7)
    worker.results_ready.connect(
        lambda rows, total, format_counts, serial: emitted.append(
            (rows, total, format_counts, serial)
        )
    )
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert len(emitted) == 1
    rows, total, format_counts, serial = emitted[0]
    assert total == 1
    assert format_counts == []
    assert serial == 7
    assert [row[1] for row in rows] == [str(enabled_path)]


def test_ai_search_worker_applies_path_filter_to_hits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    alpha_dir = tmp_path / "alpha"
    beta_dir = tmp_path / "beta"
    alpha_dir.mkdir()
    beta_dir.mkdir()

    alpha_path = make_jpeg(alpha_dir / "alpha.jpg")
    beta_path = make_jpeg(beta_dir / "beta.jpg")

    alpha_folder_id = _seed_folder(db_path, alpha_dir, enabled=True)
    beta_folder_id = _seed_folder(db_path, beta_dir, enabled=True)
    _seed_image(db_path, alpha_path, alpha_folder_id, "Canon")
    _seed_image(db_path, beta_path, beta_folder_id, "Nikon")

    _FakeAiVectorRepository.hits = [
        (str(beta_path), 0.95),
        (str(alpha_path), 0.90),
    ]
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiVectorRepository",
        _FakeAiVectorRepository,
    )
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiIndexerService",
        _FakeAiIndexerService,
    )

    emitted: list[tuple[list[tuple[int, str, str, str, int, float]], int, list, int]] = []
    failures: list[str] = []
    worker = AiSearchWorker(
        db_path,
        "",
        "tree",
        9,
        path_filter=[str(beta_dir)],
    )
    worker.results_ready.connect(
        lambda rows, total, format_counts, serial: emitted.append(
            (rows, total, format_counts, serial)
        )
    )
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert len(emitted) == 1
    rows, total, format_counts, serial = emitted[0]
    assert total == 1
    assert format_counts == []
    assert serial == 9
    assert [row[1] for row in rows] == [str(beta_path)]


def test_ai_search_worker_filters_before_candidate_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    alpha_dir = tmp_path / "alpha"
    beta_dir = tmp_path / "beta"
    alpha_dir.mkdir()
    beta_dir.mkdir()

    allowed_path = make_jpeg(beta_dir / "allowed.jpg")
    beta_folder_id = _seed_folder(db_path, beta_dir, enabled=True)
    _seed_image(db_path, allowed_path, beta_folder_id, "Nikon")

    disabled_paths: list[str] = []
    disabled_dir = tmp_path / "disabled"
    disabled_dir.mkdir()
    disabled_folder_id = _seed_folder(db_path, disabled_dir, enabled=False)
    for idx in range(800):
        path = make_jpeg(disabled_dir / f"disabled_{idx}.jpg")
        disabled_paths.append(str(path))
        _seed_image(db_path, path, disabled_folder_id, "Canon")

    _FakeAiVectorRepository.hits = [
        *[(path, 0.99 - (idx * 0.0001)) for idx, path in enumerate(disabled_paths)],
        (str(allowed_path), 0.80),
    ]
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiVectorRepository",
        _FakeAiVectorRepository,
    )
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiIndexerService",
        _FakeAiIndexerService,
    )

    emitted: list[tuple[list[tuple[int, str, str, str, int, float]], int, list, int]] = []
    failures: list[str] = []
    worker = AiSearchWorker(db_path, "", "tree", 11, path_filter=[str(beta_dir)])
    worker.results_ready.connect(
        lambda rows, total, format_counts, serial: emitted.append(
            (rows, total, format_counts, serial)
        )
    )
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert len(emitted) == 1
    rows, total, format_counts, serial = emitted[0]
    assert total == 1
    assert format_counts == []
    assert serial == 11
    assert [row[1] for row in rows] == [str(allowed_path)]


def test_ai_search_worker_applies_ext_and_date_filters_to_hits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()

    jpg_path = make_jpeg(gallery_dir / "photo_2024.jpg")
    png_path = make_jpeg(gallery_dir / "photo_2025.png")

    gallery_folder_id = _seed_folder(db_path, gallery_dir, enabled=True)
    _seed_image(
        db_path,
        jpg_path,
        gallery_folder_id,
        "Canon",
        captured_at=1704067200.0,  # 2024-01-01T00:00:00Z
    )
    _seed_image(
        db_path,
        png_path,
        gallery_folder_id,
        "Canon",
        captured_at=1735689600.0,  # 2025-01-01T00:00:00Z
    )

    _FakeAiVectorRepository.hits = [
        (str(png_path), 0.96),
        (str(jpg_path), 0.95),
    ]
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiVectorRepository",
        _FakeAiVectorRepository,
    )
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiIndexerService",
        _FakeAiIndexerService,
    )

    emitted: list[tuple[list[tuple[int, str, str, str, int, float]], int, list, int]] = []
    failures: list[str] = []
    worker = AiSearchWorker(
        db_path,
        "",
        "landscape",
        13,
        ext_filter="jpg",
        date_from=1704067200,
        date_to=1735603199,
    )
    worker.results_ready.connect(
        lambda rows, total, format_counts, serial: emitted.append(
            (rows, total, format_counts, serial)
        )
    )
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert len(emitted) == 1
    rows, total, format_counts, serial = emitted[0]
    assert total == 1
    assert format_counts == []
    assert serial == 13
    assert [row[1] for row in rows] == [str(jpg_path)]


def test_ai_search_worker_calls_vector_search_with_2000_result_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()

    img_path = make_jpeg(gallery_dir / "photo.jpg")
    folder_id = _seed_folder(db_path, gallery_dir, enabled=True)
    _seed_image(db_path, img_path, folder_id, "Canon")

    _FakeAiVectorRepository.hits = [(str(img_path), 0.91)]
    _FakeAiVectorRepository.last_top_k = 800
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiVectorRepository",
        _FakeAiVectorRepository,
    )
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiIndexerService",
        _FakeAiIndexerService,
    )

    emitted: list[tuple[list[tuple[int, str, str, str, int, float]], int, list, int]] = []
    failures: list[str] = []
    worker = AiSearchWorker(db_path, "", "landscape", 17)
    worker.results_ready.connect(
        lambda rows, total, format_counts, serial: emitted.append(
            (rows, total, format_counts, serial)
        )
    )
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert len(emitted) == 1
    assert _FakeAiVectorRepository.last_top_k == 2000


def test_ai_search_worker_empty_query_returns_all_allowed_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    alpha_dir = tmp_path / "alpha"
    beta_dir = tmp_path / "beta"
    alpha_dir.mkdir()
    beta_dir.mkdir()

    alpha_path = make_jpeg(alpha_dir / "alpha.jpg")
    beta_path = make_jpeg(beta_dir / "beta.jpg")

    alpha_folder_id = _seed_folder(db_path, alpha_dir, enabled=True)
    beta_folder_id = _seed_folder(db_path, beta_dir, enabled=True)
    _seed_image(db_path, alpha_path, alpha_folder_id, "Canon")
    _seed_image(db_path, beta_path, beta_folder_id, "Nikon")

    _FakeAiVectorRepository.hits = []
    _FakeAiVectorRepository.last_top_k = 800
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiVectorRepository",
        _FakeAiVectorRepository,
    )
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiIndexerService",
        _FakeAiIndexerService,
    )

    emitted: list[tuple[list[tuple[int, str, str, str, int, float]], int, list, int]] = []
    failures: list[str] = []
    worker = AiSearchWorker(db_path, "", "   ", 19)
    worker.results_ready.connect(
        lambda rows, total, format_counts, serial: emitted.append(
            (rows, total, format_counts, serial)
        )
    )
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert len(emitted) == 1
    rows, total, format_counts, serial = emitted[0]
    assert total == 2
    assert format_counts == []
    assert serial == 19
    assert {row[1] for row in rows} == {str(alpha_path), str(beta_path)}
    assert _FakeAiVectorRepository.last_top_k == 800