from __future__ import annotations

from pathlib import Path

import pytest
import sqlcipher3

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance


def _tag(
    concept_id: str = "loc-tgm:tgm000001",
    label: str = "Red deer",
) -> ImageTag:
    return ImageTag(
        concept_id=concept_id,
        label=label,
        category="subject",
        provenance=TagProvenance(
            method="manual",
            accepted_at="2026-08-09T12:30:00Z",
            vocabulary_checksum="sha256:tgm-snapshot",
        ),
    )


def _sidecar(*tags: ImageTag, free_tags: tuple[str, ...] = ()) -> ImageSidecar:
    return ImageSidecar(
        source=SidecarSource(filename="photo.jpg", size=100, mtime_ns=1_000),
        updated_at="2026-08-09T12:30:00Z",
        tags=tags,
        free_tags=free_tags,
    )


def _replace_tags(
    repo: ImageIndexRepository,
    image_path: str,
    sidecar: ImageSidecar,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> None:
    repo.replace_accepted_tags_and_sidecar_state(
        image_path,
        sidecar,
        sidecar_path=f"{image_path}.sidecar.json",
        sidecar_mtime_ns=2_000,
        sidecar_size=500,
        sidecar_checksum="sha256:sidecar",
        sync_status="synced",
        aliases=aliases,
    )


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
    first_repo = ImageIndexRepository(db_path)
    first_results = first_repo.search_images("Hasselblad", limit=10, offset=0)
    columns = [
        row[1]
        for row in first_repo.conn.execute("PRAGMA table_info(images_fts)").fetchall()
    ]
    first_repo.close()
    second_repo = ImageIndexRepository(db_path)
    second_results = second_repo.search_images("Hasselblad", limit=10, offset=0)
    second_repo.close()

    # Assert
    assert columns == ["path", "filename", "metadata_text", "tags_text"]
    assert [row[2] for row in first_results] == ["photo.jpg"]
    assert [row[2] for row in second_results] == ["photo.jpg"]


def test_replace_tags_persists_sidecar_state_and_round_trips_tags(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    tag = _tag()
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")

    # Act
    _replace_tags(repo, image_path, _sidecar(tag))
    stored_tags = repo.get_accepted_tags(image_path)
    state = repo.conn.execute(
        "SELECT sidecar_path, mtime_ns, size, checksum, schema_version, sync_status, error "
        "FROM image_sidecar_state"
    ).fetchone()

    # Assert
    assert stored_tags == (tag,)
    assert state == (
        f"{image_path}.sidecar.json",
        2_000,
        500,
        "sha256:sidecar",
        1,
        "synced",
        None,
    )


def test_replace_tags_preserves_exif_search_and_enables_tag_search(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Hasselblad")

    # Act
    _replace_tags(repo, image_path, _sidecar(_tag()))

    # Assert
    assert repo.count_images("Hasselblad") == 1
    assert repo.count_images("deer") == 1
    assert repo.count_images("tgm000001") == 1
    assert repo.count_images("loc-tgm") == 1
    assert repo.count_images("subject") == 1


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


def test_replace_tags_aliases_are_searchable(repo: ImageIndexRepository) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    tag = _tag()
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")

    # Act
    _replace_tags(
        repo,
        image_path,
        _sidecar(tag),
        aliases={tag.concept_id: ("Cervus elaphus", "wapiti")},
    )

    # Assert
    assert repo.count_images('"Cervus elaphus"') == 1
    assert repo.count_images("wapiti") == 1


def test_clear_tags_and_sidecar_state_clears_tag_search_but_preserves_exif_search(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Hasselblad")
    _replace_tags(repo, image_path, _sidecar(_tag()))

    # Act
    repo.clear_accepted_tags_and_sidecar_state(image_path)

    # Assert
    assert repo.get_accepted_tags(image_path) == ()
    assert repo.count_images("deer") == 0
    assert repo.count_images("Hasselblad") == 1


def test_image_reupsert_preserves_tag_search(repo: ImageIndexRepository) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(repo, image_path, _sidecar(_tag()))

    # Act
    repo.upsert_image(image_path, "photo.jpg", 2.0, 200, {}, "Make Nikon")

    # Assert
    assert repo.count_images("deer") == 1
    assert repo.count_images("Nikon") == 1
    assert repo.count_images("Canon") == 0


def test_replace_tags_replaces_duplicate_concept_instead_of_accumulating_rows(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(repo, image_path, _sidecar(_tag(label="Old label")))

    # Act
    replacement = _tag(label="New label")
    _replace_tags(repo, image_path, _sidecar(replacement))

    # Assert
    assert repo.get_accepted_tags(image_path) == (replacement,)
    assert repo.count_images("Old") == 0
    assert repo.count_images("New") == 1


def test_replace_tags_constraint_failure_rolls_back_tags_state_and_fts(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    original = _tag(label="Original label")
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(repo, image_path, _sidecar(original))

    # Act / Assert
    with pytest.raises(sqlcipher3.IntegrityError):
        _replace_tags(
            repo,
            image_path,
            _sidecar(_tag(label="Replacement label")),
            aliases={original.concept_id: ("duplicate", "duplicate")},
        )
    assert repo.get_accepted_tags(image_path) == (original,)
    assert repo.count_images("Original") == 1
    assert repo.count_images("Replacement") == 0


def test_get_marked_concept_counts_aggregates_each_concept_across_marked_images(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    first_path = "/photos/first.jpg"
    second_path = "/photos/second.jpg"
    third_path = "/photos/third.jpg"
    shared_tag = _tag()
    other_tag = _tag("loc-tgm:tgm000002", "Forests")
    for path in (first_path, second_path, third_path):
        repo.upsert_image(path, Path(path).name, 1.0, 100, {}, Path(path).name)
    _replace_tags(repo, first_path, _sidecar(shared_tag, other_tag))
    _replace_tags(repo, second_path, _sidecar(shared_tag))
    _replace_tags(repo, third_path, _sidecar(shared_tag))
    repo.mark_images((first_path, second_path), True)

    # Act
    counts = repo.get_marked_concept_counts()

    # Assert
    assert counts == {
        "loc-tgm:tgm000001": 2,
        "loc-tgm:tgm000002": 1,
    }


def test_refresh_accepted_tag_aliases_updates_fts_without_changing_tag_snapshot(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    tag = _tag()
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(
        repo,
        image_path,
        _sidecar(tag),
        aliases={tag.concept_id: ("Cervidae",)},
    )

    # Act
    refreshed_count = repo.refresh_accepted_tag_aliases(
        {tag.concept_id: ("Wapiti",)}
    )

    # Assert
    assert refreshed_count == 1
    assert repo.get_accepted_tags(image_path) == (tag,)
    assert repo.count_images("Cervidae") == 0
    assert repo.count_images("Wapiti") == 1


def test_delete_missing_cascades_tag_and_sidecar_cache_rows(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(repo, image_path, _sidecar(_tag()))

    # Act
    repo.delete_missing([])

    # Assert
    assert repo.conn.execute("SELECT COUNT(*) FROM accepted_image_tags").fetchone()[0] == 0
    assert repo.conn.execute("SELECT COUNT(*) FROM image_sidecar_state").fetchone()[0] == 0


def test_clear_all_rows_cascades_tag_and_sidecar_cache_rows(
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = "/photos/photo.jpg"
    repo.upsert_image(image_path, "photo.jpg", 1.0, 100, {}, "Make Canon")
    _replace_tags(repo, image_path, _sidecar(_tag()))

    # Act
    repo.clear_all_rows()

    # Assert
    assert repo.conn.execute("SELECT COUNT(*) FROM accepted_image_tags").fetchone()[0] == 0
    assert repo.conn.execute("SELECT COUNT(*) FROM image_sidecar_state").fetchone()[0] == 0
    assert repo.count_images("deer") == 0