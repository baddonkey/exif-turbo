"""Tests for folder-enable/disable filtering in ImageIndexRepository.

Verifies that ``restrict_to_enabled_folders=True`` correctly uses the
``image_folders`` join table to show/hide images based on the ``enabled``
flag on ``indexed_folders``.  The key case is a parent folder disabled while
a child sub-folder is enabled — the child's images must still be visible.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository
from tests.conftest import make_jpeg


def _insert_folder(db: ImageIndexRepository, path: str, enabled: int) -> int:
    """Insert a row into indexed_folders and return its id."""
    cur = db.conn.execute(
        "INSERT INTO indexed_folders (path, display_name, enabled, status) VALUES (?, ?, ?, ?)",
        (path, os.path.basename(path), enabled, "indexed"),
    )
    db.conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


@pytest.fixture
def repo_with_folders(tmp_path: Path) -> ImageIndexRepository:
    """DB with images in 'alpha' (enabled) and 'beta' (disabled) folders.

    alpha/        — folder_id=1, enabled=1, 3 Canon images
    beta/         — folder_id=2, enabled=0, 2 Nikon images
    """
    db = ImageIndexRepository(tmp_path / "test.db", key="")

    # indexed_folders table lives in the same file for tests
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS indexed_folders ("
        "id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, "
        "display_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, "
        "status TEXT NOT NULL DEFAULT 'pending'"
        ")"
    )
    db.conn.commit()

    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()

    alpha_id = _insert_folder(db, str(alpha), enabled=1)
    beta_id = _insert_folder(db, str(beta), enabled=0)

    for i in range(3):
        p = make_jpeg(alpha / f"alpha_{i}.jpg")
        db.upsert_image(
            str(p), p.name, float(i), i * 100,
            {"Make": "Canon"}, f"Canon alpha_{i} jpg",
            folder_id=alpha_id,
        )
    for i in range(2):
        p = make_jpeg(beta / f"beta_{i}.jpg")
        db.upsert_image(
            str(p), p.name, float(i), i * 100,
            {"Make": "Nikon"}, f"Nikon beta_{i} jpg",
            folder_id=beta_id,
        )

    yield db
    db.close()


@pytest.fixture
def repo_with_parent_child(tmp_path: Path) -> ImageIndexRepository:
    """DB that reproduces the parent-disabled / child-enabled conflict.

    parent/         — folder_id=1, enabled=0, 1 image
    parent/child/   — folder_id=2, enabled=1, 1 image
    """
    db = ImageIndexRepository(tmp_path / "test.db", key="")

    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS indexed_folders ("
        "id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, "
        "display_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, "
        "status TEXT NOT NULL DEFAULT 'pending'"
        ")"
    )
    db.conn.commit()

    parent = tmp_path / "parent"
    child = parent / "child"
    parent.mkdir()
    child.mkdir()

    parent_id = _insert_folder(db, str(parent), enabled=0)
    child_id = _insert_folder(db, str(child), enabled=1)

    p1 = make_jpeg(parent / "parent_img.jpg")
    db.upsert_image(
        str(p1), p1.name, 1.0, 100,
        {"Make": "Sony"}, "Sony parent_img jpg",
        folder_id=parent_id,
    )

    p2 = make_jpeg(child / "child_img.jpg")
    db.upsert_image(
        str(p2), p2.name, 2.0, 200,
        {"Make": "Fuji"}, "Fuji child_img jpg",
        folder_id=child_id,
    )

    yield db
    db.close()


@pytest.fixture
def repo_with_folders_without_links(tmp_path: Path) -> ImageIndexRepository:
    """DB with indexed_folders rows but legacy images missing image_folders links."""
    db = ImageIndexRepository(tmp_path / "test.db", key="")

    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS indexed_folders ("
        "id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, "
        "display_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, "
        "status TEXT NOT NULL DEFAULT 'pending'"
        ")"
    )
    db.conn.commit()

    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()

    _insert_folder(db, str(alpha), enabled=1)
    _insert_folder(db, str(beta), enabled=0)

    # Intentionally omit folder_id to simulate legacy rows with no join links.
    p1 = make_jpeg(alpha / "alpha_marked.jpg")
    db.upsert_image(
        str(p1), p1.name, 1.0, 100,
        {"Make": "Canon"}, "Canon alpha_marked jpg",
        folder_id=None,
    )
    p2 = make_jpeg(beta / "beta_marked.jpg")
    db.upsert_image(
        str(p2), p2.name, 2.0, 200,
        {"Make": "Nikon"}, "Nikon beta_marked jpg",
        folder_id=None,
    )
    db.conn.execute("UPDATE images SET marked = 1")
    db.conn.commit()

    yield db
    db.close()


# ── restrict_to_enabled_folders in search_images ────────────────────────────


def test_search_images_no_filter_returns_all_images(
    repo_with_folders: ImageIndexRepository,
) -> None:
    rows = repo_with_folders.search_images("", limit=20, offset=0)
    assert len(rows) == 5


def test_search_images_restrict_hides_disabled_folder_images(
    repo_with_folders: ImageIndexRepository,
) -> None:
    # Act — only enabled folder (alpha) images should appear
    rows = repo_with_folders.search_images(
        "", limit=20, offset=0, restrict_to_enabled_folders=True
    )

    # Assert — only 3 alpha images visible
    assert len(rows) == 3
    for row in rows:
        assert "alpha" in row[2]


def test_search_images_restrict_returns_empty_when_all_disabled(
    repo_with_folders: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange — disable alpha too
    repo_with_folders.conn.execute(
        "UPDATE indexed_folders SET enabled = 0 WHERE path = ?",
        (str(tmp_path / "alpha"),),
    )
    repo_with_folders.conn.commit()

    rows = repo_with_folders.search_images(
        "", limit=20, offset=0, restrict_to_enabled_folders=True
    )
    assert len(rows) == 0


def test_search_images_fts_restrict_filters_correctly(
    repo_with_folders: ImageIndexRepository,
) -> None:
    # Canon images are only in the enabled alpha folder — must be found
    rows = repo_with_folders.search_images(
        "Canon", limit=20, offset=0, restrict_to_enabled_folders=True
    )
    assert len(rows) == 3


def test_search_images_fts_restrict_hides_disabled_folder_fts_results(
    repo_with_folders: ImageIndexRepository,
) -> None:
    # Nikon images are only in the disabled beta folder — must be hidden
    rows = repo_with_folders.search_images(
        "Nikon", limit=20, offset=0, restrict_to_enabled_folders=True
    )
    assert len(rows) == 0


def test_search_images_parent_disabled_child_enabled_shows_child(
    repo_with_parent_child: ImageIndexRepository,
) -> None:
    """Images in an enabled child folder are visible even when parent is disabled.

    This is the key regression test for the bug fixed by the image_folders
    join table — the old excluded_paths approach would hide child images
    whenever the parent path prefix was in the exclusion list.
    """
    rows = repo_with_parent_child.search_images(
        "", limit=20, offset=0, restrict_to_enabled_folders=True
    )

    filenames = [row[2] for row in rows]
    assert "child_img.jpg" in filenames
    assert "parent_img.jpg" not in filenames


def test_search_images_restrict_without_links_uses_enabled_path_fallback(
    repo_with_folders_without_links: ImageIndexRepository,
) -> None:
    # Arrange / Act
    rows = repo_with_folders_without_links.search_images(
        "", limit=20, offset=0, restrict_to_enabled_folders=True
    )

    # Assert
    assert len(rows) == 1
    assert rows[0][2] == "alpha_marked.jpg"


def test_search_images_marked_only_without_links_respects_enabled_folders(
    repo_with_folders_without_links: ImageIndexRepository,
) -> None:
    # Arrange / Act
    rows = repo_with_folders_without_links.search_images(
        "",
        limit=20,
        offset=0,
        marked_only=True,
        restrict_to_enabled_folders=True,
    )

    # Assert
    assert len(rows) == 1
    assert rows[0][2] == "alpha_marked.jpg"


# ── restrict_to_enabled_folders in count_images ─────────────────────────────


def test_count_images_no_filter_returns_total(
    repo_with_folders: ImageIndexRepository,
) -> None:
    assert repo_with_folders.count_images("") == 5


def test_count_images_restrict_counts_only_enabled_folders(
    repo_with_folders: ImageIndexRepository,
) -> None:
    count = repo_with_folders.count_images("", restrict_to_enabled_folders=True)
    assert count == 3


def test_count_images_fts_restrict_counts_correctly(
    repo_with_folders: ImageIndexRepository,
) -> None:
    # Nikon images are in the disabled folder — count must be 0
    count = repo_with_folders.count_images("Nikon", restrict_to_enabled_folders=True)
    assert count == 0


def test_get_marked_paths_restrict_excludes_disabled_folder_marks(
    repo_with_folders: ImageIndexRepository,
) -> None:
    # Arrange
    repo_with_folders.conn.execute("UPDATE images SET marked = 1")
    repo_with_folders.conn.commit()

    # Act
    paths = repo_with_folders.get_marked_paths(restrict_to_enabled_folders=True)

    # Assert
    assert len(paths) == 3
    assert all("alpha" in p for p in paths)


def test_get_marked_metadata_restrict_excludes_disabled_folder_marks(
    repo_with_folders: ImageIndexRepository,
) -> None:
    # Arrange
    repo_with_folders.conn.execute("UPDATE images SET marked = 1")
    repo_with_folders.conn.commit()

    # Act
    records = repo_with_folders.get_marked_metadata(
        restrict_to_enabled_folders=True,
    )

    # Assert
    assert len(records) == 3
    assert all("alpha" in rec["path"] for rec in records)


# ── delete_by_path_prefix ────────────────────────────────────────────────────


def test_delete_by_path_prefix_removes_only_matching_images(
    repo_with_folders: ImageIndexRepository, tmp_path: Path
) -> None:
    # Act
    repo_with_folders.delete_by_path_prefix(str(tmp_path / "beta"))

    # Assert
    rows = repo_with_folders.search_images("", limit=20, offset=0)
    assert len(rows) == 3
    for row in rows:
        assert "alpha" in row[2]


def test_delete_by_path_prefix_removes_from_fts_index(
    repo_with_folders: ImageIndexRepository, tmp_path: Path
) -> None:
    # Act
    repo_with_folders.delete_by_path_prefix(str(tmp_path / "beta"))

    # Assert — Nikon images (from beta) no longer searchable
    rows = repo_with_folders.search_images("Nikon", limit=20, offset=0)
    assert len(rows) == 0


def test_delete_by_path_prefix_nonexistent_path_does_not_raise(
    repo_with_folders: ImageIndexRepository, tmp_path: Path
) -> None:
    repo_with_folders.delete_by_path_prefix(str(tmp_path / "nonexistent"))
    assert repo_with_folders.count_images("") == 5


# ── delete_orphans_under_prefix ──────────────────────────────────────────────


def test_delete_orphans_under_prefix_removes_parent_only_images(
    repo_with_parent_child: ImageIndexRepository, tmp_path: Path
) -> None:
    """Removing the parent folder deletes only its own images, not child images.

    This is the regression test for the bug where delete_by_path_prefix was
    used unconditionally, wiping child-folder images that still had valid
    folder associations.
    """
    parent = tmp_path / "parent"
    child = parent / "child"

    # Arrange — simulate removeIndexedFolder: remove parent associations first
    parent_id = repo_with_parent_child.conn.execute(
        "SELECT id FROM indexed_folders WHERE path = ?", (str(parent),)
    ).fetchone()[0]
    repo_with_parent_child.delete_folder_associations(parent_id)

    # Act — delete only orphans (images with no remaining associations)
    repo_with_parent_child.delete_orphans_under_prefix(str(parent))

    # Assert — child image survives; parent-root image is gone
    rows = repo_with_parent_child.search_images("", limit=20, offset=0)
    filenames = [row[2] for row in rows]
    assert "child_img.jpg" in filenames
    assert "parent_img.jpg" not in filenames


def test_delete_orphans_under_prefix_removes_all_when_no_associations(
    repo_with_folders: ImageIndexRepository, tmp_path: Path
) -> None:
    # Arrange — strip all associations from beta images
    beta_id = repo_with_folders.conn.execute(
        "SELECT id FROM indexed_folders WHERE path = ?", (str(tmp_path / "beta"),)
    ).fetchone()[0]
    repo_with_folders.delete_folder_associations(beta_id)

    # Act
    repo_with_folders.delete_orphans_under_prefix(str(tmp_path / "beta"))

    # Assert — beta images gone, alpha images intact
    assert repo_with_folders.count_images("") == 3
