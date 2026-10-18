from __future__ import annotations

from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.ui.workers.image_set_membership_worker import (
    ImageSetMembershipWorker,
)


def test_image_set_membership_worker_cancel_keeps_completed_batches(
    tmp_path: Path,
) -> None:
    # Arrange
    db_path = tmp_path / "images.db"
    repository = ImageIndexRepository(db_path, key="")
    image_paths = [str(tmp_path / f"image-{index}.jpg") for index in range(501)]
    repository.upsert_images_batch(
        [
            (path, Path(path).name, 1.0, 100, {}, "", None, None)
            for path in image_paths
        ]
    )
    set_id = repository.create_image_set("Batch")
    repository.close()
    worker = ImageSetMembershipWorker(
        db_path,
        "",
        set_id,
        "results",
        True,
        image_paths=image_paths,
    )
    progress: list[tuple[int, int]] = []
    canceled: list[tuple[int, int, int]] = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.canceled.connect(lambda *result: canceled.append(result))

    def cancel_after_first_batch(done: int, _total: int) -> None:
        if done >= 500:
            worker.cancel()

    worker.progress.connect(cancel_after_first_batch)

    # Act
    worker.run()

    # Assert
    assert progress == [(0, 501), (500, 501)]
    assert canceled == [(500, 500, 0)]
    result_repository = ImageIndexRepository(db_path, key="")
    try:
        members = result_repository.get_image_set_members(set_id, limit=501)
    finally:
        result_repository.close()
    assert len(members) == 500


def test_image_set_membership_worker_filter_reapply_reports_progress(
    tmp_path: Path,
) -> None:
    # Arrange
    db_path = tmp_path / "images.db"
    repository = ImageIndexRepository(db_path, key="")
    image_paths = [str(tmp_path / f"wildlife-{index}.jpg") for index in range(1001)]
    repository.upsert_images_batch(
        [
            (path, Path(path).name, 1.0, 100, {}, "wildlife", None, None)
            for path in image_paths
        ]
    )
    set_id = repository.create_image_set(
        "Filter progress",
        {
            "op": "and",
            "conditions": [
                {"field": "text", "operator": "matches", "value": "wildlife"}
            ],
        },
    )
    repository.close()
    worker = ImageSetMembershipWorker(
        db_path,
        "",
        set_id,
        "filter",
        True,
        filter_mode="add",
    )
    progress: list[tuple[int, int]] = []
    results: list[tuple[int, int, int]] = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.result_ready.connect(lambda *result: results.append(result))

    # Act
    worker.run()

    # Assert
    assert progress == [(0, 1001), (500, 1001), (1000, 1001), (1001, 1001)]
    assert results == [(1001, 1001, 0)]


@pytest.mark.parametrize("mode", ["add", "replace"])
def test_image_set_membership_worker_filter_cancel_keeps_completed_batches(
    tmp_path: Path,
    mode: str,
) -> None:
    # Arrange
    db_path = tmp_path / "images.db"
    repository = ImageIndexRepository(db_path, key="")
    image_paths = [str(tmp_path / f"wildlife-{index}.jpg") for index in range(1001)]
    stale_path = str(tmp_path / "existing.jpg")
    repository.upsert_images_batch(
        [
            (path, Path(path).name, 1.0, 100, {}, "wildlife", None, None)
            for path in image_paths
        ]
        + [(stale_path, "existing.jpg", 1.0, 100, {}, "other", None, None)]
    )
    set_id = repository.create_image_set(
        "Filter cancel",
        {
            "op": "and",
            "conditions": [
                {"field": "text", "operator": "matches", "value": "wildlife"}
            ],
        },
    )
    repository.add_images_to_set(set_id, [stale_path])
    repository.close()
    worker = ImageSetMembershipWorker(
        db_path,
        "",
        set_id,
        "filter",
        False,
        filter_mode=mode,
        confirm_empty_replace=True,
    )
    progress: list[tuple[int, int]] = []
    canceled: list[tuple[int, int, int]] = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.canceled.connect(lambda *result: canceled.append(result))

    def cancel_after_first_batch(done: int, _total: int) -> None:
        if done >= 500:
            worker.cancel()

    worker.progress.connect(cancel_after_first_batch)

    # Act
    worker.run()

    # Assert
    assert progress == [(0, 1001), (500, 1001)]
    assert canceled == [(500, 500, 1 if mode == "replace" else 0)]
    result_repository = ImageIndexRepository(db_path, key="")
    try:
        members = result_repository.get_image_set_members(set_id, limit=1001)
    finally:
        result_repository.close()
    expected_paths = set(image_paths[:500])
    if mode == "add":
        expected_paths.add(stale_path)
    assert {member["path"] for member in members} == expected_paths


def test_image_set_membership_worker_empty_replace_requests_confirmation(
    tmp_path: Path,
) -> None:
    # Arrange
    db_path = tmp_path / "images.db"
    repository = ImageIndexRepository(db_path, key="")
    stale_path = str(tmp_path / "existing.jpg")
    repository.upsert_image(stale_path, "existing.jpg", 1.0, 100, {}, "other")
    set_id = repository.create_image_set(
        "Empty filter",
        {
            "op": "and",
            "conditions": [
                {"field": "text", "operator": "matches", "value": "missing"}
            ],
        },
    )
    repository.add_images_to_set(set_id, [stale_path])
    repository.close()
    worker = ImageSetMembershipWorker(
        db_path,
        "",
        set_id,
        "filter",
        False,
        filter_mode="replace",
    )
    confirmation_required: list[bool] = []
    worker.empty_replace_confirmation_required.connect(
        lambda: confirmation_required.append(True)
    )

    # Act
    worker.run()

    # Assert
    assert confirmation_required == [True]
    result_repository = ImageIndexRepository(db_path, key="")
    try:
        members = result_repository.get_image_set_members(set_id)
    finally:
        result_repository.close()
    assert [member["path"] for member in members] == [stale_path]