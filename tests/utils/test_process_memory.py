from __future__ import annotations

import os
from pathlib import Path

import pytest

from exif_turbo.utils.process_memory import current_rss_bytes


@pytest.mark.skipif(not hasattr(os, "sysconf"), reason="POSIX only")
def test_current_rss_bytes_statm_file_returns_resident_pages_in_bytes(
    tmp_path: Path,
) -> None:
    # Arrange
    statm = tmp_path / "statm"
    statm.write_text("5000 1234 300 10 0 900 0\n", encoding="ascii")

    # Act
    rss = current_rss_bytes(statm)

    # Assert
    assert rss == 1234 * os.sysconf("SC_PAGE_SIZE")


def test_current_rss_bytes_missing_statm_returns_none(tmp_path: Path) -> None:
    # Act
    rss = current_rss_bytes(tmp_path / "does-not-exist")

    # Assert
    assert rss is None


def test_current_rss_bytes_malformed_statm_returns_none(tmp_path: Path) -> None:
    # Arrange
    statm = tmp_path / "statm"
    statm.write_text("garbage\n", encoding="ascii")

    # Act
    rss = current_rss_bytes(statm)

    # Assert
    assert rss is None
