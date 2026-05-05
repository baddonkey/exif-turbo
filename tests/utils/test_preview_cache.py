from __future__ import annotations

from pathlib import Path

from PIL import Image

from exif_turbo.utils.preview_cache import (
    clear_cached_previews_for,
    count_cached_previews,
    expected_preview_filenames,
    list_existing_previews,
    preview_cache_name_from_stamp,
    preview_cache_path,
    preview_dir,
)


def test_preview_dir_appends_previews_subdir(tmp_path: Path) -> None:
    assert preview_dir(tmp_path) == tmp_path / "previews"


def test_preview_cache_name_is_deterministic_for_same_stamp() -> None:
    a = preview_cache_name_from_stamp("/x/y.jpg", 1234.5, 1024)
    b = preview_cache_name_from_stamp("/x/y.jpg", 1234.5, 1024)
    assert a == b
    assert a.endswith(".jpg")
    # SHA-1 hex (40) + ".jpg"
    assert len(a) == 44


def test_preview_cache_name_changes_when_mtime_changes() -> None:
    a = preview_cache_name_from_stamp("/x/y.jpg", 100.0, 1024)
    b = preview_cache_name_from_stamp("/x/y.jpg", 200.0, 1024)
    assert a != b


def test_preview_cache_name_changes_when_size_changes() -> None:
    a = preview_cache_name_from_stamp("/x/y.jpg", 100.0, 1024)
    b = preview_cache_name_from_stamp("/x/y.jpg", 100.0, 2048)
    assert a != b


def test_preview_cache_path_lives_under_previews_subdir(tmp_path: Path) -> None:
    src = tmp_path / "img.jpg"
    Image.new("RGB", (4, 4), "red").save(src)
    out = preview_cache_path(str(src), tmp_path)
    assert out.parent == tmp_path / "previews"
    assert out.suffix == ".jpg"


def _seed_previews(
    tmp_path: Path,
    stamps: dict[str, tuple[float, int]],
    *,
    encrypted: bool,
) -> None:
    pdir = preview_dir(tmp_path)
    pdir.mkdir(parents=True, exist_ok=True)
    suffix = ".jpg.enc" if encrypted else ".jpg"
    for name in expected_preview_filenames(stamps, encrypted=encrypted):
        # Filename already carries the right suffix.
        assert name.endswith(suffix)
        (pdir / name).write_bytes(b"x")


def test_count_cached_previews_counts_only_matching_files(tmp_path: Path) -> None:
    stamps = {
        "/a.jpg": (1.0, 100),
        "/b.jpg": (2.0, 200),
        "/c.jpg": (3.0, 300),
    }
    # Only seed two of three.
    partial = {k: stamps[k] for k in ("/a.jpg", "/b.jpg")}
    _seed_previews(tmp_path, partial, encrypted=False)

    assert count_cached_previews(tmp_path, stamps, encrypted=False) == 2
    assert count_cached_previews(tmp_path, partial, encrypted=False) == 2
    assert count_cached_previews(tmp_path, {}, encrypted=False) == 0


def test_count_cached_previews_respects_encryption_flag(tmp_path: Path) -> None:
    stamps = {"/a.jpg": (1.0, 100)}
    _seed_previews(tmp_path, stamps, encrypted=True)
    # Plain .jpg lookup ignores .jpg.enc files.
    assert count_cached_previews(tmp_path, stamps, encrypted=False) == 0
    assert count_cached_previews(tmp_path, stamps, encrypted=True) == 1


def test_clear_cached_previews_removes_only_listed_stamps(tmp_path: Path) -> None:
    folder_a = {"/a1.jpg": (1.0, 100), "/a2.jpg": (2.0, 200)}
    folder_b = {"/b1.jpg": (3.0, 300)}
    _seed_previews(tmp_path, folder_a, encrypted=False)
    _seed_previews(tmp_path, folder_b, encrypted=False)

    removed = clear_cached_previews_for(tmp_path, folder_a, encrypted=False)
    assert removed == 2

    remaining = list_existing_previews(tmp_path, encrypted=False)
    assert remaining == expected_preview_filenames(folder_b, encrypted=False)


def test_clear_cached_previews_tolerates_missing_files(tmp_path: Path) -> None:
    stamps = {"/x.jpg": (1.0, 100)}
    # Nothing seeded — must not raise and should report zero removals.
    assert clear_cached_previews_for(tmp_path, stamps, encrypted=False) == 0
