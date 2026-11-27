from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from exif_turbo.data.ai_search_session import AiSearchSession
from exif_turbo.data.ai_vec1_repository import AiVec1Repository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository
from exif_turbo.ui.workers.ai_search_worker import AiSearchWorker
from tests.conftest import make_jpeg


@pytest.fixture(autouse=True)
def _fake_backend_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "exif_turbo.data.ai_search_session.bundled_vec1_extension", lambda: Path(".")
    )
    monkeypatch.setattr(
        "exif_turbo.data.ai_index_revision.AiIndexRevision.state",
        lambda _selector: ("vec1", 0),
    )


def _extension() -> Path:
    value = os.environ.get("EXIF_TURBO_VEC1_EXTENSION")
    if not value:
        pytest.skip("EXIF_TURBO_VEC1_EXTENSION is not configured")
    return Path(value)


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
    hits: ClassVar[list[tuple[str, float]]] = []
    last_top_k: int | None = None
    searches: int = 0

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def load(self) -> None:
        pass

    def close(self) -> None:
        pass

    def get_vector_count(self) -> int:
        return 1

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
        _FakeAiVectorRepository.searches += 1
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


def test_ai_search_worker_shared_session_returns_results_across_queries(
    tmp_path: Path, monkeypatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    directory = tmp_path / "photos"
    directory.mkdir()
    image = make_jpeg(directory / "photo.jpg")
    folder_id = _seed_folder(db_path, directory, enabled=True)
    _seed_image(db_path, image, folder_id, "Canon")
    extension = _extension()
    repository = AiVec1Repository(db_path, "", extension)
    repository.load()
    vector = np.ones(512, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    repository.add_images(vector, [str(image)])
    repository.save()
    repository.close()

    class FakeEncoder:
        def __init__(self, vector_repo: AiVec1Repository) -> None:
            pass

        def encode_text(self, text: str) -> np.ndarray:
            return vector

    monkeypatch.setattr("exif_turbo.ui.workers.ai_search_worker.AiIndexerService", FakeEncoder)
    session = AiSearchSession(db_path, extension_resolver=lambda: extension)
    emitted: list[list[tuple]] = []
    failures: list[str] = []

    # Act
    for serial in (1, 2):
        worker = AiSearchWorker(db_path, "", "photo", serial, session=session)
        worker.results_ready.connect(lambda rows, total, facets, serial: emitted.append(rows))
        worker.failed.connect(failures.append)
        worker.run()
    session.close()

    # Assert
    assert failures == []
    assert len(emitted) == 2
    assert emitted[0] == emitted[1]
    assert [row[1] for row in emitted[0]] == [str(image)]


def test_ai_search_worker_backend_changes_during_search_discards_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    directory = tmp_path / "photos"
    directory.mkdir()
    image = make_jpeg(directory / "photo.jpg")
    folder_id = _seed_folder(db_path, directory, enabled=True)
    _seed_image(db_path, image, folder_id, "Canon")
    extension = _extension()
    repository = AiVec1Repository(db_path, "", extension)
    repository.load()
    vector = np.ones(512, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    repository.add_images(vector, [str(image)])
    repository.save()
    repository.close()
    class ChangingEncoder:
        def __init__(self, vector_repo: AiVec1Repository) -> None:
            pass

        def encode_text(self, text: str) -> np.ndarray:
            changed = ImageIndexRepository(db_path, key="")
            try:
                with changed.conn:
                    changed.conn.execute("UPDATE ai_vector_backend SET revision = revision + 1")
            finally:
                changed.close()
            return vector

    monkeypatch.setattr("exif_turbo.ui.workers.ai_search_worker.AiIndexerService", ChangingEncoder)
    from exif_turbo.data._connection import open_encrypted_connection
    from exif_turbo.data.ai_index_revision import AiIndexRevision

    def state(selector: AiIndexRevision) -> tuple[str, int]:
        conn = open_encrypted_connection(db_path, "")
        try:
            row = conn.execute("SELECT active, revision FROM ai_vector_backend").fetchone()
            return (str(row[0]), int(row[1]))
        finally:
            conn.close()

    monkeypatch.setattr(AiIndexRevision, "state", state)
    session = AiSearchSession(db_path, extension_resolver=lambda: extension)
    worker = AiSearchWorker(db_path, "", "photo", 1, session=session)
    emitted: list[list[tuple]] = []
    failures: list[str] = []
    worker.results_ready.connect(lambda rows, total, facets, serial: emitted.append(rows))
    worker.failed.connect(failures.append)

    # Act
    worker.run()
    session.close()

    # Assert
    assert emitted == []
    assert failures == ["AI index changed during search; retry the search"]


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
        "exif_turbo.data.ai_search_session.AiVec1Repository",
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
        "exif_turbo.data.ai_search_session.AiVec1Repository",
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


def test_ai_search_worker_applies_image_set_filter_to_hits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    directory = tmp_path / "photos"
    directory.mkdir()
    member_path = make_jpeg(directory / "member.jpg")
    other_path = make_jpeg(directory / "other.jpg")
    folder_id = _seed_folder(db_path, directory, enabled=True)
    _seed_image(db_path, member_path, folder_id, "Canon")
    _seed_image(db_path, other_path, folder_id, "Nikon")
    image_repository = ImageIndexRepository(db_path, key="")
    set_id = image_repository.create_image_set("AI scope")
    image_repository.add_images_to_set(set_id, [str(member_path)])
    image_repository.close()

    _FakeAiVectorRepository.hits = [
        (str(other_path), 0.95),
        (str(member_path), 0.90),
    ]
    monkeypatch.setattr(
        "exif_turbo.data.ai_search_session.AiVec1Repository",
        _FakeAiVectorRepository,
    )
    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_search_worker.AiIndexerService",
        _FakeAiIndexerService,
    )
    emitted: list[tuple[list[tuple], int, list, int]] = []
    failures: list[str] = []
    worker = AiSearchWorker(db_path, "", "animal", 10, image_set_id=set_id)
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
    assert serial == 10
    assert [row[1] for row in rows] == [str(member_path)]


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
        "exif_turbo.data.ai_search_session.AiVec1Repository",
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
        "exif_turbo.data.ai_search_session.AiVec1Repository",
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


def test_ai_search_worker_date_filter_keeps_facet_paths_for_all_years(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange — two semantic hits in different years; date filter covers 2024 only
    db_path = tmp_path / "test.db"
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()

    path_2024 = make_jpeg(gallery_dir / "photo_2024.jpg")
    path_2025 = make_jpeg(gallery_dir / "photo_2025.jpg")

    folder_id = _seed_folder(db_path, gallery_dir, enabled=True)
    _seed_image(
        db_path, path_2024, folder_id, "Canon", captured_at=1704067200.0
    )  # 2024-01-01T00:00:00Z
    _seed_image(
        db_path, path_2025, folder_id, "Canon", captured_at=1735689600.0
    )  # 2025-01-01T00:00:00Z

    _FakeAiVectorRepository.hits = [
        (str(path_2025), 0.96),
        (str(path_2024), 0.95),
    ]
    monkeypatch.setattr(
        "exif_turbo.data.ai_search_session.AiVec1Repository",
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
        23,
        date_from=1704067200,
        date_to=1735603199,  # just before 2025-01-01T00:00:00Z
    )
    worker.results_ready.connect(
        lambda rows, total, format_counts, serial: emitted.append(
            (rows, total, format_counts, serial)
        )
    )
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert — displayed rows honour the date filter, but the timeline facet
    # source keeps every semantic year so the histogram does not collapse.
    assert failures == []
    rows = emitted[0][0]
    assert [row[1] for row in rows] == [str(path_2024)]
    assert set(worker.facet_paths) == {str(path_2024), str(path_2025)}


@pytest.mark.parametrize("date_filter_enabled", [True, False])
def test_ai_search_worker_date_eligibility_precedes_cap_and_facets_are_uncapped(
    tmp_path: Path, monkeypatch, date_filter_enabled: bool,
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    directory = tmp_path / "photos"
    directory.mkdir()
    folder_id = _seed_folder(db_path, directory, enabled=True)
    outside_paths = [str(directory / f"outside_{number}.jpg") for number in range(2001)]
    target = str(directory / "eligible.jpg")
    repository = ImageIndexRepository(db_path, key="")
    for path in outside_paths:
        repository.upsert_image(path, Path(path).name, 1.0, 10, {}, "",
                                folder_id=folder_id, captured_at=1735689600.0)
    repository.upsert_image(target, "eligible.jpg", 1.0, 10, {}, "",
                            folder_id=folder_id, captured_at=1704067200.0)
    repository.commit()
    repository.close()
    _FakeAiVectorRepository.hits = [(path, 0.9) for path in outside_paths] + [(target, 0.8)]
    monkeypatch.setattr("exif_turbo.data.ai_search_session.AiVec1Repository", _FakeAiVectorRepository)
    monkeypatch.setattr("exif_turbo.ui.workers.ai_search_worker.AiIndexerService", _FakeAiIndexerService)
    worker = AiSearchWorker(db_path, "", "photo", 31,
                            date_from=1704067200 if date_filter_enabled else None,
                            date_to=1735689599 if date_filter_enabled else None)
    emitted: list[list[tuple]] = []
    failures: list[str] = []
    worker.results_ready.connect(lambda rows, total, facets, serial: emitted.append(rows))
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    expected = [target] if date_filter_enabled else outside_paths[:2000]
    assert [row[1] for row in emitted[0]] == expected
    assert set(worker.facet_paths) == set(outside_paths) | {target}


@pytest.mark.parametrize("query", ["photo", ""])
@pytest.mark.parametrize(
    "date_from,date_to,expected_names",
    [
        (1704067200, 1704067300, {"start.jpg", "end.jpg"}),
        (1704067200, None, {"start.jpg", "end.jpg", "after.jpg"}),
        (None, 1704067300, {"before.jpg", "start.jpg", "end.jpg"}),
    ],
)
def test_ai_search_worker_date_boundaries_and_open_ranges_preserve_facets(
    tmp_path: Path, monkeypatch, query: str,
    date_from: int | None, date_to: int | None, expected_names: set[str],
) -> None:
    # Arrange
    db_path = tmp_path / "test.db"
    directory = tmp_path / "photos"
    directory.mkdir()
    folder_id = _seed_folder(db_path, directory, enabled=True)
    repository = ImageIndexRepository(db_path, key="")
    names = ["before.jpg", "start.jpg", "end.jpg", "after.jpg", "unknown.jpg"]
    dates = [1704067199.0, 1704067200.0, 1704067300.0, 1704067301.0, None]
    paths = [str(directory / name) for name in names]
    for path, date in zip(paths, dates):
        repository.upsert_image(path, Path(path).name, 1.0, 10, {}, "",
                                folder_id=folder_id, captured_at=date)
    repository.commit()
    repository.close()
    _FakeAiVectorRepository.hits = [(path, 0.9) for path in paths]
    monkeypatch.setattr("exif_turbo.data.ai_search_session.AiVec1Repository", _FakeAiVectorRepository)
    monkeypatch.setattr("exif_turbo.ui.workers.ai_search_worker.AiIndexerService", _FakeAiIndexerService)
    worker = AiSearchWorker(db_path, "", query, 32, date_from=date_from, date_to=date_to)
    emitted: list[list[tuple]] = []
    failures: list[str] = []
    worker.results_ready.connect(lambda rows, total, facets, serial: emitted.append(rows))
    worker.failed.connect(failures.append)

    # Act
    worker.run()

    # Assert
    assert failures == []
    assert {Path(row[1]).name for row in emitted[0]} == expected_names
    assert set(worker.facet_paths) == set(paths)


def test_ai_search_worker_computes_facet_and_display_hits_once(
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
    _FakeAiVectorRepository.searches = 0
    monkeypatch.setattr(
        "exif_turbo.data.ai_search_session.AiVec1Repository",
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
    assert _FakeAiVectorRepository.last_top_k is None
    assert _FakeAiVectorRepository.searches == 1


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
        "exif_turbo.data.ai_search_session.AiVec1Repository",
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