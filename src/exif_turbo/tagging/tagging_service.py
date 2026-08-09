from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from ..data.image_index_repository import ImageIndexRepository
from ..data.sidecar_sync_state import SidecarSyncState
from ..models.image_sidecar import ImageSidecar, SidecarSource
from ..models.image_tag import ImageTag, TagProvenance
from ..models.tag_proposal import (
    ProposalBatchResult,
    ProposalGenerationResult,
    TagProposal,
    TagProposalStatus,
)
from ..models.tgm import TgmCategory, TgmConcept, TgmSnapshot
from .sidecar_repository import (
    FilesystemSidecarRepository,
    LoadedSidecar,
    SidecarConflictError,
    SidecarReadError,
    SidecarRevision,
)
from .tgm_snapshot_repository import TgmSnapshotRepository


class TaggingError(RuntimeError):
    """Base class for application-service tagging failures."""


class TaggingConceptError(TaggingError):
    """Raised when input does not resolve to a selectable canonical concept."""


class TaggingPartialFailure(TaggingError):
    """Raised when the sidecar write succeeded but the derived cache update failed."""


class TaggingConflictError(TaggingError):
    """Raised when an external sidecar edit wins an optimistic-write race."""


class TaggingSidecarError(TaggingError):
    """Raised when an existing sidecar is malformed or unsupported."""


class TaggingFilesystemError(TaggingError):
    """Raised when an image or sidecar cannot be read or written."""


class TaggingProposalError(TaggingError):
    """Raised when a pending proposal cannot be found or decided."""


class BulkTagStatus(StrEnum):
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    CONFLICTED = "conflicted"
    FAILED = "failed"


class TagMembership(StrEnum):
    ALL = "all"
    SOME = "some"


@dataclass(frozen=True)
class TagMutationResult:
    image_path: str
    changed: bool
    sidecar: ImageSidecar


@dataclass(frozen=True)
class ProposalDecisionResult:
    image_path: str
    concept_id: str
    changed: bool


@dataclass(frozen=True)
class ImageTaggingState:
    image_path: str
    sidecar: ImageSidecar | None
    revision: SidecarRevision | None
    proposals: tuple[TagProposal, ...]
    cache_state: SidecarSyncState | None

    @property
    def accepted_tags(self) -> tuple[ImageTag, ...]:
        return () if self.sidecar is None else self.sidecar.tags


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


@dataclass(frozen=True)
class AggregatedConceptState:
    concept: TgmConcept
    count: int
    membership: TagMembership


@dataclass(frozen=True)
class MarkedTaggingState:
    total_marked: int
    tagged_marked: int
    concepts: tuple[AggregatedConceptState, ...]


BulkProgress = Callable[[int, int, BulkTagItemResult], None]


class TaggingService:
    def __init__(
        self,
        image_repository: ImageIndexRepository,
        sidecar_repository: FilesystemSidecarRepository,
        tgm_repository: TgmSnapshotRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._image_repository = image_repository
        self._sidecar_repository = sidecar_repository
        self._tgm_repository = tgm_repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def get_image_tagging_state(self, image_path: str) -> ImageTaggingState:
        loaded = self._read_sidecar(Path(image_path))
        return ImageTaggingState(
            image_path=image_path,
            sidecar=None if loaded is None else loaded.sidecar,
            revision=None if loaded is None else loaded.revision,
            proposals=self._image_repository.get_proposals(
                image_path, status=TagProposalStatus.PENDING
            ),
            cache_state=self._image_repository.get_sidecar_sync_state(image_path),
        )

    def add_concept(self, image_path: str, concept_reference: str) -> TagMutationResult:
        snapshot = self._tgm_repository.load()
        concept = self._resolve_concept(concept_reference)
        tag = self._build_tag(concept, snapshot, self._timestamp())
        return self._apply_tag_changes(image_path, additions=(tag,))

    def remove_concept(self, image_path: str, concept_id: str) -> TagMutationResult:
        return self._apply_tag_changes(image_path, removals=(concept_id,))

    def accept_pending_proposal(
        self,
        image_path: str,
        concept_id: str,
        provider_fingerprint: str,
    ) -> TagMutationResult:
        proposal = self._find_pending_proposal(
            image_path, concept_id, provider_fingerprint
        )
        concept = self._resolve_concept(proposal.concept_id)
        tag = self._build_tag(
            concept,
            self._tgm_repository.load(),
            self._timestamp(),
        )
        return self._apply_tag_changes(
            image_path,
            additions=(tag,),
            accepted_proposals=((concept_id, provider_fingerprint),),
        )

    def reject_proposal(
        self,
        image_path: str,
        concept_id: str,
        provider_fingerprint: str,
    ) -> ProposalDecisionResult:
        changed = self._image_repository.reject_proposal(
            image_path, concept_id, provider_fingerprint
        )
        if not changed:
            raise TaggingProposalError("pending proposal was not found")
        return ProposalDecisionResult(image_path, concept_id, True)

    def add_concept_to_paths(
        self,
        image_paths: Iterable[str],
        concept_reference: str,
        *,
        on_progress: BulkProgress | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> BulkTagResult:
        concept = self._resolve_concept(concept_reference)
        return self._bulk_apply(
            image_paths,
            lambda path: self.add_concept(path, concept.concept_id),
            on_progress=on_progress,
            cancel_check=cancel_check,
        )

    def remove_concept_from_paths(
        self,
        image_paths: Iterable[str],
        concept_id: str,
        *,
        on_progress: BulkProgress | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> BulkTagResult:
        return self._bulk_apply(
            image_paths,
            lambda path: self.remove_concept(path, concept_id),
            on_progress=on_progress,
            cancel_check=cancel_check,
        )

    def add_concept_to_marked(
        self,
        concept_reference: str,
        *,
        restrict_to_enabled_folders: bool = True,
        on_progress: BulkProgress | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> BulkTagResult:
        return self.add_concept_to_paths(
            self._image_repository.get_marked_paths(
                restrict_to_enabled_folders=restrict_to_enabled_folders
            ),
            concept_reference,
            on_progress=on_progress,
            cancel_check=cancel_check,
        )

    def remove_concept_from_marked(
        self,
        concept_id: str,
        *,
        restrict_to_enabled_folders: bool = True,
        on_progress: BulkProgress | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> BulkTagResult:
        return self.remove_concept_from_paths(
            self._image_repository.get_marked_paths(
                restrict_to_enabled_folders=restrict_to_enabled_folders
            ),
            concept_id,
            on_progress=on_progress,
            cancel_check=cancel_check,
        )

    def accept_auto_candidates(
        self,
        batch: ProposalBatchResult,
        *,
        on_progress: BulkProgress | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> BulkTagResult:
        results = batch.results
        items: list[BulkTagItemResult] = []
        for index, generation in enumerate(results):
            if cancel_check is not None and cancel_check():
                return BulkTagResult(tuple(items), True)
            if not generation.auto_candidates:
                item = BulkTagItemResult(
                    generation.image_path, BulkTagStatus.SKIPPED
                )
            else:
                item = self._apply_auto_generation(generation)
            items.append(item)
            if on_progress is not None:
                on_progress(index + 1, len(results), item)
        return BulkTagResult(tuple(items), batch.cancelled)

    def get_marked_tagging_state(
        self,
        *,
        restrict_to_enabled_folders: bool = True,
    ) -> MarkedTaggingState:
        paths = self._image_repository.get_marked_paths(
            restrict_to_enabled_folders=restrict_to_enabled_folders
        )
        counts: dict[str, int] = {}
        tagged_marked = 0
        for path in paths:
            tags = self._image_repository.get_accepted_tags(path)
            if tags:
                tagged_marked += 1
            for tag in tags:
                counts[tag.concept_id] = counts.get(tag.concept_id, 0) + 1
        total = len(paths)
        concepts = tuple(
            AggregatedConceptState(
                concept=concept,
                count=count,
                membership=(
                    TagMembership.ALL if count == total else TagMembership.SOME
                ),
            )
            for concept_id, count in sorted(counts.items())
            if (concept := self._tgm_repository.get(concept_id)) is not None
            and concept.selectable
        )
        return MarkedTaggingState(total, tagged_marked, concepts)

    def _apply_tag_changes(
        self,
        image_path: str,
        *,
        additions: tuple[ImageTag, ...] = (),
        removals: tuple[str, ...] = (),
        accepted_proposals: tuple[tuple[str, str], ...] = (),
    ) -> TagMutationResult:
        path = Path(image_path)
        loaded = self._read_sidecar(path)
        sidecar = self._load_or_create_sidecar(path, loaded)
        tags_by_id = {tag.concept_id: tag for tag in sidecar.tags}
        original_ids = set(tags_by_id)
        for concept_id in removals:
            tags_by_id.pop(concept_id, None)
        for tag in additions:
            tags_by_id.setdefault(tag.concept_id, tag)
        changed = original_ids != set(tags_by_id)
        if not changed:
            return TagMutationResult(image_path, False, sidecar)
        updated = replace(
            sidecar,
            updated_at=self._timestamp(),
            tags=self._ordered_tags(tuple(tags_by_id.values())),
        )
        revision = self._write_sidecar(path, updated, loaded)
        self._update_cache(
            image_path,
            updated,
            revision,
            accepted_proposals=accepted_proposals,
        )
        return TagMutationResult(image_path, True, updated)

    def _apply_auto_generation(
        self,
        generation: ProposalGenerationResult,
    ) -> BulkTagItemResult:
        try:
            snapshot = self._tgm_repository.load()
            timestamp = self._timestamp()
            proposals_by_concept = {
                proposal.concept_id: proposal
                for proposal in generation.auto_candidates
            }
            additions = tuple(
                self._build_clip_tag(
                    self._resolve_concept(proposal.concept_id),
                    snapshot,
                    timestamp,
                    proposal,
                )
                for proposal in proposals_by_concept.values()
            )
            result = self._apply_tag_changes(
                generation.image_path,
                additions=additions,
                accepted_proposals=tuple(
                    (proposal.concept_id, proposal.provider_fingerprint)
                    for proposal in proposals_by_concept.values()
                ),
            )
            status = (
                BulkTagStatus.SUCCEEDED if result.changed else BulkTagStatus.SKIPPED
            )
            return BulkTagItemResult(generation.image_path, status)
        except TaggingConflictError as exc:
            return BulkTagItemResult(
                generation.image_path, BulkTagStatus.CONFLICTED, str(exc)
            )
        except Exception as exc:  # noqa: BLE001
            return BulkTagItemResult(
                generation.image_path, BulkTagStatus.FAILED, str(exc)
            )

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

    def _find_pending_proposal(
        self,
        image_path: str,
        concept_id: str,
        provider_fingerprint: str,
    ) -> TagProposal:
        proposals = self._image_repository.get_proposals(
            image_path,
            provider_fingerprint=provider_fingerprint,
            status=TagProposalStatus.PENDING,
        )
        proposal = next(
            (item for item in proposals if item.concept_id == concept_id), None
        )
        if proposal is None:
            raise TaggingProposalError("pending proposal was not found")
        return proposal

    def _resolve_concept(self, reference: str) -> TgmConcept:
        normalized = reference.strip()
        if not normalized:
            raise TaggingConceptError("free-text tags are unsupported")
        concept = self._tgm_repository.get(normalized)
        if concept is None:
            concept = self._tgm_repository.resolve_label(normalized)
        if concept is None:
            raise TaggingConceptError(f"unknown TGM concept: {reference}")
        if not concept.selectable:
            raise TaggingConceptError(
                f"TGM concept is not selectable: {concept.concept_id}"
            )
        return concept

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

    @staticmethod
    def _build_tag(
        concept: TgmConcept,
        snapshot: TgmSnapshot,
        timestamp: str,
    ) -> ImageTag:
        category = (
            TgmCategory.SUBJECT
            if TgmCategory.SUBJECT in concept.categories
            else TgmCategory.GENRE_FORMAT
        )
        return ImageTag(
            concept_id=concept.concept_id,
            label=concept.label,
            category=category.value,
            provenance=TagProvenance(
                method="manual",
                accepted_at=timestamp,
                vocabulary_checksum=f"sha256:{snapshot.raw_sha256}",
            ),
            extra={
                "tgm_categories": [item.value for item in concept.categories],
            },
        )

    @classmethod
    def _build_clip_tag(
        cls,
        concept: TgmConcept,
        snapshot: TgmSnapshot,
        timestamp: str,
        proposal: TagProposal,
    ) -> ImageTag:
        manual = cls._build_tag(concept, snapshot, timestamp)
        return replace(
            manual,
            provenance=TagProvenance(
                method="clip",
                accepted_at=timestamp,
                confidence=proposal.score,
                model=proposal.provider_model,
                vocabulary_checksum=f"sha256:{snapshot.raw_sha256}",
                extra={
                    "provider": "clip",
                    "provider_fingerprint": proposal.provider_fingerprint,
                },
            ),
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
        *,
        accepted_proposals: tuple[tuple[str, str], ...] = (),
    ) -> None:
        sidecar_path = self._sidecar_repository.sidecar_path(Path(image_path))
        aliases = {
            tag.concept_id: concept.aliases
            for tag in sidecar.tags
            if (concept := self._tgm_repository.get(tag.concept_id)) is not None
        }
        try:
            self._image_repository.replace_accepted_tags_and_sidecar_state(
                image_path,
                sidecar,
                sidecar_path=str(sidecar_path),
                sidecar_mtime_ns=revision.mtime_ns,
                sidecar_size=revision.size,
                sidecar_checksum=revision.sha256,
                sync_status="synced",
                aliases=aliases,
                accepted_proposals=accepted_proposals,
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

    @staticmethod
    def _ordered_tags(tags: tuple[ImageTag, ...]) -> tuple[ImageTag, ...]:
        return tuple(sorted(tags, key=lambda tag: (tag.label.casefold(), tag.concept_id)))