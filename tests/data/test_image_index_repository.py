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


def test_search_fts_column_scope_restricts_to_filename_column(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — "eagle" appears in filename of one image and metadata_text of another
    path_hawk = str(make_jpeg(tmp_path / "hawk.jpg"))
    path_eagle = str(make_jpeg(tmp_path / "eagle.jpg"))
    repo.upsert_image(path_hawk, "hawk.jpg", 1.0, 100, {}, "eagle soaring wildlife")
    repo.upsert_image(path_eagle, "eagle.jpg", 1.0, 100, {}, "hawk diving wildlife")
    repo.commit()

    # Act — restrict search to the filename column
    rows = repo.search_images("filename:eagle", limit=10, offset=0)

    # Assert — only the image whose filename contains "eagle" is returned
    assert len(rows) == 1
    assert "eagle.jpg" in rows[0][2]


def test_search_fts_column_scope_restricts_to_metadata_text_column(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange — same setup as above
    path_hawk = str(make_jpeg(tmp_path / "hawk.jpg"))
    path_eagle = str(make_jpeg(tmp_path / "eagle.jpg"))
    repo.upsert_image(path_hawk, "hawk.jpg", 1.0, 100, {}, "eagle soaring wildlife")
    repo.upsert_image(path_eagle, "eagle.jpg", 1.0, 100, {}, "hawk diving wildlife")
    repo.commit()

    # Act — restrict search to metadata_text column
    rows = repo.search_images("metadata_text:eagle", limit=10, offset=0)

    # Assert — only the image whose metadata_text contains "eagle" is returned
    assert len(rows) == 1
    assert "hawk.jpg" in rows[0][2]


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
