from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import shutil
from typing import Callable

from ..config import database_data_dir
from ..data.image_index_repository import ImageIndexRepository
from .sidecar_repository import FilesystemSidecarRepository


@dataclass(frozen=True)
class CustomTagMigrationResult:
    images_scanned: int
    sidecars_updated: int
    errors: tuple[str, ...]
    canceled: bool
    completed: bool
    database_cleared: bool


class CustomTagMigrationService:
    MIGRATION_NAME = "custom-only-tagging-v1"

    def __init__(
        self,
        image_repository: ImageIndexRepository,
        sidecar_repository: FilesystemSidecarRepository | None = None,
    ) -> None:
        self._image_repository = image_repository
        self._sidecar_repository = sidecar_repository or FilesystemSidecarRepository()

    def migrate(
        self,
        cancel_check: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> CustomTagMigrationResult:
        if self._image_repository.migration_completed(self.MIGRATION_NAME):
            return CustomTagMigrationResult(0, 0, (), False, True, True)

        image_paths = tuple(str(row[0]) for row in self._image_repository.all_images())
        sidecars_updated = 0
        errors: list[str] = []
        for index, image_path in enumerate(image_paths):
            if cancel_check is not None and cancel_check():
                return CustomTagMigrationResult(
                    index, sidecars_updated, tuple(errors), True, False, False
                )
            path = Path(image_path)
            try:
                loaded = self._sidecar_repository.read(path)
                if loaded is not None and loaded.sidecar.tags:
                    self._sidecar_repository.write(
                        path,
                        replace(loaded.sidecar, tags=()),
                        expected_revision=loaded.revision,
                    )
                    sidecars_updated += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{image_path}: {exc}")
            if on_progress is not None:
                on_progress(index + 1, len(image_paths), image_path)

        self._image_repository.remove_controlled_tagging_data()
        shutil.rmtree(
            database_data_dir(self._image_repository.db_path) / "tgm",
            ignore_errors=True,
        )
        if errors:
            return CustomTagMigrationResult(
                len(image_paths), sidecars_updated, tuple(errors), False, False, True
            )

        self._image_repository.mark_migration_completed(self.MIGRATION_NAME)
        return CustomTagMigrationResult(
            len(image_paths), sidecars_updated, (), False, True, True
        )