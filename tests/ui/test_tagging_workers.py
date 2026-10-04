from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from exif_turbo.ui.workers import copy_tags_worker as copy_module
from exif_turbo.ui.workers.copy_tags_worker import CopyTagsWorker


class FakeRepository:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.closed = False

    def load(self) -> None:
        pass

    def load_for_rebuild(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_copy_tags_worker_marked_scope_resolves_marked_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    copied_paths: list[tuple[str, ...]] = []
    result = SimpleNamespace(cancelled=False, succeeded_count=2)

    class MarkedRepository(FakeRepository):
        def get_marked_paths(self, **_kwargs: object) -> list[str]:
            return ["first.jpg", "second.jpg"]

    class FakeTaggingService:
        def __init__(self, *args: object) -> None:
            pass

        def copy_tags_to_paths(
            self,
            _source: str,
            paths: object,
            _mode: object,
            **_kwargs: object,
        ) -> object:
            copied_paths.append(tuple(paths))  # type: ignore[arg-type]
            return result

    monkeypatch.setattr(copy_module, "ImageIndexRepository", MarkedRepository)
    monkeypatch.setattr(copy_module, "TaggingService", FakeTaggingService)
    worker = CopyTagsWorker(
        tmp_path / "images.db",
        "",
        "source.jpg",
        "add",
        marked_only=True,
    )
    results: list[object] = []
    worker.result_ready.connect(results.append)

    # Act
    worker.run()

    # Assert
    assert copied_paths == [("first.jpg", "second.jpg")]
    assert results == [result]


def test_copy_tags_worker_results_scope_forwards_complete_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    matching_options: list[tuple[str, dict[str, object]]] = []
    result = SimpleNamespace(cancelled=False, succeeded_count=1)

    class MatchingRepository(FakeRepository):
        def get_matching_paths(self, query: str, **kwargs: object) -> list[str]:
            matching_options.append((query, kwargs))
            return ["target.jpg"]

    class FakeTaggingService:
        def __init__(self, *args: object) -> None:
            pass

        def copy_tags_to_paths(self, *_args: object, **_kwargs: object) -> object:
            return result

    monkeypatch.setattr(copy_module, "ImageIndexRepository", MatchingRepository)
    monkeypatch.setattr(copy_module, "TaggingService", FakeTaggingService)
    worker = CopyTagsWorker(
        tmp_path / "images.db",
        "",
        "source.jpg",
        "replace",
        query="family",
        ext_filter=".jpg",
        path_filter=["photos"],
        restrict_to_enabled_folders=True,
        date_from=100,
        date_to=200,
    )

    # Act
    worker.run()

    # Assert
    assert matching_options == [
        (
            "family",
            {
                "ext_filter": ".jpg",
                "path_filter": ["photos"],
                "restrict_to_enabled_folders": True,
                "date_from": 100,
                "date_to": 200,
            },
        )
    ]


