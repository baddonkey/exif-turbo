"""Unit tests for AppController file-open behaviour when the original is gone.

Covers issue #20: clicking a thumbnail whose original data source is not
attached must not silently fail.  Instead the controller surfaces a red
status-bar warning that names the indexed folder the user needs to (re)attach
or mount, and it never tries to open a missing file.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Generator

import pytest

from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.view_models.app_controller import AppController


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def controller(tmp_path: Path) -> Generator[AppController, None, None]:
    """Bare AppController over an unopened DB — no QML engine, no workers."""
    search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
    ctrl = AppController(
        tmp_path / "app.db",
        search_model,
        ExifListModel(),
        FolderListModel(),
    )
    yield ctrl
    ctrl.close()


def _fake_folder_repo(*paths: str) -> SimpleNamespace:
    """In-memory stand-in for IndexedFolderRepository exposing get_all/close."""
    folders = [SimpleNamespace(path=p) for p in paths]
    return SimpleNamespace(get_all=lambda: folders, close=lambda: None)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_openImage_missing_file_in_indexed_folder_warns_with_data_source(
    controller: AppController, tmp_path: Path
) -> None:
    # Arrange — folder is indexed but the file no longer exists on disk
    root = tmp_path / "photos"
    controller._folder_repo = _fake_folder_repo(str(root))
    missing = root / "sub" / "img.jpg"

    # Act
    controller.openImage(str(missing))

    # Assert — red warning naming the data source to attach
    assert controller.statusIsError is True
    assert os.path.normpath(str(root)) in controller.statusText


def test_openImage_missing_file_outside_indexed_folders_warns_file_not_found(
    controller: AppController, tmp_path: Path
) -> None:
    # Arrange — missing file is not covered by any indexed folder
    controller._folder_repo = _fake_folder_repo(str(tmp_path / "photos"))
    missing = tmp_path / "elsewhere" / "img.jpg"

    # Act
    controller.openImage(str(missing))

    # Assert — still an error, but the generic file-not-found message
    assert controller.statusIsError is True
    assert "img.jpg" in controller.statusText


def test_openFolder_missing_file_in_indexed_folder_warns_with_data_source(
    controller: AppController, tmp_path: Path
) -> None:
    # Arrange
    root = tmp_path / "photos"
    controller._folder_repo = _fake_folder_repo(str(root))
    missing = root / "img.jpg"

    # Act
    controller.openFolder(str(missing))

    # Assert
    assert controller.statusIsError is True
    assert os.path.normpath(str(root)) in controller.statusText


def test_expected_data_source_returns_longest_matching_root(
    controller: AppController, tmp_path: Path
) -> None:
    # Arrange — nested indexed roots; the deeper one must win
    outer = tmp_path / "lib"
    inner = tmp_path / "lib" / "2024"
    controller._folder_repo = _fake_folder_repo(str(outer), str(inner))
    target = inner / "img.jpg"

    # Act
    source = controller._expected_data_source(str(target))

    # Assert
    assert source == os.path.normpath(str(inner))


def test_expected_data_source_no_indexed_folder_returns_empty(
    controller: AppController, tmp_path: Path
) -> None:
    # Arrange
    controller._folder_repo = _fake_folder_repo(str(tmp_path / "photos"))

    # Act
    source = controller._expected_data_source(str(tmp_path / "other" / "img.jpg"))

    # Assert
    assert source == ""


def test_openImage_empty_path_leaves_status_unchanged(
    controller: AppController,
) -> None:
    # Arrange
    before = controller.statusText

    # Act
    controller.openImage("")

    # Assert
    assert controller.statusIsError is False
    assert controller.statusText == before
