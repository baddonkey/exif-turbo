from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pytest
import sqlcipher3

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.tagging.sidecar_repository import FilesystemSidecarRepository
from exif_turbo.tagging.sidecar_synchronizer import SidecarSynchronizer


def _sidecar(*, free_tags: tuple[str, ...] = ()) -> ImageSidecar:
    return ImageSidecar(
        source=SidecarSource(filename="photo.jpg", size=100, mtime_ns=1_000),
        updated_at="2026-08-09T12:30:00Z",
        free_tags=free_tags,
    )


def _replace_tags(
    repo: ImageIndexRepository,
    image_path: str,
    sidecar: ImageSidecar,
) -> None:
    repo.replace_custom_tags_and_sidecar_state(
        image_path,
        sidecar,
        sidecar_path=f"{image_path}.sidecar.json",
        sidecar_mtime_ns=2_000,
        sidecar_size=500,
        sidecar_checksum="sha256:sidecar",
        sync_status="synced",
    )


def test_description_upgrade_resynchronizes_previously_unknown_field(tmp_path: Path) -> None:
    # Arrange
    database = tmp_path / "index.db"
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"original")
    sidecars = FilesystemSidecarRepository()
    sidecars.write(
        image_path, replace(_sidecar(), description="Previouslyunknowncaption"), None
    )
    repository = ImageIndexRepository(database, key="")
    repository.upsert_image(str(image_path), image_path.name, 0, 8, {}, "")
    SidecarSynchronizer(repository, sidecars).synchronize([str(image_path)])
    repository.conn.execute("DROP TABLE image_descriptions")
    repository.conn.execute("UPDATE images_fts SET tags_text = ''")
    repository.conn.commit()
    repository.close()

    # Act
    repository = ImageIndexRepository(database, key="")
    result = SidecarSynchronizer(repository, sidecars).synchronize([str(image_path)])

    # Assert
    assert result.error_count == 0
    assert repository.get_description(str(image_path)) == "Previouslyunknowncaption"
    assert repository.count_images("Previouslyunknowncaption") == 1
    repository.close()


def test_init_db_legacy_fts_migration_preserves_metadata_search_and_is_idempotent(
    tmp_path: Path,
) -> None:
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
        INSERT INTO images (id, path, filename, mtime, size, metadata_json)
        VALUES (1, '/photos/photo.jpg', 'photo.jpg', 1.0, 100, '{}');
        INSERT INTO images_fts (rowid, path, filename, metadata_text)
        VALUES (1, '/photos/photo.jpg', 'photo.jpg', 'Make Hasselblad');
        """
    )
    conn.commit()
    conn.close()

    # Act
    first_repo = ImageIndexRepository(db_path, key="")
    first_results = first_repo.search_images("Hasselblad", limit=10, offset=0)
    columns = [
        row[1]
        for row in first_repo.conn.execute("PRAGMA table_info(images_fts)").fetchall()
    ]
    first_repo.close()
    second_repo = ImageIndexRepository(db_path, key="")
    second_results = second_repo.search_images("Hasselblad", limit=10, offset=0)
    second_repo.close()

    # Assert
    assert columns == ["path", "filename", "metadata_text", "tags_text"]
    assert [row[2] for row in first_results] == ["photo.jpg"]
    assert [row[2] for row in second_results] == ["photo.jpg"]


def test_init_db_backfills_structured_search_indexes_from_cached_data(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"not read by migration")
    sidecar_path = Path(f"{image_path}.sidecar.json")
    sidecar = replace(
        _sidecar(free_tags=("deer",)),
        description="autumn custom notes",
        excluded_embedded_tags=("Landscape",),
        exclude_all_embedded_tags=True,
    )
    FilesystemSidecarRepository().write(image_path, sidecar, None)
    original_sidecar = sidecar_path.read_bytes()
    db_path = tmp_path / "legacy-search.db"
    connection = sqlcipher3.connect(str(db_path))
    connection.executescript(
        """
        CREATE TABLE images (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE image_sidecar_state (
            image_id INTEGER PRIMARY KEY,
            sidecar_path TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            checksum TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            sync_status TEXT NOT NULL,
            error TEXT
        );
        CREATE TABLE image_free_tags (
            image_id INTEGER NOT NULL,
            normalized_label TEXT NOT NULL,
            position INTEGER NOT NULL,
            display_label TEXT NOT NULL,
            PRIMARY KEY (image_id, normalized_label)
        );
        CREATE TABLE image_descriptions (
            image_id INTEGER PRIMARY KEY,
            description TEXT NOT NULL
        );
        """,
    )
    connection.execute(
        "INSERT INTO images (id, path, filename, mtime, size, metadata_json) "
        "VALUES (1, ?, 'photo.jpg', 1.0, 100, ?)",
        (
            str(image_path),
            '{"IPTC:Keywords": ["forest", "Landscape"], '
            '"XMP-dc:Description": "Schurzwald dusk"}',
        ),
    )
    connection.execute(
        "INSERT INTO image_sidecar_state ("
        "image_id, sidecar_path, mtime_ns, size, checksum, schema_version, "
        "sync_status, error) VALUES (1, ?, 1, 1, 'cached', 1, 'synced', NULL)",
        (str(sidecar_path),),
    )
    connection.execute(
        "INSERT INTO image_free_tags "
        "(image_id, normalized_label, position, display_label) "
        "VALUES (1, 'deer', 0, 'deer')"
    )
    connection.execute(
        "INSERT INTO image_descriptions (image_id, description) "
        "VALUES (1, 'autumn custom notes')"
    )
    connection.commit()
    connection.close()

    repo = ImageIndexRepository(db_path, key="")

    embedded = repo.conn.execute(
        "SELECT normalized_label FROM image_embedded_tags "
        "WHERE image_id = 1 ORDER BY normalized_label"
    ).fetchall()
    exclusions = repo.conn.execute(
        "SELECT normalized_label FROM image_tag_exclusions WHERE image_id = 1"
    ).fetchall()
    assert embedded == [("forest",), ("landscape",)]
    assert exclusions == [("landscape",)]
    assert repo.conn.execute(
        "SELECT exclude_all_embedded_tags FROM image_sidecar_state WHERE image_id = 1"
    ).fetchone()[0] == 1
    assert repo.migration_completed("structured-search-index-v1")
    assert sidecar_path.read_bytes() == original_sidecar
    repo.close()


def test_replace_tags_free_tags_are_searchable_and_remembered(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Hasselblad")

    # Act
    _replace_tags(
        repo,
        image_path,
        _sidecar(free_tags=("Summer 2026", "Family")),
    )

    # Assert
    assert repo.get_free_tags(image_path) == ("Summer 2026", "Family")
    assert repo.count_images('"Summer 2026"') == 1
    assert repo.search_free_tags("fam") == ("Family",)
    assert repo.count_images("Hasselblad") == 1


def test_upsert_embedded_metadata_updates_normalized_search_indexes(
    repo: ImageIndexRepository,
) -> None:
    image_path = "/photos/metadata.jpg"

    repo.upsert_image(
        image_path,
        "metadata.jpg",
        1.0,
        100,
        {
            "IPTC:Keywords": ["Forest", "Birdhouse"],
            "XMP-dc:Description": "Schurzwald at dusk; Straße",
        },
        "",
    )

    rows = repo.conn.execute(
        "SELECT normalized_label, display_label FROM image_embedded_tags "
        "WHERE image_id = (SELECT id FROM images WHERE path = ?) "
        "ORDER BY normalized_label",
        (image_path,),
    ).fetchall()
    description_match = repo.conn.execute(
        "SELECT d.image_id FROM image_description_fts f "
        "JOIN image_description_texts d ON d.id = f.rowid "
        "WHERE image_description_fts MATCH ?",
        ('"hurz"',),
    ).fetchone()

    assert rows == [("birdhouse", "Birdhouse"), ("forest", "Forest")]
    assert description_match is not None
    assert int(description_match[0]) == repo.conn.execute(
        "SELECT id FROM images WHERE path = ?", (image_path,)
    ).fetchone()[0]
    assert repo.count_images('embedded-tags:="forest"') == 1
    assert repo.count_images('description:="hurz"') == 1
    assert repo.count_images('description:="STRASSE"') == 1


def test_sidecar_cache_updates_exclusions_custom_description_and_cleanup(
    repo: ImageIndexRepository,
) -> None:
    image_path = "/photos/sidecar.jpg"
    repo.upsert_image(
        image_path,
        "photo.jpg",
        1.0,
        100,
        {"IPTC:Keywords": ["Landscape"]},
        "",
    )
    sidecar = replace(
        _sidecar(free_tags=("Autumn",)),
        description="Schurzwald notes",
        excluded_embedded_tags=("Landscape",),
        exclude_all_embedded_tags=True,
    )

    _replace_tags(repo, image_path, sidecar)

    image_id = int(
        repo.conn.execute(
            "SELECT id FROM images WHERE path = ?", (image_path,)
        ).fetchone()[0]
    )
    assert repo.conn.execute(
        "SELECT normalized_label FROM image_tag_exclusions WHERE image_id = ?",
        (image_id,),
    ).fetchall() == [("landscape",)]
    assert repo.conn.execute(
        "SELECT exclude_all_embedded_tags FROM image_sidecar_state "
        "WHERE image_id = ?",
        (image_id,),
    ).fetchone()[0] == 1
    assert repo.conn.execute(
        "SELECT image_id FROM image_description_fts f "
        "JOIN image_description_texts d ON d.id = f.rowid "
        "WHERE image_description_fts MATCH ?",
        ('"notes"',),
    ).fetchone()[0] == image_id

    repo.clear_custom_tags_and_sidecar_state(image_path)

    assert repo.conn.execute(
        "SELECT COUNT(*) FROM image_tag_exclusions WHERE image_id = ?", (image_id,)
    ).fetchone()[0] == 0
    assert repo.conn.execute(
        "SELECT COUNT(*) FROM image_description_texts "
        "WHERE image_id = ? AND source = 'custom'",
        (image_id,),
    ).fetchone()[0] == 0


def test_search_effective_tags_matches_all_exact_values_across_sources(
    repo: ImageIndexRepository,
) -> None:
    first_path = "/photos/first.jpg"
    second_path = "/photos/second.jpg"
    repo.upsert_image(
        first_path,
        "first.jpg",
        1.0,
        100,
        {"IPTC:Keywords": ["Forest", "wildlife", "landscape"]},
        "",
        captured_at=1_735_689_600,
    )
    repo.upsert_image(
        second_path,
        "second.jpg",
        1.0,
        100,
        {"IPTC:Keywords": ["birdhouse"]},
        "",
    )
    repo.upsert_image(
        "/photos/empty.jpg",
        "empty.jpg",
        1.0,
        100,
        {"IPTC:Keywords": []},
        "",
    )
    all_excluded_path = "/photos/all-excluded.jpg"
    repo.upsert_image(
        all_excluded_path,
        "all-excluded.jpg",
        1.0,
        100,
        {"IPTC:Keywords": ["mountain"]},
        "",
    )
    first_sidecar = replace(
        _sidecar(free_tags=("forest", "deer", "autumn", "Café au lait")),
        excluded_embedded_tags=("Landscape",),
    )
    _replace_tags(repo, first_path, first_sidecar)
    _replace_tags(repo, second_path, _sidecar(free_tags=("birdhouse",)))
    _replace_tags(
        repo,
        all_excluded_path,
        replace(
            _sidecar(free_tags=("compass",)),
            exclude_all_embedded_tags=True,
        ),
    )

    matching_paths = lambda query: [
        row[1] for row in repo.search_images(query, limit=20, offset=0)
    ]

    assert matching_paths('tags:="forest, deer"') == [first_path]
    assert matching_paths('tags:="deer, autumn"') == [first_path]
    assert matching_paths('tags:="forest, landscape"') == []
    assert matching_paths('tags:="bird"') == []
    assert matching_paths('tags:="birdhouse"') == [second_path]
    assert matching_paths('custom-tags:="bird"') == []
    assert matching_paths('tags:="empty"') == []
    assert matching_paths('tags:="Café au lait, café au lait"') == [first_path]
    assert matching_paths('embedded-tags:="forest"') == [first_path]
    assert matching_paths('custom-tags:="deer, autumn"') == [first_path]
    assert matching_paths('tags:="mountain"') == []
    assert matching_paths('embedded-tags:="mountain"') == []
    assert matching_paths('tags:="compass"') == [all_excluded_path]
    query = 'tags:="forest, deer"'
    image_id = int(
        repo.conn.execute(
            "SELECT id FROM images WHERE path = ?", (first_path,)
        ).fetchone()[0]
    )
    assert repo.count_images(query) == 1
    assert repo.get_matching_paths(query) == [first_path]
    assert repo.find_image_offset(image_id, query) == 0
    assert repo.get_year_counts(query) == [(2025, 1)]
    assert repo.get_format_counts(query) == [("jpg", 1)]
    assert repo.bulk_mark_images(True, query=query) == [first_path]
    assert repo.bulk_invert_images(query=query) == ([], [first_path])


def test_search_description_substrings_combine_with_fts_and_tag_filters(
    repo: ImageIndexRepository,
) -> None:
    image_path = "/photos/description.jpg"
    repo.upsert_image(
        image_path,
        "description.jpg",
        1.0,
        100,
        {
            "IPTC:Keywords": ["Forest"],
            "XMP-dc:Description": "Schurzwald at dusk",
        },
        "Mountains",
    )
    _replace_tags(
        repo,
        image_path,
        replace(
            _sidecar(free_tags=("deer",)),
            description="Abhurzung in the field notes",
        ),
    )

    assert repo.count_images('description:="HURZ"') == 1
    assert repo.count_images('description:="field"') == 1
    assert repo.count_images(
        'Mountains tags:="forest, deer" description:="hurz"'
    ) == 1
    assert repo.count_images('Mountains description:="missing"') == 0


def test_upsert_and_delete_refresh_structured_search_indexes(
    repo: ImageIndexRepository,
) -> None:
    image_path = "/photos/updated.jpg"
    repo.upsert_image(
        image_path,
        "updated.jpg",
        1.0,
        100,
        {"IPTC:Keywords": ["forest"], "XMP-dc:Description": "old caption"},
        "",
    )
    repo.upsert_image(
        image_path,
        "updated.jpg",
        2.0,
        100,
        {"IPTC:Keywords": ["bird"], "XMP-dc:Description": "new caption"},
        "",
    )

    assert repo.count_images('embedded-tags:="forest"') == 0
    assert repo.count_images('embedded-tags:="bird"') == 1
    assert repo.count_images('description:="old"') == 0
    assert repo.count_images('description:="new"') == 1

    repo.delete_missing([])

    assert repo.count_images('embedded-tags:="bird"') == 0
    assert repo.conn.execute(
        "SELECT COUNT(*) FROM image_description_texts"
    ).fetchone()[0] == 0


def test_structured_search_malformed_expression_raises_controlled_error(
    repo: ImageIndexRepository,
) -> None:
    with pytest.raises(ValueError, match="requires a quoted value"):
        repo.search_images("tags:=forest", limit=10, offset=0)


def test_description_search_falls_back_to_cached_text_without_trigram(
    repo: ImageIndexRepository,
) -> None:
    repo.upsert_image(
        "/photos/fallback.jpg",
        "fallback.jpg",
        1.0,
        100,
        {"XMP-dc:Description": "The Schurzwald at dusk"},
        "",
    )
    repo._description_trigram_available = False

    assert repo.count_images('description:="hurz"') == 1
    assert repo.count_images('description:="ss"') == 0


def test_large_synthetic_tag_collection_uses_label_lookup_index(
    repo: ImageIndexRepository,
) -> None:
    image_count = 2_500
    repo.upsert_images_batch(
        [
            (
                f"/photos/synthetic-{index:05}.jpg",
                f"synthetic-{index:05}.jpg",
                float(index),
                100,
                {"IPTC:Keywords": ["shared", f"subject-{index}"]},
                "",
                None,
                None,
            )
            for index in range(image_count)
        ]
    )

    count = repo.count_images('embedded-tags:="shared"')
    query_plan = repo.conn.execute(
        "EXPLAIN QUERY PLAN SELECT image_id FROM image_embedded_tags "
        "WHERE normalized_label IN (?)",
        ("shared",),
    ).fetchall()
    assert count == image_count
    assert any("idx_image_embedded_tags_label" in str(row[3]) for row in query_plan)
    if repo._description_trigram_available:
        description_plan = repo.conn.execute(
            "EXPLAIN QUERY PLAN SELECT rowid FROM image_description_fts "
            "WHERE image_description_fts MATCH ?",
            ('"caption"',),
        ).fetchall()
        assert any("VIRTUAL TABLE INDEX" in str(row[3]) for row in description_plan)


def test_remove_free_tag_from_image_keeps_catalog_suggestion(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "photo")
    _replace_tags(repo, image_path, _sidecar(free_tags=("Family",)))

    # Act
    _replace_tags(repo, image_path, _sidecar())

    # Assert
    assert repo.get_free_tags(image_path) == ()
    assert repo.count_images("Family") == 0
    assert repo.search_free_tags("family") == ("Family",)


def test_free_tag_catalog_preserves_first_remembered_spelling(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    first_path = "/photos/first.jpg"
    second_path = "/photos/second.jpg"
    for path in (first_path, second_path):
        repo.upsert_image(path, Path(path).name, 1.0, 100, {}, Path(path).name)
    _replace_tags(repo, first_path, _sidecar(free_tags=("Family",)))

    # Act
    _replace_tags(repo, second_path, _sidecar(free_tags=("family",)))

    # Assert
    assert repo.resolve_free_tag(" FAMILY ") == "Family"


def test_clear_all_rows_clears_remembered_free_tag_catalog(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "photo")
    _replace_tags(repo, image_path, _sidecar(free_tags=("Family",)))

    # Act
    repo.clear_all_rows()

    # Assert
    assert repo.search_free_tags("") == ()


def test_clear_custom_tags_and_sidecar_state_preserves_exif_search(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Hasselblad")
    _replace_tags(repo, image_path, _sidecar(free_tags=("Family",)))

    # Act
    repo.clear_custom_tags_and_sidecar_state(image_path)

    # Assert
    assert repo.get_free_tags(image_path) == ()
    assert repo.count_images("Family") == 0
    assert repo.count_images("Hasselblad") == 1


def test_image_reupsert_preserves_free_tag_search(repo: ImageIndexRepository) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(repo, image_path, _sidecar(free_tags=("Family",)))

    # Act
    repo.upsert_image(image_path, "photo.jpg", 2.0, 200, {}, "Make Nikon")

    # Assert
    assert repo.count_images("Family") == 1
    assert repo.count_images("Nikon") == 1
    assert repo.count_images("Canon") == 0


def test_delete_missing_cascades_free_tag_and_sidecar_cache_rows(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(repo, image_path, _sidecar(free_tags=("Family",)))

    # Act
    repo.delete_missing([])

    # Assert
    assert repo.conn.execute("SELECT COUNT(*) FROM image_free_tags").fetchone()[0] == 0
    assert repo.conn.execute("SELECT COUNT(*) FROM image_sidecar_state").fetchone()[0] == 0


def test_clear_all_rows_cascades_free_tag_and_sidecar_cache_rows(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(repo, image_path, _sidecar(free_tags=("Family",)))

    # Act
    repo.clear_all_rows()

    # Assert
    assert repo.conn.execute("SELECT COUNT(*) FROM image_free_tags").fetchone()[0] == 0
    assert repo.conn.execute("SELECT COUNT(*) FROM image_sidecar_state").fetchone()[0] == 0
    assert repo.count_images("Family") == 0