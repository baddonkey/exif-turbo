from __future__ import annotations

from pathlib import Path

import pytest

from exif_turbo.utils.ai_index_write_lock import AiIndexWriteLock


def test_ai_index_write_lock_concurrent_writer_fails_then_can_retry(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "index.db"

    # Act / Assert
    with (
        AiIndexWriteLock(db_path),
        pytest.raises(RuntimeError, match="already running"),
        AiIndexWriteLock(db_path),
    ):
        pytest.fail("the second writer acquired the lock")
    with AiIndexWriteLock(db_path):
        pass
