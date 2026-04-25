from __future__ import annotations

import os
from pathlib import Path

import pytest

from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository


@pytest.fixture
def folder_repo(tmp_path: Path) -> IndexedFolderRepository:
    return IndexedFolderRepository(tmp_path / "test.db", key="")


# ── add ───────────────────────────────────────────────────────────────────────


def test_add_folder_returns_indexed_folder_with_new_status(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    folder_path = str(tmp_path / "photos")

    # Act
    result = folder_repo.add(folder_path)

    # Assert
    assert result.id > 0
    assert os.path.normpath(result.path) == os.path.normpath(folder_path)
    assert result.display_name == "photos"
    assert result.enabled is True
    assert result.recursive is True
    assert result.status == "new"
    assert result.image_count == 0


def test_add_folder_with_custom_display_name(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    folder_path = str(tmp_path / "photos")

    # Act
    result = folder_repo.add(folder_path, display_name="My Photos")

    # Assert
    assert result.display_name == "My Photos"


def test_add_duplicate_path_is_idempotent(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    folder_path = str(tmp_path / "photos")
    first = folder_repo.add(folder_path)

    # Act — inserting same path again should not raise and return same record
    second = folder_repo.add(folder_path)

    # Assert
    assert first.id == second.id
    assert len(folder_repo.get_all()) == 1


# ── get_all ───────────────────────────────────────────────────────────────────


def test_get_all_empty_db_returns_empty_list(
    folder_repo: IndexedFolderRepository,
) -> None:
    assert folder_repo.get_all() == []


def test_get_all_returns_all_added_folders(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    folder_repo.add(str(tmp_path / "a"))
    folder_repo.add(str(tmp_path / "b"))

    # Act
    result = folder_repo.get_all()

    # Assert
    assert len(result) == 2


# ── get_by_id ─────────────────────────────────────────────────────────────────


def test_get_by_id_existing_folder_returns_folder(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    added = folder_repo.add(str(tmp_path / "photos"))

    # Act
    result = folder_repo.get_by_id(added.id)

    # Assert
    assert result is not None
    assert result.id == added.id


def test_get_by_id_missing_id_returns_none(
    folder_repo: IndexedFolderRepository,
) -> None:
    assert folder_repo.get_by_id(9999) is None


# ── exists ───────────────────────────────────────────────────────────────────


def test_exists_returns_true_for_added_path(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    folder_path = str(tmp_path / "photos")
    folder_repo.add(folder_path)
    assert folder_repo.exists(folder_path) is True


def test_exists_returns_false_for_unknown_path(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    assert folder_repo.exists(str(tmp_path / "unknown")) is False


# ── remove ────────────────────────────────────────────────────────────────────


def test_remove_deletes_folder_from_db(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    added = folder_repo.add(str(tmp_path / "photos"))

    # Act
    folder_repo.remove(added.id)

    # Assert
    assert folder_repo.get_by_id(added.id) is None
    assert folder_repo.get_all() == []


def test_remove_nonexistent_id_does_not_raise(
    folder_repo: IndexedFolderRepository,
) -> None:
    folder_repo.remove(9999)  # should not raise


# ── set_enabled ───────────────────────────────────────────────────────────────


def test_set_enabled_false_marks_folder_disabled(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    added = folder_repo.add(str(tmp_path / "photos"))

    # Act
    folder_repo.set_enabled(added.id, enabled=False)
    result = folder_repo.get_by_id(added.id)

    # Assert
    assert result is not None
    assert result.enabled is False
    assert result.status == "disabled"


def test_set_enabled_true_marks_folder_indexed(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    added = folder_repo.add(str(tmp_path / "photos"))
    folder_repo.set_enabled(added.id, enabled=False)

    # Act
    folder_repo.set_enabled(added.id, enabled=True)
    result = folder_repo.get_by_id(added.id)

    # Assert
    assert result is not None
    assert result.enabled is True
    assert result.status == "indexed"


# ── get_disabled_paths ────────────────────────────────────────────────────────


def test_get_disabled_paths_returns_only_disabled_folders(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    enabled = folder_repo.add(str(tmp_path / "enabled"))
    disabled = folder_repo.add(str(tmp_path / "disabled"))
    folder_repo.set_enabled(disabled.id, enabled=False)

    # Act
    result = folder_repo.get_disabled_paths()

    # Assert
    assert len(result) == 1
    assert os.path.normpath(disabled.path) in [os.path.normpath(p) for p in result]
    assert enabled.path not in result


def test_get_disabled_paths_empty_when_all_enabled(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    folder_repo.add(str(tmp_path / "photos"))
    assert folder_repo.get_disabled_paths() == []


# ── update_status ─────────────────────────────────────────────────────────────


def test_update_status_persists_status_and_image_count(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    added = folder_repo.add(str(tmp_path / "photos"))

    # Act
    folder_repo.update_status(added.id, status="indexed", image_count=42)
    result = folder_repo.get_by_id(added.id)

    # Assert
    assert result is not None
    assert result.status == "indexed"
    assert result.image_count == 42


def test_update_status_error_persists_error_message(
    folder_repo: IndexedFolderRepository, tmp_path: Path
) -> None:
    # Arrange
    added = folder_repo.add(str(tmp_path / "photos"))

    # Act
    folder_repo.update_status(added.id, status="error", error_message="disk full")
    result = folder_repo.get_by_id(added.id)

    # Assert
    assert result is not None
    assert result.status == "error"
    assert result.error_message == "disk full"
