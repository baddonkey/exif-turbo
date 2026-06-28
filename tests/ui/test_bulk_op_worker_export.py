from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.workers.bulk_op_worker import BulkOpWorker
from exif_turbo.utils.json_export import JsonExportFormat


@pytest.fixture
def marked_db(tmp_path: Path) -> Path:
    """A database file holding two marked images, ordered by path."""
    db_path = tmp_path / "index.db"
    repo = ImageIndexRepository(db_path, key="")
    repo.upsert_image("/a.jpg", "a.jpg", 1.0, 10, {"Make": "Canon"}, "Canon")
    repo.upsert_image("/b.jpg", "b.jpg", 2.0, 20, {"Make": "Nikon"}, "Nikon")
    repo.mark_images(["/a.jpg", "/b.jpg"], True)
    repo.close()
    return db_path


def _run_export(db_path: Path, out: Path, fmt: JsonExportFormat) -> None:
    worker = BulkOpWorker(
        db_path,
        "",
        "export_json",
        file_path=out,
        sort_by="path_asc",
        json_format=fmt,
    )
    worker.run()


def test_export_compact_writes_one_record_per_line(
    qtbot: QtBot, marked_db: Path, tmp_path: Path
) -> None:
    # Arrange
    out = tmp_path / "compact.json"

    # Act
    _run_export(marked_db, out, JsonExportFormat())

    # Assert
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "[" and lines[-1] == "]"
    assert '{"path": "/a.jpg"' in lines[1]


def test_export_pretty_spaces_indents_records(
    qtbot: QtBot, marked_db: Path, tmp_path: Path
) -> None:
    # Arrange
    out = tmp_path / "pretty.json"
    fmt = JsonExportFormat(pretty=True, indent_style="space", indent_size=2)

    # Act
    _run_export(marked_db, out, fmt)

    # Assert
    text = out.read_text(encoding="utf-8")
    assert '\n    "path": "/a.jpg"' in text  # 2 (array level) + 2 (object level)
    assert [r["path"] for r in json.loads(text)] == ["/a.jpg", "/b.jpg"]


def test_export_pretty_tabs_uses_tab_indentation(
    qtbot: QtBot, marked_db: Path, tmp_path: Path
) -> None:
    # Arrange
    out = tmp_path / "tabs.json"
    fmt = JsonExportFormat(pretty=True, indent_style="tab")

    # Act
    _run_export(marked_db, out, fmt)

    # Assert
    text = out.read_text(encoding="utf-8")
    assert '\n\t\t"path": "/a.jpg"' in text
