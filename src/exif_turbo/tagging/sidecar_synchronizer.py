from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable, Iterable

from ..data.image_index_repository import ImageIndexRepository
from ..models.image_tag import SidecarValidationError
from .sidecar_repository import (
    FilesystemSidecarRepository,
    SidecarReadError,
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SidecarSyncResult:
    error_count: int
    canceled: bool


class SidecarSynchronizer:
    def __init__(
        self,
        image_repository: ImageIndexRepository,
        sidecar_repository: FilesystemSidecarRepository | None = None,
    ) -> None:
        self._image_repository = image_repository
        self._sidecar_repository = (
            sidecar_repository or FilesystemSidecarRepository()
        )

    def synchronize(
        self,
        image_paths: Iterable[str],
        cancel_check: Callable[[], bool] | None = None,
    ) -> SidecarSyncResult:
        error_count = 0
        for image_path_value in image_paths:
            if cancel_check and cancel_check():
                return SidecarSyncResult(error_count=error_count, canceled=True)
            image_path = Path(image_path_value)
            try:
                synchronized = self._synchronize_image(image_path)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Unable to synchronize %s: %s", image_path, exc)
                synchronized = False
            if not synchronized:
                error_count += 1
        return SidecarSyncResult(error_count=error_count, canceled=False)

    def _synchronize_image(self, image_path: Path) -> bool:
        sidecar_path = self._sidecar_repository.sidecar_path(image_path)
        cached = self._image_repository.get_sidecar_sync_state(str(image_path))
        observed = self._sidecar_repository.stat(image_path)

        if observed is None:
            if cached is not None:
                self._image_repository.clear_accepted_tags_and_sidecar_state(
                    str(image_path)
                )
            return True

        if (
            cached is not None
            and cached.sidecar_path == str(sidecar_path)
            and cached.mtime_ns == observed.mtime_ns
            and cached.size == observed.size
        ):
            return cached.sync_status != "error"

        try:
            loaded = self._sidecar_repository.read(image_path)
            if loaded is None:
                if cached is not None:
                    self._image_repository.clear_accepted_tags_and_sidecar_state(
                        str(image_path)
                    )
                return True
            if loaded.sidecar.source.filename != image_path.name:
                raise SidecarReadError(
                    "source.filename must match the original image filename",
                    loaded.revision,
                )
            self._image_repository.replace_accepted_tags_and_sidecar_state(
                str(image_path),
                loaded.sidecar,
                sidecar_path=str(sidecar_path),
                sidecar_mtime_ns=loaded.revision.mtime_ns,
                sidecar_size=loaded.revision.size,
                sidecar_checksum=loaded.revision.sha256,
                sync_status="synced",
                aliases={},
            )
            return True
        except SidecarReadError as exc:
            self._record_error(image_path, sidecar_path, exc)
        except SidecarValidationError as exc:
            _log.warning("Unable to synchronize %s: %s", sidecar_path, exc)
            return False
        except OSError as exc:
            _log.warning("Unable to synchronize %s: %s", sidecar_path, exc)
            return False
        return False

    def _record_error(
        self,
        image_path: Path,
        sidecar_path: Path,
        error: SidecarReadError,
    ) -> None:
        self._image_repository.record_sidecar_sync_error(
            str(image_path),
            sidecar_path=str(sidecar_path),
            sidecar_mtime_ns=error.revision.mtime_ns,
            sidecar_size=error.revision.size,
            sidecar_checksum=error.revision.sha256,
            sync_error=str(error),
        )
        _log.warning("Unable to synchronize %s: %s", sidecar_path, error)