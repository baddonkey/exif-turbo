from __future__ import annotations

from pathlib import Path

from exif_turbo.config import database_data_dir, tgm_snapshot_path, tgm_work_dir


def test_tgm_config_paths_are_isolated_by_database_name() -> None:
    # Arrange
    first_database = Path("C:/catalogs/animals.db")
    second_database = Path("C:/catalogs/people.db")

    # Act
    first_snapshot = tgm_snapshot_path(first_database)
    second_snapshot = tgm_snapshot_path(second_database)

    # Assert
    assert first_snapshot.name == "tgm-snapshot.json.gz"
    assert first_snapshot.parent.name == "tgm"
    assert first_snapshot != second_snapshot
    assert tgm_work_dir(first_database) == first_snapshot.parent / "work"


def test_database_data_dir_same_stem_in_different_locations_is_isolated() -> None:
    # Arrange
    application_database = Path("C:/Users/test/.exif-turbo/data/index/index.db")
    temporary_database = Path("C:/Temp/test-run/index.db")

    # Act
    application_data = database_data_dir(application_database)
    temporary_data = database_data_dir(temporary_database)

    # Assert
    assert application_data == application_database.parent
    assert temporary_data == temporary_database.parent / ".index.exif-turbo"
    assert tgm_snapshot_path(application_database) != tgm_snapshot_path(
        temporary_database
    )


def test_database_data_dir_named_database_preserves_existing_layout() -> None:
    # Arrange
    database = Path("C:/Users/test/.exif-turbo/data/animals/animals.db")

    # Act
    data_dir = database_data_dir(database)

    # Assert
    assert data_dir == database.parent