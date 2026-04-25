"""Consistency check for the ext-filter against the real user index database.

Opens `~/.exif-turbo/data/index/index.db` read-only, retrieves the format
counts that the UI displays, then verifies that filtering by each format
returns exactly that count from the query engine.

Run with:
    pytest tests/ui/test_ext_filter_real_db.py -v -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository

_REAL_DB = Path.home() / ".exif-turbo" / "data" / "index" / "index.db"


# ── Fixtures ──────────────────────────────────────────────────────────────────


_REAL_DB_KEY = "HurzHurz"


@pytest.fixture(scope="module")
def real_repo() -> ImageIndexRepository:
    if not _REAL_DB.exists():
        pytest.skip(f"Real DB not found at {_REAL_DB}")
    repo = ImageIndexRepository(_REAL_DB, key=_REAL_DB_KEY)
    yield repo
    repo.close()


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_real_db_total_count_is_nonzero(
    real_repo: ImageIndexRepository,
) -> None:
    # Arrange / Act
    total = real_repo.count_images("")

    # Assert
    print(f"\n  Total indexed images: {total}")
    assert total > 0, "Database appears empty"


def test_real_db_format_counts_are_consistent(
    real_repo: ImageIndexRepository,
) -> None:
    """Every bucket in get_format_counts() must match count_images(ext_filter=...)."""
    # Arrange
    format_counts = real_repo.get_format_counts()
    assert format_counts, "get_format_counts() returned nothing"

    print(f"\n  Formats in DB: {format_counts}")

    # Act / Assert — each ext filter must return exactly the declared count
    mismatches: list[str] = []
    for ext, expected in format_counts:
        actual = real_repo.count_images("", ext_filter=ext)
        status = "OK" if actual == expected else f"MISMATCH (expected {expected}, got {actual})"
        print(f"    {ext:8s}: {actual:6d}  {status}")
        if actual != expected:
            mismatches.append(f"{ext}: expected {expected}, got {actual}")

    assert not mismatches, "Format filter counts do not match:\n" + "\n".join(mismatches)


def test_real_db_all_format_counts_sum_to_total(
    real_repo: ImageIndexRepository,
) -> None:
    """The sum of all per-format counts must equal the unfiltered total.

    This catches double-counting or missing rows in the extension grouping.
    """
    # Arrange
    total = real_repo.count_images("")
    format_counts = real_repo.get_format_counts()

    # Act
    summed = sum(count for _, count in format_counts)

    # Assert
    print(f"\n  Total: {total}  |  Sum of format buckets: {summed}")
    assert summed == total, (
        f"Sum of per-format counts ({summed}) != total ({total}). "
        "Possible cause: images with no/unknown extension are excluded from format_counts."
    )


def test_real_db_clearing_ext_filter_restores_total(
    real_repo: ImageIndexRepository,
) -> None:
    """Applying then clearing an ext filter must return the same total."""
    # Arrange
    total_before = real_repo.count_images("")
    format_counts = real_repo.get_format_counts()
    if not format_counts:
        pytest.skip("No formats in DB")

    first_ext = format_counts[0][0]

    # Act — apply first format filter then clear it
    real_repo.count_images("", ext_filter=first_ext)  # warm up
    total_after_clear = real_repo.count_images("")

    # Assert
    assert total_after_clear == total_before, (
        f"Total changed after clearing filter: {total_before} → {total_after_clear}"
    )
