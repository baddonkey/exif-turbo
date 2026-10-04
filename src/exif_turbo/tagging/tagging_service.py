from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path

from ..data.image_index_repository import ImageIndexRepository
from ..data.sidecar_sync_state import SidecarSyncState
from ..models.image_sidecar import ImageSidecar, SidecarSource, normalize_free_tag
from ..models.image_tag import SidecarValidationError
from .derivative_export_service import extract_embedded_keyword_labels
from .sidecar_repository import (
    FilesystemSidecarRepository,
    LoadedSidecar,
    SidecarConflictError,
    SidecarReadError,
    SidecarRevision,
)


class TaggingError(RuntimeError):
    """Base class for application-service tagging failures."""


class TaggingFreeTagError(TaggingError):
    """Raised when a custom free tag is invalid."""


class TaggingPartialFailure(TaggingError):
    """Raised when the sidecar write succeeded but the derived cache update failed."""


class TaggingConflictError(TaggingError):
    """Raised when an external sidecar edit wins an optimistic-write race."""


class TaggingSidecarError(TaggingError):
    """Raised when an existing sidecar is malformed or unsupported."""


class TaggingFilesystemError(TaggingError):
    """Raised when an image or sidecar cannot be read or written."""


class BulkTagStatus(StrEnum):
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    CONFLICTED = "conflicted"
    FAILED = "failed"


class CopyTagsMode(StrEnum):
    ADD = "add"
    REPLACE = "replace"


@dataclass(frozen=True)
class TagMutationResult:
    image_path: str
    changed: bool
    sidecar: ImageSidecar


@dataclass(frozen=True)
class ImageTaggingState:
    image_path: str
    sidecar: ImageSidecar | None
    revision: SidecarRevision | None
    cache_state: SidecarSyncState | None

    @property
    def free_tags(self) -> tuple[str, ...]:
        return () if self.sidecar is None else self.sidecar.free_tags


@dataclass(frozen=True)
class BulkTagItemResult:
    image_path: str
    status: BulkTagStatus
    error: str | None = None


@dataclass(frozen=True)
class BulkTagResult:
    items: tuple[BulkTagItemResult, ...]
    cancelled: bool

    def count(self, status: BulkTagStatus) -> int:
        return sum(item.status is status for item in self.items)

    @property
    def succeeded_count(self) -> int:
        return self.count(BulkTagStatus.SUCCEEDED)

    @property
    def skipped_count(self) -> int:
        return self.count(BulkTagStatus.SKIPPED)

    @property
    def conflicted_count(self) -> int:
        return self.count(BulkTagStatus.CONFLICTED)

    @property
    def failed_count(self) -> int:
        return self.count(BulkTagStatus.FAILED)


BulkProgress = Callable[[int, int, BulkTagItemResult], None]


class TaggingService:
    def __init__(
        self,
        image_repository: ImageIndexRepository,
        sidecar_repository: FilesystemSidecarRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._image_repository = image_repository
        self._sidecar_repository = sidecar_repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def get_image_tagging_state(self, image_path: str) -> ImageTaggingState:
        loaded = self._read_sidecar(Path(image_path))
        return ImageTaggingState(
            image_path=image_path,
            sidecar=None if loaded is None else loaded.sidecar,
            revision=None if loaded is None else loaded.revision,
            cache_state=self._image_repository.get_sidecar_sync_state(image_path),
        )

    def add_free_tag(self, image_path: str, label: str) -> TagMutationResult:
        normalized_label = self._normalize_free_tag(label)
        normalized_label = (
            self._image_repository.resolve_free_tag(normalized_label)
            or normalized_label
        )
        path = Path(image_path)
        loaded = self._read_sidecar(path)
        sidecar = self._load_or_create_sidecar(path, loaded)
        existing_keys = {tag.casefold() for tag in sidecar.free_tags}
        if normalized_label.casefold() in existing_keys:
            return TagMutationResult(image_path, False, sidecar)
        updated = replace(
            sidecar,
            updated_at=self._timestamp(),
            free_tags=(*sidecar.free_tags, normalized_label),
        )
        revision = self._write_sidecar(path, updated, loaded)
        self._update_cache(image_path, updated, revision)
        return TagMutationResult(image_path, True, updated)

    def remove_free_tag(self, image_path: str, label: str) -> TagMutationResult:
        normalized_label = self._normalize_free_tag(label)
        path = Path(image_path)
        loaded = self._read_sidecar(path)
        sidecar = self._load_or_create_sidecar(path, loaded)
        retained = tuple(
            tag
            for tag in sidecar.free_tags
            if tag.casefold() != normalized_label.casefold()
        )
        if len(retained) == len(sidecar.free_tags):
            return TagMutationResult(image_path, False, sidecar)
        updated = replace(
            sidecar,
            updated_at=self._timestamp(),
            free_tags=retained,
        )
        revision = self._write_sidecar(path, updated, loaded)
        self._update_cache(image_path, updated, revision)
        return TagMutationResult(image_path, True, updated)

    def set_embedded_tag_excluded(
        self,
        image_path: str,
        label: str,
        excluded: bool,
    ) -> TagMutationResult:
        normalized_label = self._normalize_free_tag(label)
        path = Path(image_path)
        loaded = self._read_sidecar(path)
        sidecar = self._load_or_create_sidecar(path, loaded)
        exclusions_by_key = {
            value.casefold(): value for value in sidecar.excluded_embedded_tags
        }
        if excluded:
            exclusions_by_key.setdefault(normalized_label.casefold(), normalized_label)
        else:
            exclusions_by_key.pop(normalized_label.casefold(), None)
        exclusions = tuple(exclusions_by_key.values())
        if exclusions == sidecar.excluded_embedded_tags:
            return TagMutationResult(image_path, False, sidecar)
        updated = replace(
            sidecar,
            updated_at=self._timestamp(),
            excluded_embedded_tags=exclusions,
        )
        revision = self._write_sidecar(path, updated, loaded)
        self._update_cache(image_path, updated, revision)
        return TagMutationResult(image_path, True, updated)

    def set_all_embedded_tags_excluded(
        self,
        image_path: str,
        excluded: bool,
    ) -> TagMutationResult:
        path = Path(image_path)
        loaded = self._read_sidecar(path)
        sidecar = self._load_or_create_sidecar(path, loaded)
        if sidecar.exclude_all_embedded_tags == excluded:
            return TagMutationResult(image_path, False, sidecar)
        updated = replace(
            sidecar,
            updated_at=self._timestamp(),
            exclude_all_embedded_tags=excluded,
        )
        revision = self._write_sidecar(path, updated, loaded)
        self._update_cache(image_path, updated, revision)
        return TagMutationResult(image_path, True, updated)

    def copy_tags_to_paths(
        self,
        source_image_path: str,
        target_image_paths: Iterable[str],
        mode: CopyTagsMode,
        *,
        on_progress: BulkProgress | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> BulkTagResult:
        source_state = self.get_image_tagging_state(source_image_path)
        source_sidecar = source_state.sidecar
        source_free_tags = () if source_sidecar is None else source_sidecar.free_tags
        source_excluded_embedded_tags = (
            () if source_sidecar is None else source_sidecar.excluded_embedded_tags
        )
        source_exclude_all_embedded_tags = (
            False if source_sidecar is None else source_sidecar.exclude_all_embedded_tags
        )
        targets = (
            path
            for path in target_image_paths
            if path != source_image_path
        )
        return self._bulk_apply(
            targets,
            lambda path: self._copy_tags_to_path(
                path,
                source_free_tags,
                source_excluded_embedded_tags,
                source_exclude_all_embedded_tags,
                mode,
            ),
            on_progress=on_progress,
            cancel_check=cancel_check,
        )

    def _copy_tags_to_path(
        self,
        image_path: str,
        source_free_tags: tuple[str, ...],
        source_excluded_embedded_tags: tuple[str, ...],
        source_exclude_all_embedded_tags: bool,
        mode: CopyTagsMode,
    ) -> TagMutationResult:
        path = Path(image_path)
        loaded = self._read_sidecar(path)
        sidecar = self._load_or_create_sidecar(path, loaded)
        embedded_keys = {
            label.casefold() for label in self._embedded_tags_for_path(image_path)
        }
        applicable_exclusions = tuple(
            label
            for label in source_excluded_embedded_tags
            if label.casefold() in embedded_keys
        )
        if mode is CopyTagsMode.REPLACE:
            free_tags = source_free_tags
            excluded_embedded_tags = applicable_exclusions
            exclude_all_embedded_tags = source_exclude_all_embedded_tags
        elif mode is CopyTagsMode.ADD:
            free_tags_by_key = {tag.casefold(): tag for tag in sidecar.free_tags}
            for tag in source_free_tags:
                free_tags_by_key.setdefault(tag.casefold(), tag)
            free_tags = tuple(free_tags_by_key.values())
            exclusions_by_key = {
                tag.casefold(): tag for tag in sidecar.excluded_embedded_tags
            }
            for tag in applicable_exclusions:
                exclusions_by_key.setdefault(tag.casefold(), tag)
            excluded_embedded_tags = tuple(exclusions_by_key.values())
            exclude_all_embedded_tags = (
                sidecar.exclude_all_embedded_tags
                or source_exclude_all_embedded_tags
            )
        else:
            raise ValueError(f"unknown copy tags mode: {mode}")
        if (
            not sidecar.tags
            and free_tags == sidecar.free_tags
            and excluded_embedded_tags == sidecar.excluded_embedded_tags
            and exclude_all_embedded_tags == sidecar.exclude_all_embedded_tags
        ):
            return TagMutationResult(image_path, False, sidecar)
        updated = replace(
            sidecar,
            updated_at=self._timestamp(),
            tags=(),
            free_tags=free_tags,
            excluded_embedded_tags=excluded_embedded_tags,
            exclude_all_embedded_tags=exclude_all_embedded_tags,
        )
        revision = self._write_sidecar(path, updated, loaded)
        self._update_cache(image_path, updated, revision)
        return TagMutationResult(image_path, True, updated)

    def _embedded_tags_for_path(self, image_path: str) -> tuple[str, ...]:
        rows = self._image_repository.get_images_by_paths([image_path])
        if not rows:
            return ()
        try:
            metadata = json.loads(rows[0][3])
        except (TypeError, json.JSONDecodeError):
            return ()
        if not isinstance(metadata, dict):
            return ()
        return extract_embedded_keyword_labels(metadata)

    def _bulk_apply(
        self,
        image_paths: Iterable[str],
        operation: Callable[[str], TagMutationResult],
        *,
        on_progress: BulkProgress | None,
        cancel_check: Callable[[], bool] | None,
    ) -> BulkTagResult:
        paths = tuple(dict.fromkeys(image_paths))
        items: list[BulkTagItemResult] = []
        for index, image_path in enumerate(paths):
            if cancel_check is not None and cancel_check():
                return BulkTagResult(tuple(items), True)
            try:
                result = operation(image_path)
                status = (
                    BulkTagStatus.SUCCEEDED
                    if result.changed
                    else BulkTagStatus.SKIPPED
                )
                item = BulkTagItemResult(image_path, status)
            except TaggingConflictError as exc:
                item = BulkTagItemResult(
                    image_path, BulkTagStatus.CONFLICTED, str(exc)
                )
            except Exception as exc:  # noqa: BLE001
                item = BulkTagItemResult(
                    image_path, BulkTagStatus.FAILED, str(exc)
                )
            items.append(item)
            if on_progress is not None:
                on_progress(index + 1, len(paths), item)
        return BulkTagResult(tuple(items), False)

    @staticmethod
    def _normalize_free_tag(label: str) -> str:
        try:
            return normalize_free_tag(label)
        except SidecarValidationError as exc:
            raise TaggingFreeTagError(str(exc)) from exc

    @staticmethod
    def _load_or_create_sidecar(
        image_path: Path,
        loaded: LoadedSidecar | None,
    ) -> ImageSidecar:
        if loaded is not None:
            return loaded.sidecar
        image_stat = image_path.stat()
        return ImageSidecar(
            source=SidecarSource(
                filename=image_path.name,
                size=image_stat.st_size,
                mtime_ns=image_stat.st_mtime_ns,
            ),
            updated_at=datetime.fromtimestamp(0, UTC).isoformat().replace("+00:00", "Z"),
        )

    def _read_sidecar(self, image_path: Path) -> LoadedSidecar | None:
        try:
            return self._sidecar_repository.read(image_path)
        except SidecarConflictError as exc:
            raise TaggingConflictError(str(exc)) from exc
        except SidecarReadError as exc:
            raise TaggingSidecarError(str(exc)) from exc
        except OSError as exc:
            raise TaggingFilesystemError(str(exc)) from exc

    def _write_sidecar(
        self,
        image_path: Path,
        sidecar: ImageSidecar,
        loaded: LoadedSidecar | None,
    ) -> SidecarRevision:
        try:
            return self._sidecar_repository.write(
                image_path,
                sidecar,
                expected_revision=None if loaded is None else loaded.revision,
            )
        except SidecarConflictError as exc:
            raise TaggingConflictError(str(exc)) from exc
        except OSError as exc:
            raise TaggingFilesystemError(str(exc)) from exc

    def _update_cache(
        self,
        image_path: str,
        sidecar: ImageSidecar,
        revision: SidecarRevision,
    ) -> None:
        sidecar_path = self._sidecar_repository.sidecar_path(Path(image_path))
        try:
            self._image_repository.replace_custom_tags_and_sidecar_state(
                image_path,
                sidecar,
                sidecar_path=str(sidecar_path),
                sidecar_mtime_ns=revision.mtime_ns,
                sidecar_size=revision.size,
                sidecar_checksum=revision.sha256,
                sync_status="synced",
            )
        except Exception as exc:
            try:
                self._image_repository.record_sidecar_sync_error(
                    image_path,
                    sidecar_path=str(sidecar_path),
                    sidecar_mtime_ns=revision.mtime_ns,
                    sidecar_size=revision.size,
                    sidecar_checksum=revision.sha256,
                    sync_error=f"cache update failed: {exc}",
                )
            except Exception:
                pass
            raise TaggingPartialFailure(
                f"sidecar was written but cache update failed: {exc}"
            ) from exc

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise TaggingError("tagging clock must return a timezone-aware datetime")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

