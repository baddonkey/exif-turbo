from __future__ import annotations

import time
from pathlib import Path

import pytest  # noqa: F401  — used implicitly via qtbot
from PIL import Image
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository
from exif_turbo.ui.workers.preview_build_worker import PreviewBuildWorker
from exif_turbo.utils.preview_cache import preview_cache_name_from_stamp, preview_dir


def _make_jpeg(path: Path, size: tuple[int, int] = (256, 192)) -> None:
    Image.new("RGB", size, "blue").save(path, "JPEG")


def _seed_db(db_path: Path, sources: list[Path]) -> int:
    """Index the given files into a fresh DB and return the folder_id."""
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


def test_preview_worker_renders_jpeg_for_each_indexed_image(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sources = [src_dir / f"img{i}.jpg" for i in range(3)]
    for s in sources:
        _make_jpeg(s)
    db = tmp_path / "test.db"
    cache = tmp_path / "cache"
    folder_id = _seed_db(db, sources)

    worker = PreviewBuildWorker(db, cache, folder_id, target_long_edge=128)

    # Act
    with qtbot.waitSignal(worker.finished, timeout=10_000):
        worker.start()

    # Assert
    out_dir = preview_dir(cache)
    assert out_dir.exists()
    for s in sources:
        st = s.stat()
        name = preview_cache_name_from_stamp(str(s), st.st_mtime, st.st_size)
        assert (out_dir / name).exists(), f"missing preview for {s.name}"


def test_preview_worker_skips_already_cached_files(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange — render once, then re-run and verify the file isn't rewritten.
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src = src_dir / "img.jpg"
    _make_jpeg(src)
    db = tmp_path / "test.db"
    cache = tmp_path / "cache"
    folder_id = _seed_db(db, [src])

    first = PreviewBuildWorker(db, cache, folder_id, target_long_edge=128)
    with qtbot.waitSignal(first.finished, timeout=10_000):
        first.start()

    st = src.stat()
    out_path = preview_dir(cache) / preview_cache_name_from_stamp(
        str(src), st.st_mtime, st.st_size
    )
    initial_mtime = out_path.stat().st_mtime
    time.sleep(0.05)  # ensure mtime resolution would tick on rewrite

    # Act
    second = PreviewBuildWorker(db, cache, folder_id, target_long_edge=128)
    with qtbot.waitSignal(second.finished, timeout=10_000):
        second.start()

    # Assert
    assert out_path.stat().st_mtime == initial_mtime


def test_preview_worker_finishes_on_empty_folder(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange — register a folder with no images.
    db = tmp_path / "test.db"
    cache = tmp_path / "cache"
    folder_repo = IndexedFolderRepository(db, key="")
    folder = folder_repo.add(str(tmp_path / "empty"))
    folder_repo.close()
    # Touch the repo so the schema exists.
    repo = ImageIndexRepository(db, key="")
    repo.close()

    # Act / Assert — worker emits finished(0, 0) without error.
    worker = PreviewBuildWorker(db, cache, folder.id, target_long_edge=128)
    with qtbot.waitSignal(worker.finished, timeout=5_000) as sig:
        worker.start()
    assert sig.args == [0, 0]


def test_preview_worker_writes_encrypted_files_when_keyed(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange — encrypted DB and matching ThumbCrypto-backed preview cache.
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src = src_dir / "img.jpg"
    _make_jpeg(src)
    db = tmp_path / "test.db"
    cache = tmp_path / "cache"
    key = "secret"

    # Seed under the encrypted key.
    folder_repo = IndexedFolderRepository(db, key=key)
    folder = folder_repo.add(str(src_dir))
    folder_repo.close()
    repo = ImageIndexRepository(db, key=key)
    st = src.stat()
    repo.upsert_image(
        str(src), src.name, st.st_mtime, st.st_size, {}, "",
        folder_id=folder.id,
    )
    repo.commit()
    repo.close()

    worker = PreviewBuildWorker(
        db, cache, folder.id, target_long_edge=128, key=key
    )

    # Act
    with qtbot.waitSignal(worker.finished, timeout=10_000):
        worker.start()

    # Assert — the cache contains a `.jpg.enc`, not a plain `.jpg`.
    files = list(preview_dir(cache).iterdir())
    suffixes = {f.suffix for f in files}
    assert ".enc" in next(iter(suffixes), "") or any(
        f.name.endswith(".jpg.enc") for f in files
    )
    assert not any(f.name.endswith(".jpg") and not f.name.endswith(".jpg.enc") for f in files)


def test_preview_worker_clamps_parallel_workers_to_one(
    tmp_path: Path,
) -> None:
    # Arrange
    db = tmp_path / "test.db"
    cache = tmp_path / "cache"

    # Act
    worker = PreviewBuildWorker(db, cache, folder_id=1, target_long_edge=128, workers=8)

    # Assert
    assert worker._workers == 1


def test_preview_worker_emits_oversized_signal_for_too_large_images(
    tmp_path: Path, qtbot: QtBot
) -> None:
    # Arrange — seed one normal image and one that is "too large" according to the
    # pixel-budget guard.  We fake the oversized condition by monkey-patching
    # render_preview to raise the expected RuntimeError for that specific file.
    import exif_turbo.ui.workers.preview_build_worker as _mod

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    ok_src = src_dir / "ok.jpg"
    big_src = src_dir / "big.jpg"
    _make_jpeg(ok_src)
    _make_jpeg(big_src)

    db = tmp_path / "test.db"
    cache = tmp_path / "cache"
    folder_id = _seed_db(db, [ok_src, big_src])

    original_render = _mod.render_preview

    def _fake_render(path: str, target: int) -> Image.Image:
        if path == str(big_src):
            raise RuntimeError(f"preview source too large: {path!r} (9999x9999)")
        return original_render(path, target)

    oversized_counts: list[int] = []
    worker = PreviewBuildWorker(db, cache, folder_id, target_long_edge=128)
    worker.oversized.connect(oversized_counts.append)

    _mod.render_preview = _fake_render  # type: ignore[assignment]
    try:
        with qtbot.waitSignal(worker.finished, timeout=10_000):
            worker.start()
    finally:
        _mod.render_preview = original_render  # type: ignore[assignment]

    # Assert — one oversized skip was reported, one preview was built.
    assert oversized_counts == [1]
    out_dir = preview_dir(cache)
    ok_st = ok_src.stat()
    ok_name = preview_cache_name_from_stamp(str(ok_src), ok_st.st_mtime, ok_st.st_size)
    assert (out_dir / ok_name).exists(), "normal image should still be rendered"
    big_st = big_src.stat()
    big_name = preview_cache_name_from_stamp(str(big_src), big_st.st_mtime, big_st.st_size)
    assert not (out_dir / big_name).exists(), "oversized image must not be rendered"
