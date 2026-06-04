from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image

from exif_turbo.config import ai_id_map_path, ai_index_path
from exif_turbo.data.ai_vector_repository import AiVectorRepository
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository
from exif_turbo.ui.workers.ai_scan_worker import AiScanWorker


def _make_jpeg(path: Path, size: tuple[int, int] = (256, 192)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "blue").save(path, "JPEG")


def _seed_db(db_path: Path, sources: list[Path]) -> int:
    folder_repo = IndexedFolderRepository(db_path, key="")
    folder = folder_repo.add(str(sources[0].parent))
    folder_repo.update_status(folder.id, "indexed", image_count=len(sources))
    folder_repo.close()

    repo = ImageIndexRepository(db_path, key="")
    for src in sources:
        st = src.stat()
        repo.upsert_image(
            str(src), src.name, st.st_mtime, st.st_size, {}, "",
            folder_id=folder.id,
        )
    repo.commit()
    repo.close()
    return folder.id


def _seed_ai_vectors(db_path: Path, paths: list[str]) -> None:
    repo = AiVectorRepository(ai_index_path(db_path), ai_id_map_path(db_path))
    repo.load()
    vec = np.ones((len(paths), 512), dtype=np.float32)
    vec /= np.linalg.norm(vec, axis=1, keepdims=True)
    repo.add_images(vec, paths)
    repo.save()


def _load_indexed_paths(db_path: Path) -> set[str]:
    repo = AiVectorRepository(ai_index_path(db_path), ai_id_map_path(db_path))
    repo.load()
    return repo.get_indexed_paths()


def _unique_db_path(tmp_path: Path) -> Path:
    return tmp_path / f"ai_scan_{uuid4().hex}.db"


class _FakeAiIndexerService:
    def __init__(
        self,
        vector_repo: AiVectorRepository,
        cache_dir: Path | None = None,
        *,
        preview_cache_dir: Path | None = None,
        preview_cache_key: str = "",
    ) -> None:
        self._repo = vector_repo
        self._preview_cache_dir = preview_cache_dir
        self._preview_cache_key = preview_cache_key

    def build_index(self, image_paths, on_progress=None, cancel_check=None):  # type: ignore[no-untyped-def]
        pending = [p for p in image_paths if p not in self._repo.get_indexed_paths()]
        if pending:
            vec = np.ones((len(pending), 512), dtype=np.float32)
            vec /= np.linalg.norm(vec, axis=1, keepdims=True)
            self._repo.add_images(vec, pending)
        if on_progress is not None:
            current = image_paths[-1] if image_paths else ""
            on_progress(len(image_paths), len(image_paths), current)
        return len(pending), 0


def test_ai_scan_worker_incremental_scan_keeps_existing_folder_vectors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    src_dir = tmp_path / "src"
    current = src_dir / "current.jpg"
    stale = src_dir / "stale.jpg"
    _make_jpeg(current)
    db_path = _unique_db_path(tmp_path)
    folder_id = _seed_db(db_path, [current])
    _seed_ai_vectors(db_path, [str(current), str(stale)])

    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_scan_worker.AiIndexerService",
        _FakeAiIndexerService,
    )

    worker = AiScanWorker(db_path, folder_id, str(src_dir), force_rebuild=False)

    # Act
    worker.run()

    # Assert
    assert _load_indexed_paths(db_path) == {str(current), str(stale)}


def test_ai_scan_worker_full_rescan_replaces_folder_vectors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Arrange
    src_dir = tmp_path / "src"
    current = src_dir / "current.jpg"
    stale = src_dir / "stale.jpg"
    _make_jpeg(current)
    db_path = _unique_db_path(tmp_path)
    folder_id = _seed_db(db_path, [current])
    _seed_ai_vectors(db_path, [str(current), str(stale)])

    monkeypatch.setattr(
        "exif_turbo.ui.workers.ai_scan_worker.AiIndexerService",
        _FakeAiIndexerService,
    )

    worker = AiScanWorker(db_path, folder_id, str(src_dir), force_rebuild=True)

    # Act
    worker.run()

    # Assert
    assert _load_indexed_paths(db_path) == {str(current)}