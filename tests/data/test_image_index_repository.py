from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
import sqlcipher3

from exif_turbo.data.image_index_repository import (
    ImageIndexRepository,
    ImageSetFilterReapplyCanceled,
)
from tests.conftest import make_jpeg, make_png


class _SpecialQueryErrorOnceConnection:
    """Proxy that simulates SQLCipher rejecting wildcard FTS MATCH once."""

    def __init__(self, inner) -> None:  # type: ignore[no-untyped-def]
        self._inner = inner
        self._raised = False
        self.fts_queries: list[str] = []

    def execute(self, sql: str, args: tuple = ()):  # type: ignore[no-untyped-def]
        if "MATCH ?" in sql and args and isinstance(args[0], str):
            query = args[0]
            self.fts_queries.append(query)
            if "*" in query and not self._raised:
                self._raised = True
                raise sqlcipher3.OperationalError(f"unknown special query: {query}")
        return self._inner.execute(sql, args)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


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


def test_image_set_create_add_and_remove_members(repo: ImageIndexRepository, tmp_path: Path) -> None:
    # Arrange
    image_paths = [
        str(make_jpeg(tmp_path / "first.jpg")),
        str(make_jpeg(tmp_path / "second.jpg")),
    ]
    for image_path in image_paths:
        repo.upsert_image(
            image_path, Path(image_path).name, 1.0, 100, {"Make": "Canon"}, "Canon"
        )
    apply_filter = {"operator": "and", "conditions": []}

    # Act
    set_id = repo.create_image_set("Family", apply_filter)
    first_add_count = repo.add_images_to_set(set_id, image_paths)
    duplicate_add_count = repo.add_images_to_set(set_id, image_paths)
    remove_count = repo.remove_images_from_set(set_id, image_paths[:1])
    image_sets = repo.list_image_sets()
    members = repo.get_image_set_members(set_id)

    # Assert
    assert first_add_count == 2
    assert duplicate_add_count == 0
    assert remove_count == 1
    assert image_sets[0]["apply_filter"] == apply_filter
    assert image_sets[0]["member_count"] == 1
    assert [member["path"] for member in members] == [image_paths[1]]


def test_search_image_set_filter_restricts_rows_counts_and_offsets(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    member_path = str(make_jpeg(tmp_path / "member.jpg"))
    other_path = str(make_jpeg(tmp_path / "other.jpg"))
    repo.upsert_image(
        member_path, "member.jpg", 1.0, 100, {}, "wildlife", captured_at=1704067200.0
    )
    repo.upsert_image(
        other_path, "other.jpg", 1.0, 100, {}, "wildlife", captured_at=1704067200.0
    )
    set_id = repo.create_image_set("Wildlife")
    repo.add_images_to_set(set_id, [member_path])

    # Act
    rows = repo.search_images("wildlife", limit=10, offset=0, image_set_id=set_id)
    count = repo.count_images("wildlife", image_set_id=set_id)
    matching_paths = repo.get_matching_paths("wildlife", image_set_id=set_id)
    all_sets_rows = repo.search_images("wildlife", 10, 0, image_set_id=-1)
    all_sets_count = repo.count_images("wildlife", image_set_id=-1)
    ignored_rows = repo.search_images("wildlife", 10, 0)
    ignored_count = repo.count_images("wildlife")
    filtered_paths = repo.get_filtered_paths(image_set_id=set_id)
    format_counts = repo.get_format_counts(query="wildlife", image_set_id=set_id)
    year_counts = repo.get_year_counts(query="wildlife", image_set_id=set_id)
    hydrated_rows = repo.get_images_by_paths(
        [member_path, other_path], image_set_id=set_id
    )
    member_offset = repo.find_image_offset(1, query="wildlife", image_set_id=set_id)
    other_offset = repo.find_image_offset(2, query="wildlife", image_set_id=set_id)
    marked = repo.bulk_mark_images(True, query="wildlife", image_set_id=set_id)

    # Assert
    assert [row[1] for row in rows] == [member_path]
    assert count == 1
    assert matching_paths == [member_path]
    assert filtered_paths == {member_path}
    assert format_counts == [("jpg", 1)]
    assert year_counts == [(2024, 1)]
    assert [row[1] for row in hydrated_rows] == [member_path]
    assert member_offset == 0
    assert other_offset is None
    assert marked == [member_path]
    assert [row[1] for row in all_sets_rows] == [member_path]
    assert all_sets_count == 1
    assert {row[1] for row in ignored_rows} == {member_path, other_path}
    assert ignored_count == 2


def test_image_set_name_is_unique_ignoring_case(repo: ImageIndexRepository) -> None:
    # Arrange
    repo.create_image_set("Summer")

    # Act / Assert
    with pytest.raises(ValueError, match="already exists"):
        repo.create_image_set(" summer ")


def test_image_set_members_cascade_when_indexed_image_is_deleted(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    image_path = str(make_jpeg(tmp_path / "removed.jpg"))
    repo.upsert_image(image_path, "removed.jpg", 1.0, 100, {}, "removed")
    set_id = repo.create_image_set("Archive")
    repo.add_images_to_set(set_id, [image_path])

    # Act
    repo.delete_missing([])

    # Assert
    assert repo.get_image_set_members(set_id) == []


def test_image_set_filter_reapply_matches_nested_text_and_metadata_conditions(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    canon_path = str(make_jpeg(tmp_path / "canon.jpg"))
    marked_path = str(make_jpeg(tmp_path / "marked.jpg"))
    other_path = str(make_jpeg(tmp_path / "other.jpg"))
    repo.upsert_image(canon_path, "canon.jpg", 1.0, 100, {"Make": "Canon"}, "camera canon")
    repo.upsert_image(marked_path, "marked.jpg", 1.0, 100, {"Make": "Nikon"}, "camera nikon")
    repo.upsert_image(other_path, "other.jpg", 1.0, 100, {"Make": "Nikon"}, "camera nikon")
    repo.mark_image(marked_path, True)
    set_id = repo.create_image_set(
        "Cameras",
        {
            "op": "and",
            "conditions": [
                {"field": "text", "operator": "matches", "value": "camera"},
                {
                    "op": "or",
                    "conditions": [
                        {
                            "field": "metadata",
                            "key": "Make",
                            "operator": "equals",
                            "value": "Canon",
                        },
                        {"field": "marked", "operator": "equals", "value": True},
                    ],
                },
            ],
        },
    )

    # Act
    result = repo.reapply_image_set_filter(set_id, mode="replace")

    # Assert
    assert result == {"matched": 2, "added": 2, "removed": 0}
    assert {member["path"] for member in repo.get_image_set_members(set_id)} == {
        canon_path,
        marked_path,
    }


def test_image_set_filter_empty_replace_requires_confirmation(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    image_path = str(make_jpeg(tmp_path / "kept.jpg"))
    repo.upsert_image(image_path, "kept.jpg", 1.0, 100, {}, "kept")
    set_id = repo.create_image_set(
        "Keep",
        {"op": "and", "conditions": [
            {"field": "text", "operator": "matches", "value": "no-match-token"}
        ]},
    )
    repo.add_images_to_set(set_id, [image_path])

    # Act / Assert
    with pytest.raises(ValueError, match="requires confirmation"):
        repo.reapply_image_set_filter(set_id, mode="replace")
    assert [member["path"] for member in repo.get_image_set_members(set_id)] == [image_path]


def test_image_set_filter_numeric_metadata_comparison_matches_numeric_values(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    first_path = str(make_jpeg(tmp_path / "wide.jpg"))
    second_path = str(make_jpeg(tmp_path / "narrow.jpg"))
    repo.upsert_image(first_path, "wide.jpg", 1.0, 100, {"FocalLength": "85"}, "wide")
    repo.upsert_image(second_path, "narrow.jpg", 1.0, 100, {"FocalLength": "35"}, "narrow")
    set_id = repo.create_image_set(
        "Long lenses",
        {
            "op": "and",
            "conditions": [
                {
                    "field": "metadata",
                    "key": "FocalLength",
                    "operator": "greater_than",
                    "value": 50,
                }
            ],
        },
    )

    # Act
    count = repo.count_image_set_filter_matches(set_id)

    # Assert
    assert count == 1


def test_image_set_filter_can_be_cleared(repo: ImageIndexRepository) -> None:
    # Arrange
    set_id = repo.create_image_set(
        "Filtered",
        {"op": "and", "conditions": [
            {"field": "marked", "operator": "equals", "value": True}
        ]},
    )

    # Act
    repo.set_image_set_filter(set_id, None)

    # Assert
    image_set = repo.list_image_sets()[0]
    assert image_set["apply_filter"] is None
    assert image_set["apply_filter_version"] is None


def test_image_set_filter_rejects_invalid_tree_without_overwriting_saved_filter(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    valid_filter = {
        "op": "and",
        "conditions": [
            {"field": "marked", "operator": "equals", "value": True}
        ],
    }
    set_id = repo.create_image_set("Validated", valid_filter)

    # Act / Assert
    with pytest.raises(ValueError, match="Unsupported image-set filter condition"):
        repo.set_image_set_filter(
            set_id,
            {
                "op": "and",
                "conditions": [
                    {"field": "mystery", "operator": "equals", "value": "x"}
                ],
            },
        )
    assert repo.list_image_sets()[0]["apply_filter"] == valid_filter


def test_image_set_filter_reapply_reports_batched_progress(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    image_paths = [str(tmp_path / f"match-{index}.jpg") for index in range(1001)]
    repo.upsert_images_batch(
        [
            (path, Path(path).name, 1.0, 100, {}, "wildlife", None, None)
            for path in image_paths
        ]
    )
    set_id = repo.create_image_set(
        "Progress",
        {
            "op": "and",
            "conditions": [
                {"field": "text", "operator": "matches", "value": "wildlife"}
            ],
        },
    )
    progress: list[tuple[int, int]] = []

    # Act
    result = repo.reapply_image_set_filter_with_progress(
        set_id,
        mode="add",
        on_progress=lambda done, total: progress.append((done, total)),
        batch_size=500,
    )

    # Assert
    assert result == {"matched": 1001, "added": 1001, "removed": 0}
    assert progress == [(0, 1001), (500, 1001), (1000, 1001), (1001, 1001)]


@pytest.mark.parametrize("mode", ["add", "replace"])
def test_image_set_filter_reapply_cancel_before_changes_keeps_members(
    repo: ImageIndexRepository, tmp_path: Path, mode: str
) -> None:
    # Arrange
    stale_path = str(tmp_path / "prior-member.jpg")
    matching_path = str(tmp_path / "matching.jpg")
    repo.upsert_image(stale_path, "prior-member.jpg", 1.0, 100, {}, "other")
    repo.upsert_image(matching_path, "matching.jpg", 1.0, 100, {}, "wildlife")
    set_id = repo.create_image_set(
        "Cancel before changes",
        {
            "op": "and",
            "conditions": [
                {"field": "text", "operator": "matches", "value": "wildlife"}
            ],
        },
    )
    repo.add_images_to_set(set_id, [stale_path])

    # Act / Assert
    with pytest.raises(ImageSetFilterReapplyCanceled) as raised:
        repo.reapply_image_set_filter_with_progress(
            set_id, mode=mode, cancel_check=lambda: True
        )
    assert (raised.value.processed, raised.value.added, raised.value.removed) == (0, 0, 0)
    assert [member["path"] for member in repo.get_image_set_members(set_id)] == [stale_path]
    assert not repo.conn.in_transaction


def test_image_set_filter_reapply_cancel_keeps_completed_replacement(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    matching_paths = [str(tmp_path / f"match-{index}.jpg") for index in range(1001)]
    stale_path = str(tmp_path / "prior-member.jpg")
    repo.upsert_images_batch(
        [
            (path, Path(path).name, 1.0, 100, {}, "wildlife", None, None)
            for path in matching_paths
        ]
        + [(stale_path, "prior-member.jpg", 1.0, 100, {}, "other", None, None)]
    )
    set_id = repo.create_image_set(
        "Cancelable",
        {
            "op": "and",
            "conditions": [
                {"field": "text", "operator": "matches", "value": "wildlife"}
            ],
        },
    )
    repo.add_images_to_set(set_id, [stale_path])
    cancel_event = threading.Event()
    progress: list[tuple[int, int]] = []

    def cancel_after_batch(done: int, total: int) -> None:
        progress.append((done, total))
        if done >= 500:
            cancel_event.set()

    # Act / Assert
    with pytest.raises(ImageSetFilterReapplyCanceled) as raised:
        repo.reapply_image_set_filter_with_progress(
            set_id,
            mode="replace",
            confirm_empty_replace=True,
            cancel_check=cancel_event.is_set,
            on_progress=cancel_after_batch,
            batch_size=500,
        )
    assert raised.value.processed == 500
    assert raised.value.added == 500
    assert raised.value.removed == 1
    assert progress == [(0, 1001), (500, 1001)]
    assert {
        member["path"] for member in repo.get_image_set_members(set_id, limit=1001)
    } == set(matching_paths[:500])
    assert not repo.conn.in_transaction


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


def test_search_images_path_filter_treats_wildcards_as_literal(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    folder = tmp_path / "album_%_2026"
    wildcard_match = tmp_path / "album_XY_2026"
    folder.mkdir()
    wildcard_match.mkdir()
    expected_path = str(make_jpeg(folder / "inside.jpg"))
    sibling_path = str(make_jpeg(wildcard_match / "sibling.jpg"))
    for path in (expected_path, sibling_path):
        repo.upsert_image(path, Path(path).name, 1.0, 100, {}, Path(path).name)

    # Act
    rows = repo.search_images("", limit=10, offset=0, path_filter=[str(folder)])

    # Assert
    assert [row[1] for row in rows] == [expected_path]


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


def test_count_images_wildcard_special_query_falls_back_without_asterisk(
    repo: ImageIndexRepository,
    tmp_path: Path,
) -> None:
    # Arrange
    path = str(make_jpeg(tmp_path / "malongo.jpg"))
    repo.upsert_image(path, "malongo.jpg", 1.0, 100, {}, "malongo jpg")
    repo.commit()
    proxy = _SpecialQueryErrorOnceConnection(repo.conn)
    repo.conn = proxy

    # Act
    count = repo.count_images("malongo*")

    # Assert
    assert count == 1
    assert proxy.fts_queries[:2] == ["malongo*", "malongo"]


def test_search_images_wildcard_special_query_falls_back_without_asterisk(
    repo: ImageIndexRepository,
    tmp_path: Path,
) -> None:
    # Arrange
    path = str(make_jpeg(tmp_path / "malongo.jpg"))
    repo.upsert_image(path, "malongo.jpg", 1.0, 100, {}, "malongo jpg")
    repo.commit()
    proxy = _SpecialQueryErrorOnceConnection(repo.conn)
    repo.conn = proxy

    # Act
    rows = repo.search_images("malongo*", limit=10, offset=0)

    # Assert
    assert len(rows) == 1
    assert rows[0][2] == "malongo.jpg"
    assert proxy.fts_queries[:2] == ["malongo*", "malongo"]


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


def test_delete_missing_treats_wildcards_in_folder_as_literal(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    folder = tmp_path / "folder_a"
    wildcard_match = tmp_path / "folderXa"
    folder.mkdir()
    wildcard_match.mkdir()
    path_inside = str(make_jpeg(folder / "inside.jpg"))
    path_sibling = str(make_jpeg(wildcard_match / "sibling.jpg"))
    repo.upsert_image(path_inside, "inside.jpg", 1.0, 100, {}, "inside")
    repo.upsert_image(path_sibling, "sibling.jpg", 1.0, 100, {}, "sibling")
    repo.commit()

    # Act
    repo.delete_missing([], folder_roots=[str(folder)])
    rows = repo.search_images("", limit=10, offset=0)

    # Assert
    assert [row[1] for row in rows] == [path_sibling]


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


def test_get_format_counts_uses_last_filename_segment_as_extension(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    path = str(make_jpeg(tmp_path / "cb-01.07.16-name-.jpg"))
    repo.upsert_image(path, "cb-01.07.16-name-.jpg", 1.0, 100, {}, "sample")
    repo.commit()

    # Act
    counts = dict(repo.get_format_counts())

    # Assert
    assert counts == {"jpg": 1}


def test_init_db_backfills_ext_for_legacy_rows(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "legacy.db"
    conn = sqlcipher3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE images (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE images_fts USING fts5(path, filename, metadata_text);
        INSERT INTO images (path, filename, mtime, size, metadata_json)
        VALUES ('/tmp/legacy.jpeg', 'legacy.jpeg', 1.0, 100, '{}');
        INSERT INTO images_fts (rowid, path, filename, metadata_text)
        VALUES (1, '/tmp/legacy.jpeg', 'legacy.jpeg', 'legacy jpeg');
        """
    )
    conn.commit()
    conn.close()

    # Act
    repo = ImageIndexRepository(db_path, key="")
    counts = dict(repo.get_format_counts())
    ext_row = repo.conn.execute("SELECT ext FROM images WHERE id = 1").fetchone()
    repo.close()

    # Assert
    assert ext_row is not None
    assert ext_row[0] == "jpg"
    assert counts == {"jpg": 1}


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


def test_get_format_counts_by_paths_counts_only_selected_paths(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    path_a = str(make_jpeg(tmp_path / "a.jpg"))
    path_b = str(make_jpeg(tmp_path / "b.jpeg"))
    path_c = str(make_jpeg(tmp_path / "c.png"))
    repo.upsert_image(path_a, "a.jpg", 1.0, 100, {}, "a jpg")
    repo.upsert_image(path_b, "b.jpeg", 1.0, 100, {}, "b jpeg")
    repo.upsert_image(path_c, "c.png", 1.0, 100, {}, "c png")
    repo.commit()

    # Act
    counts = dict(repo.get_format_counts_by_paths([path_a, path_b]))

    # Assert
    assert counts == {"jpg": 2}


def test_get_year_counts_by_paths_counts_only_selected_paths(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange
    path_a = str(make_jpeg(tmp_path / "y2022.jpg"))
    path_b = str(make_jpeg(tmp_path / "y2023.jpg"))
    path_c = str(make_jpeg(tmp_path / "y2024.jpg"))
    repo.upsert_image(path_a, "y2022.jpg", 1.0, 100, {}, "y2022", captured_at=_JAN_2022)
    repo.upsert_image(path_b, "y2023.jpg", 1.0, 100, {}, "y2023", captured_at=_JAN_2023)
    repo.upsert_image(path_c, "y2024.jpg", 1.0, 100, {}, "y2024", captured_at=_JAN_2024)
    repo.commit()

    # Act
    counts = dict(repo.get_year_counts_by_paths([path_a, path_c]))

    # Assert
    assert counts == {2022: 1, 2024: 1}


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


# ── pixel counts ─────────────────────────────────────────────────────────────


def test_get_image_pixel_counts_for_paths_returns_only_requested_paths(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    dims = {"File:ImageWidth": "6000", "File:ImageHeight": "4000"}
    repo.upsert_image("/photos/a.tif", "a.tif", 1.0, 100, dims, "a")
    repo.upsert_image("/photos/b.tif", "b.tif", 1.0, 100, dims, "b")
    repo.commit()

    # Act
    counts = repo.get_image_pixel_counts_for_paths(["/photos/b.tif"])

    # Assert
    assert counts == {"/photos/b.tif": 24_000_000}


def test_get_image_pixel_counts_for_paths_more_than_one_chunk_returns_all(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    dims = {"File:ImageWidth": "10", "File:ImageHeight": "20"}
    paths = [f"/photos/img{i}.jpg" for i in range(1_201)]
    for path in paths:
        repo.upsert_image(path, Path(path).name, 1.0, 100, dims, path)
    repo.commit()

    # Act
    counts = repo.get_image_pixel_counts_for_paths(paths)

    # Assert
    assert len(counts) == len(paths)
    assert set(counts.values()) == {200}


def test_get_image_pixel_counts_for_paths_without_dimensions_omits_path(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    repo.upsert_image("/photos/c.jpg", "c.jpg", 1.0, 100, {"Make": "Canon"}, "c")
    repo.commit()

    # Act
    counts = repo.get_image_pixel_counts_for_paths(["/photos/c.jpg", "/photos/missing.jpg"])

    # Assert
    assert counts == {}
