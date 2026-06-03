from __future__ import annotations

import json
from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository
from tests.conftest import make_jpeg, make_png


# ── upsert / search ──────────────────────────────────────────────────────────


def test_upsert_and_search_empty_query_returns_row(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path = str(make_jpeg(tmp_path / "photo.jpg"))

    # Act
    repo.upsert_image(path, "photo.jpg", 1_000_000.0, 12345, {}, "photo jpg")
    repo.commit()
    rows = repo.search_images("", limit=10, offset=0)

    # Assert
    assert len(rows) == 1
    assert rows[0][1] == path
    assert rows[0][2] == "photo.jpg"


def test_upsert_updates_existing_row(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path = str(make_jpeg(tmp_path / "photo.jpg"))
    repo.upsert_image(path, "photo.jpg", 1.0, 100, {}, "old text")
    repo.commit()

    # Act — upsert again with changed mtime/size
    repo.upsert_image(path, "photo.jpg", 2.0, 200, {"Make": "Canon"}, "Canon photo jpg")
    repo.commit()
    rows = repo.search_images("", limit=10, offset=0)

    # Assert — still one row, with updated values
    assert len(rows) == 1
    meta = json.loads(rows[0][3])
    assert meta["Make"] == "Canon"


def test_count_images_empty_db_returns_zero(repo: ImageIndexRepository) -> None:
    assert repo.count_images("") == 0


def test_count_images_after_insert_returns_correct_count(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    for i in range(5):
        p = str(make_jpeg(tmp_path / f"img{i}.jpg"))
        repo.upsert_image(p, f"img{i}.jpg", float(i), i * 100, {}, f"img{i} jpg")
    repo.commit()

    assert repo.count_images("") == 5


def test_find_image_offset_path_filter_returns_sorted_offset(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    folder = tmp_path / "folder"
    folder.mkdir()
    for name in ("c.jpg", "a.jpg", "b.jpg"):
        path = str(make_jpeg(folder / name))
        repo.upsert_image(path, name, 1.0, 100, {}, name)
    repo.commit()
    rows = repo.search_images("", limit=10, offset=0, sort_by="filename_asc")
    target_id = next(row[0] for row in rows if row[2] == "b.jpg")

    # Act
    offset = repo.find_image_offset(
        target_id,
        sort_by="filename_asc",
        path_filter=[str(folder)],
    )

    # Assert
    assert offset == 1


# ── FTS5 search ───────────────────────────────────────────────────────────────


def test_search_fts_match_returns_relevant_row(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path_canon = str(make_jpeg(tmp_path / "canon.jpg"))
    path_nikon = str(make_jpeg(tmp_path / "nikon.jpg"))
    repo.upsert_image(path_canon, "canon.jpg", 1.0, 100, {"Make": "Canon"}, "Make Canon canon jpg")
    repo.upsert_image(path_nikon, "nikon.jpg", 1.0, 100, {"Make": "Nikon"}, "Make Nikon nikon jpg")
    repo.commit()

    # Act
    rows = repo.search_images("Canon", limit=10, offset=0)

    # Assert
    assert len(rows) == 1
    assert "canon.jpg" in rows[0][2]


def test_search_fts_no_match_returns_empty(repo: ImageIndexRepository, tmp_path: Path) -> None:
    path = str(make_jpeg(tmp_path / "photo.jpg"))
    repo.upsert_image(path, "photo.jpg", 1.0, 100, {}, "photo jpg")
    repo.commit()

    rows = repo.search_images("Leica", limit=10, offset=0)
    assert rows == []


# ── FTS5 logical operators ────────────────────────────────────────────────────


def test_search_fts_and_operator_returns_intersection(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — canon has both terms; nikon has only the second
    path_canon = str(make_jpeg(tmp_path / "canon.jpg"))
    path_nikon = str(make_jpeg(tmp_path / "nikon.jpg"))
    repo.upsert_image(path_canon, "canon.jpg", 1.0, 100, {}, "Make Canon lens 50mm")
    repo.upsert_image(path_nikon, "nikon.jpg", 1.0, 100, {}, "Make Nikon lens 85mm")
    repo.commit()

    # Act
    rows = repo.search_images("Canon AND 50mm", limit=10, offset=0)

    # Assert — only the image that has both terms is returned
    assert len(rows) == 1
    assert "canon.jpg" in rows[0][2]


def test_search_fts_and_operator_returns_empty_when_no_intersection(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path_canon = str(make_jpeg(tmp_path / "canon.jpg"))
    path_nikon = str(make_jpeg(tmp_path / "nikon.jpg"))
    repo.upsert_image(path_canon, "canon.jpg", 1.0, 100, {}, "Make Canon lens 50mm")
    repo.upsert_image(path_nikon, "nikon.jpg", 1.0, 100, {}, "Make Nikon lens 85mm")
    repo.commit()

    # Act — no image has both Nikon and 50mm
    rows = repo.search_images("Nikon AND 50mm", limit=10, offset=0)

    # Assert
    assert rows == []


def test_search_fts_or_operator_returns_union(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path_canon = str(make_jpeg(tmp_path / "canon.jpg"))
    path_nikon = str(make_jpeg(tmp_path / "nikon.jpg"))
    repo.upsert_image(path_canon, "canon.jpg", 1.0, 100, {}, "Make Canon lens 50mm")
    repo.upsert_image(path_nikon, "nikon.jpg", 1.0, 100, {}, "Make Nikon lens 85mm")
    repo.commit()

    # Act
    rows = repo.search_images("Canon OR Nikon", limit=10, offset=0)

    # Assert — both images are returned
    assert len(rows) == 2
    filenames = {r[2] for r in rows}
    assert filenames == {"canon.jpg", "nikon.jpg"}


def test_search_fts_not_operator_excludes_negated_term(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — only canon has "50mm"; nikon does not
    path_canon = str(make_jpeg(tmp_path / "canon.jpg"))
    path_nikon = str(make_jpeg(tmp_path / "nikon.jpg"))
    repo.upsert_image(path_canon, "canon.jpg", 1.0, 100, {}, "Make Canon lens 50mm")
    repo.upsert_image(path_nikon, "nikon.jpg", 1.0, 100, {}, "Make Nikon lens 85mm")
    repo.commit()

    # Act — "50mm" present AND "Nikon" absent → only canon qualifies
    rows = repo.search_images("50mm NOT Nikon", limit=10, offset=0)

    # Assert
    assert len(rows) == 1
    assert "canon.jpg" in rows[0][2]


def test_search_fts_not_operator_returns_empty_when_all_excluded(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path_canon = str(make_jpeg(tmp_path / "canon.jpg"))
    repo.upsert_image(path_canon, "canon.jpg", 1.0, 100, {}, "Make Canon lens 50mm")
    repo.commit()

    # Act — "50mm" present but "Canon" also present → excluded by NOT
    rows = repo.search_images("50mm NOT Canon", limit=10, offset=0)

    # Assert
    assert rows == []


def test_search_fts_phrase_search_returns_exact_match_only(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — both images share individual words but differ in adjacency
    path_deer = str(make_jpeg(tmp_path / "deer.jpg"))
    path_fox = str(make_jpeg(tmp_path / "fox.jpg"))
    repo.upsert_image(path_deer, "deer.jpg", 1.0, 100, {}, "red deer wildlife")
    repo.upsert_image(path_fox, "fox.jpg", 1.0, 100, {}, "red fox wildlife")
    repo.commit()

    # Act
    rows = repo.search_images('"red deer"', limit=10, offset=0)

    # Assert — only the image with the exact adjacent phrase is returned
    assert len(rows) == 1
    assert "deer.jpg" in rows[0][2]


def test_search_fts_prefix_wildcard_returns_prefix_matches(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path_fuji = str(make_jpeg(tmp_path / "fuji.jpg"))
    path_nikon = str(make_jpeg(tmp_path / "nikon.jpg"))
    repo.upsert_image(path_fuji, "fuji.jpg", 1.0, 100, {}, "Make Fujifilm X100V")
    repo.upsert_image(path_nikon, "nikon.jpg", 1.0, 100, {}, "Make Nikon Z9")
    repo.commit()

    # Act
    rows = repo.search_images("Fuji*", limit=10, offset=0)

    # Assert — only the Fujifilm image matches
    assert len(rows) == 1
    assert "fuji.jpg" in rows[0][2]


def test_search_fts_colon_in_query_matches_both_tokens(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — one image has an ExifTool-style group:key entry in its metadata
    path_a = str(make_jpeg(tmp_path / "gps.jpg"))
    path_b = str(make_jpeg(tmp_path / "other.jpg"))
    repo.upsert_image(path_a, "gps.jpg", 1.0, 100, {}, "GPS GPSLatitude 47.3765")
    repo.upsert_image(path_b, "other.jpg", 1.0, 100, {}, "ExifIFD FocalLength 50mm")
    repo.commit()

    # Act — typing "GPS:GPSLatitude" should be treated as implicit AND of both tokens
    rows = repo.search_images("GPS:GPSLatitude", limit=10, offset=0)

    # Assert — matches the image whose metadata contains both GPS and GPSLatitude
    assert len(rows) == 1
    assert "gps.jpg" in rows[0][2]


def test_search_fts_colon_does_not_cause_error(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path_a = str(make_jpeg(tmp_path / "a.jpg"))
    repo.upsert_image(path_a, "a.jpg", 1.0, 100, {}, "ExifIFD FocalLength 50")
    repo.commit()

    # Act — colon-prefixed query should not raise an FTS5 syntax error
    rows = repo.search_images("ExifIFD:FocalLength", limit=10, offset=0)

    # Assert — result returned without error
    assert len(rows) == 1


# ── delete_missing ────────────────────────────────────────────────────────────


def test_delete_missing_removes_stale_rows(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — insert two images
    path_a = str(make_jpeg(tmp_path / "a.jpg"))
    path_b = str(make_jpeg(tmp_path / "b.jpg"))
    repo.upsert_image(path_a, "a.jpg", 1.0, 100, {}, "a jpg")
    repo.upsert_image(path_b, "b.jpg", 1.0, 100, {}, "b jpg")
    repo.commit()

    # Act — only keep path_a
    repo.delete_missing([path_a])
    repo.commit()
    rows = repo.search_images("", limit=10, offset=0)

    # Assert
    assert len(rows) == 1
    assert rows[0][1] == path_a


def test_delete_missing_all_kept_removes_nothing(repo: ImageIndexRepository, tmp_path: Path) -> None:
    path = str(make_jpeg(tmp_path / "photo.jpg"))
    repo.upsert_image(path, "photo.jpg", 1.0, 100, {}, "photo jpg")
    repo.commit()

    repo.delete_missing([path])
    repo.commit()

    assert repo.count_images("") == 1


def test_delete_missing_scoped_to_folder_preserves_images_in_other_folders(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange — two images in separate sibling folders
    folder_a = tmp_path / "folder_a"
    folder_b = tmp_path / "folder_b"
    folder_a.mkdir()
    folder_b.mkdir()
    path_a = str(make_jpeg(folder_a / "a.jpg"))
    path_b = str(make_jpeg(folder_b / "b.jpg"))
    repo.upsert_image(path_a, "a.jpg", 1.0, 100, {}, "a jpg")
    repo.upsert_image(path_b, "b.jpg", 1.0, 100, {}, "b jpg")
    repo.commit()

    # Act — delete_missing scoped to folder_a only, with an empty keep-set
    # (simulates rescanning folder_a which now has no images on disk)
    repo.delete_missing([], folder_roots=[str(folder_a)])
    repo.commit()
    rows = repo.search_images("", limit=10, offset=0)

    # Assert — path_b in folder_b must be untouched
    assert len(rows) == 1
    assert rows[0][1] == path_b


# ── format counts ─────────────────────────────────────────────────────────────


def test_get_format_counts_groups_jpeg_alias(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — one .jpg and one .jpeg file (should merge into "jpg")
    path_jpg = str(make_jpeg(tmp_path / "a.jpg"))
    path_jpeg = str(make_jpeg(tmp_path / "b.jpeg"))
    repo.upsert_image(path_jpg, "a.jpg", 1.0, 100, {}, "a jpg")
    repo.upsert_image(path_jpeg, "b.jpeg", 1.0, 100, {}, "b jpeg")
    repo.commit()

    counts = dict(repo.get_format_counts())

    assert counts.get("jpg", 0) == 2
    assert "jpeg" not in counts


def test_search_images_returns_mtime_in_column_5(repo: ImageIndexRepository, tmp_path: Path) -> None:
    path = str(make_jpeg(tmp_path / "photo.jpg"))
    repo.upsert_image(path, "photo.jpg", 1234567.89, 500, {}, "photo jpg")
    repo.commit()

    rows = repo.search_images("", limit=10, offset=0)
    assert len(rows) == 1
    assert rows[0][5] == pytest.approx(1234567.89)


# ── captured_at / date filter ────────────────────────────────────────────────

_JAN_2022 = 1640995200  # 2022-01-01 00:00:00 UTC
_JAN_2023 = 1672531200  # 2023-01-01 00:00:00 UTC
_JAN_2024 = 1704067200  # 2024-01-01 00:00:00 UTC
_DEC_2023 = 1703980800  # 2023-12-31 00:00:00 UTC


def test_upsert_persists_captured_at(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path = str(make_jpeg(tmp_path / "photo.jpg"))

    # Act
    repo.upsert_image(path, "photo.jpg", 1.0, 100, {}, "photo jpg", captured_at=_JAN_2022)
    repo.commit()

    # Assert — captured_at survives a round-trip
    row = repo.conn.execute("SELECT captured_at FROM images WHERE path = ?", (path,)).fetchone()
    assert row is not None
    assert row[0] == _JAN_2022


def test_upsert_captured_at_none_stores_null(repo: ImageIndexRepository, tmp_path: Path) -> None:
    path = str(make_jpeg(tmp_path / "photo.jpg"))
    repo.upsert_image(path, "photo.jpg", 1.0, 100, {}, "photo jpg", captured_at=None)
    repo.commit()

    row = repo.conn.execute("SELECT captured_at FROM images WHERE path = ?", (path,)).fetchone()
    assert row is not None
    assert row[0] is None


def test_search_images_date_from_filters_out_earlier_images(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    path_old = str(make_jpeg(tmp_path / "old.jpg"))
    path_new = str(make_jpeg(tmp_path / "new.jpg"))
    repo.upsert_image(path_old, "old.jpg", 1.0, 100, {}, "old jpg", captured_at=_JAN_2022)
    repo.upsert_image(path_new, "new.jpg", 1.0, 100, {}, "new jpg", captured_at=_JAN_2023)
    repo.commit()

    # Act — filter from 2023-01-01 onward
    rows = repo.search_images("", limit=10, offset=0, date_from=_JAN_2023)

    # Assert
    assert len(rows) == 1
    assert rows[0][2] == "new.jpg"


def test_search_images_date_to_filters_out_later_images(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    path_old = str(make_jpeg(tmp_path / "old.jpg"))
    path_new = str(make_jpeg(tmp_path / "new.jpg"))
    repo.upsert_image(path_old, "old.jpg", 1.0, 100, {}, "old jpg", captured_at=_JAN_2022)
    repo.upsert_image(path_new, "new.jpg", 1.0, 100, {}, "new jpg", captured_at=_JAN_2023)
    repo.commit()

    # Act — filter up to end of 2022
    rows = repo.search_images("", limit=10, offset=0, date_to=_JAN_2023 - 1)

    # Assert
    assert len(rows) == 1
    assert rows[0][2] == "old.jpg"


def test_search_images_date_range_excludes_outside_images(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange — three years, filter to middle year only
    paths = {
        "y2022.jpg": _JAN_2022,
        "y2023.jpg": _JAN_2023,
        "y2024.jpg": _JAN_2024,
    }
    for fname, ts in paths.items():
        p = str(make_jpeg(tmp_path / fname))
        repo.upsert_image(p, fname, 1.0, 100, {}, fname, captured_at=ts)
    repo.commit()

    # Act — select 2023 only
    rows = repo.search_images("", limit=10, offset=0, date_from=_JAN_2023, date_to=_DEC_2023)

    # Assert
    assert len(rows) == 1
    assert rows[0][2] == "y2023.jpg"


def test_search_images_date_filter_excludes_null_captured_at(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange — one image with captured_at, one without
    path_dated = str(make_jpeg(tmp_path / "dated.jpg"))
    path_nodates = str(make_jpeg(tmp_path / "nodate.jpg"))
    repo.upsert_image(path_dated, "dated.jpg", 1.0, 100, {}, "dated jpg", captured_at=_JAN_2023)
    repo.upsert_image(path_nodates, "nodate.jpg", 1.0, 100, {}, "nodate jpg", captured_at=None)
    repo.commit()

    # Act
    rows = repo.search_images("", limit=10, offset=0, date_from=_JAN_2022)

    # Assert — null captured_at image is excluded when a date filter is active
    assert len(rows) == 1
    assert rows[0][2] == "dated.jpg"


def test_count_images_respects_date_filter(repo: ImageIndexRepository, tmp_path: Path) -> None:
    for i, ts in enumerate([_JAN_2022, _JAN_2023, _JAN_2024]):
        p = str(make_jpeg(tmp_path / f"img{i}.jpg"))
        repo.upsert_image(p, f"img{i}.jpg", 1.0, 100, {}, f"img{i} jpg", captured_at=ts)
    repo.commit()

    assert repo.count_images("", date_from=_JAN_2023) == 2
    assert repo.count_images("", date_to=_JAN_2022) == 1
    assert repo.count_images("", date_from=_JAN_2023, date_to=_DEC_2023) == 1


def test_get_year_counts_returns_one_entry_per_year(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange — two 2022, three 2023
    for i in range(2):
        p = str(make_jpeg(tmp_path / f"y22_{i}.jpg"))
        repo.upsert_image(p, f"y22_{i}.jpg", 1.0, 100, {}, f"y22 {i}", captured_at=_JAN_2022 + i)
    for i in range(3):
        p = str(make_jpeg(tmp_path / f"y23_{i}.jpg"))
        repo.upsert_image(p, f"y23_{i}.jpg", 1.0, 100, {}, f"y23 {i}", captured_at=_JAN_2023 + i)
    repo.commit()

    # Act
    counts = repo.get_year_counts()

    # Assert
    by_year = {yr: cnt for yr, cnt in counts}
    assert by_year[2022] == 2
    assert by_year[2023] == 3


def test_get_year_counts_excludes_null_captured_at(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    p1 = str(make_jpeg(tmp_path / "dated.jpg"))
    p2 = str(make_jpeg(tmp_path / "nodate.jpg"))
    repo.upsert_image(p1, "dated.jpg", 1.0, 100, {}, "dated jpg", captured_at=_JAN_2022)
    repo.upsert_image(p2, "nodate.jpg", 1.0, 100, {}, "nodate jpg", captured_at=None)
    repo.commit()

    counts = repo.get_year_counts()
    by_year = {yr: cnt for yr, cnt in counts}
    assert by_year == {2022: 1}


# ── bulk_mark_images / bulk_invert_images ────────────────────────────────────


def test_bulk_mark_images_no_filter_marks_all_rows(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    paths = [str(make_jpeg(tmp_path / f"img{i}.jpg")) for i in range(3)]
    for i, p in enumerate(paths):
        repo.upsert_image(p, f"img{i}.jpg", 1.0, 100, {}, f"img{i} jpg")
    repo.commit()

    # Act
    affected = repo.bulk_mark_images(True)

    # Assert
    assert len(affected) == 3
    assert set(affected) == set(paths)


def test_bulk_mark_images_fts_query_marks_matching_only(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path_a = str(make_jpeg(tmp_path / "a.jpg"))
    path_b = str(make_jpeg(tmp_path / "b.jpg"))
    repo.upsert_image(path_a, "a.jpg", 1.0, 100, {}, "canon camera")
    repo.upsert_image(path_b, "b.jpg", 1.0, 100, {}, "nikon camera")
    repo.commit()

    # Act
    affected = repo.bulk_mark_images(True, query="canon")

    # Assert
    assert len(affected) == 1
    assert repo.get_marked_paths() == [path_a]


def test_bulk_mark_images_deselect_clears_marks(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — mark all, then unmark one via fts query
    path_a = str(make_jpeg(tmp_path / "a.jpg"))
    path_b = str(make_jpeg(tmp_path / "b.jpg"))
    repo.upsert_image(path_a, "a.jpg", 1.0, 100, {}, "canon camera")
    repo.upsert_image(path_b, "b.jpg", 1.0, 100, {}, "nikon camera")
    repo.commit()
    repo.bulk_mark_images(True)

    # Act
    repo.bulk_mark_images(False, query="nikon")

    # Assert — only path_a remains marked
    assert repo.get_marked_paths() == [path_a]


def test_bulk_invert_images_flips_marks(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — mark first image only
    path_a = str(make_jpeg(tmp_path / "a.jpg"))
    path_b = str(make_jpeg(tmp_path / "b.jpg"))
    repo.upsert_image(path_a, "a.jpg", 1.0, 100, {}, "a jpg")
    repo.upsert_image(path_b, "b.jpg", 1.0, 100, {}, "b jpg")
    repo.commit()
    repo.bulk_mark_images(True, query="a")

    # Act
    repo.bulk_invert_images()

    # Assert — marks are flipped: path_b is now marked, path_a is not
    assert repo.get_marked_paths() == [path_b]


def test_bulk_mark_images_returns_zero_for_no_match(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    path = str(make_jpeg(tmp_path / "a.jpg"))
    repo.upsert_image(path, "a.jpg", 1.0, 100, {}, "canon camera")
    repo.commit()

    # Act
    affected = repo.bulk_mark_images(True, query="nikon")

    # Assert
    assert affected == []
    assert repo.get_marked_paths() == []
