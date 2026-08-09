from pathlib import Path

from exif_turbo.config import (
    ai_index_path,
    tgm_concept_map_path,
    tgm_term_index_path,
    tgm_vector_metadata_path,
)


def test_tgm_vector_paths_are_separate_from_image_ai_index() -> None:
    # Arrange
    db_path = Path("library.db")

    # Act
    paths = {
        ai_index_path(db_path),
        tgm_term_index_path(db_path),
        tgm_concept_map_path(db_path),
        tgm_vector_metadata_path(db_path),
    }

    # Assert
    assert len(paths) == 4