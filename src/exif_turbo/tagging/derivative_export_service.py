from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from ..data.image_index_repository import ImageIndexRepository
from .exif_metadata_writer import ExifMetadataWriter


class DerivativeExportError(ValueError):
    """Raised when a derivative export plan is unsafe or ambiguous."""


class DerivativeExportStatus(str, Enum):
    COPIED = "copied"
    SKIPPED_EXISTING = "skipped_existing"
    SKIPPED_UNTAGGED = "skipped_untagged"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class DerivativeExportPlanItem:
    source: Path
    destination: Path
    labels: tuple[str, ...]
    planned_status: DerivativeExportStatus | None = None
    message: str | None = None


@dataclass(frozen=True)
class DerivativeExportPlan:
    output_root: Path
    source_paths: tuple[Path, ...]
    items: tuple[DerivativeExportPlanItem, ...]


@dataclass(frozen=True)
class DerivativeExportItemResult:
    source: Path
    destination: Path
    status: DerivativeExportStatus
    message: str | None = None


@dataclass(frozen=True)
class DerivativeExportResult:
    items: tuple[DerivativeExportItemResult, ...]

    def count(self, status: DerivativeExportStatus) -> int:
        return sum(item.status is status for item in self.items)

    @property
    def copied_count(self) -> int:
        return self.count(DerivativeExportStatus.COPIED)

    @property
    def skipped_existing_count(self) -> int:
        return self.count(DerivativeExportStatus.SKIPPED_EXISTING)

    @property
    def skipped_untagged_count(self) -> int:
        return self.count(DerivativeExportStatus.SKIPPED_UNTAGGED)

    @property
    def skipped_count(self) -> int:
        return self.skipped_existing_count + self.skipped_untagged_count

    @property
    def failed_count(self) -> int:
        return self.count(DerivativeExportStatus.FAILED)

    @property
    def canceled_count(self) -> int:
        return self.count(DerivativeExportStatus.CANCELED)


DerivativeProgress = Callable[[int, int, DerivativeExportItemResult], None]
CancelCheck = Callable[[], bool]


class MetadataWriter(Protocol):
    def write_keywords(
        self,
        target: Path,
        labels: Sequence[str],
        *,
        forbidden_sources: Iterable[Path] = (),
    ) -> None: ...


class DerivativeExportService:
    def __init__(
        self,
        image_repository: ImageIndexRepository,
        metadata_writer: MetadataWriter | None = None,
    ) -> None:
        self._image_repository = image_repository
        self._metadata_writer = metadata_writer or ExifMetadataWriter()

    def create_plan(
        self,
        indexed_roots: Mapping[Path | str, str],
        output_root: Path,
        *,
        image_paths: Iterable[Path | str] | None = None,
    ) -> DerivativeExportPlan:
        roots = self._normalize_roots(indexed_roots)
        resolved_output = output_root.resolve()
        for root, _ in roots:
            if self._is_within(resolved_output, root):
                raise DerivativeExportError(
                    f"output root must be outside indexed source root: {root}"
                )

        selected = (
            self._image_repository.get_marked_paths(
                restrict_to_enabled_folders=True
            )
            if image_paths is None
            else [str(path) for path in image_paths]
        )
        sources = tuple(
            sorted(
                {Path(path).resolve() for path in selected},
                key=lambda path: os.path.normcase(str(path)),
            )
        )
        assigned_roots = {
            source: self._most_specific_root(source, roots) for source in sources
        }
        used_root_paths = set(assigned_roots.values())
        used_roots = tuple(
            (root, label) for root, label in roots if root in used_root_paths
        )
        labels_by_root = self._root_labels(used_roots)
        source_set = set(sources)
        destination_keys: set[str] = set()
        items: list[DerivativeExportPlanItem] = []
        for source in sources:
            root = assigned_roots[source]
            relative = source.relative_to(root)
            destination = resolved_output
            if len(used_roots) > 1:
                destination /= labels_by_root[root]
            destination = (destination / relative).resolve()
            if not self._is_within(destination, resolved_output):
                raise DerivativeExportError(
                    f"planned destination escapes output root: {destination}"
                )
            if destination in source_set:
                raise DerivativeExportError(
                    f"planned destination resolves to a source image: {destination}"
                )
            destination_key = os.path.normcase(str(destination))
            if destination_key in destination_keys:
                raise DerivativeExportError(
                    f"multiple sources resolve to destination: {destination}"
                )
            destination_keys.add(destination_key)
            labels = self._accepted_labels(source)
            status: DerivativeExportStatus | None = None
            message: str | None = None
            if destination.exists():
                status = DerivativeExportStatus.SKIPPED_EXISTING
                message = "destination already exists"
            elif not labels:
                status = DerivativeExportStatus.SKIPPED_UNTAGGED
                message = "image has no accepted tags"
            items.append(
                DerivativeExportPlanItem(
                    source=source,
                    destination=destination,
                    labels=labels,
                    planned_status=status,
                    message=message,
                )
            )
        return DerivativeExportPlan(resolved_output, sources, tuple(items))

    def export(
        self,
        plan: DerivativeExportPlan,
        *,
        on_progress: DerivativeProgress | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> DerivativeExportResult:
        results: list[DerivativeExportItemResult] = []
        total = len(plan.items)
        canceled = False
        for index, item in enumerate(plan.items):
            if canceled or (cancel_check is not None and cancel_check()):
                canceled = True
                result = self._result(
                    item, DerivativeExportStatus.CANCELED, "export canceled"
                )
            elif item.planned_status is not None:
                result = self._result(item, item.planned_status, item.message)
            else:
                result = self._export_item(item, plan.source_paths, cancel_check)
                canceled = result.status is DerivativeExportStatus.CANCELED
            results.append(result)
            if on_progress is not None:
                on_progress(index + 1, total, result)
        return DerivativeExportResult(tuple(results))

    def _export_item(
        self,
        item: DerivativeExportPlanItem,
        sources: tuple[Path, ...],
        cancel_check: CancelCheck | None,
    ) -> DerivativeExportItemResult:
        temporary = item.destination.with_name(
            f".{item.destination.stem}.{uuid.uuid4().hex}.tmp{item.destination.suffix}"
        )
        try:
            if item.destination.exists():
                return self._result(
                    item,
                    DerivativeExportStatus.SKIPPED_EXISTING,
                    "destination already exists",
                )
            item.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source, temporary)
            if cancel_check is not None and cancel_check():
                return self._result(
                    item, DerivativeExportStatus.CANCELED, "export canceled"
                )
            self._metadata_writer.write_keywords(
                temporary,
                item.labels,
                forbidden_sources=sources,
            )
            if cancel_check is not None and cancel_check():
                return self._result(
                    item, DerivativeExportStatus.CANCELED, "export canceled"
                )
            if item.destination.exists():
                return self._result(
                    item,
                    DerivativeExportStatus.SKIPPED_EXISTING,
                    "destination appeared during export",
                )
            os.replace(temporary, item.destination)
            return self._result(item, DerivativeExportStatus.COPIED)
        except Exception as exc:  # noqa: BLE001
            return self._result(item, DerivativeExportStatus.FAILED, str(exc))
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _accepted_labels(self, source: Path) -> tuple[str, ...]:
        labels = {
            tag.label.strip()
            for tag in self._image_repository.get_accepted_tags(str(source))
            if tag.label.strip()
        }
        labels.update(
            label.strip()
            for label in self._image_repository.get_free_tags(str(source))
            if label.strip()
        )
        return tuple(sorted(labels, key=lambda label: (label.casefold(), label)))

    @classmethod
    def _normalize_roots(
        cls, indexed_roots: Mapping[Path | str, str]
    ) -> tuple[tuple[Path, str], ...]:
        if not indexed_roots:
            raise DerivativeExportError("at least one indexed root is required")
        normalized: dict[Path, str] = {}
        for root_value, requested_label in indexed_roots.items():
            root = Path(root_value).resolve()
            if root in normalized:
                raise DerivativeExportError(f"duplicate indexed root: {root}")
            normalized[root] = cls._safe_label(requested_label, root)
        return tuple(
            sorted(
                normalized.items(),
                key=lambda pair: os.path.normcase(str(pair[0])),
            )
        )

    @classmethod
    def _root_labels(
        cls, roots: tuple[tuple[Path, str], ...]
    ) -> dict[Path, str]:
        grouped: dict[str, list[tuple[Path, str]]] = {}
        for root, label in roots:
            grouped.setdefault(os.path.normcase(label), []).append((root, label))
        result: dict[Path, str] = {}
        used: set[str] = set()
        for root, label in roots:
            matches = grouped[os.path.normcase(label)]
            if len(matches) == 1:
                base_candidate = label
            else:
                digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
                base_candidate = f"{label}-{digest}"
            candidate = base_candidate
            suffix = 2
            while os.path.normcase(candidate) in used:
                candidate = f"{base_candidate}-{suffix}"
                suffix += 1
            used.add(os.path.normcase(candidate))
            result[root] = candidate
        return result

    @staticmethod
    def _safe_label(requested_label: str, root: Path) -> str:
        candidate = requested_label.strip() or root.name or root.anchor.rstrip("\\/")
        label = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", candidate).strip(" .")
        if not label or label in {".", ".."}:
            raise DerivativeExportError(f"indexed root has no safe label: {root}")
        return label

    @classmethod
    def _most_specific_root(
        cls,
        source: Path,
        roots: tuple[tuple[Path, str], ...],
    ) -> Path:
        matches = [root for root, _ in roots if cls._is_within(source, root)]
        if not matches:
            raise DerivativeExportError(
                f"source does not belong to an indexed root: {source}"
            )
        return max(matches, key=lambda root: len(root.parts))

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            normalized_path = os.path.normcase(os.path.abspath(path))
            normalized_root = os.path.normcase(os.path.abspath(root))
            return os.path.commonpath((normalized_path, normalized_root)) == normalized_root
        except ValueError:
            return False

    @staticmethod
    def _result(
        item: DerivativeExportPlanItem,
        status: DerivativeExportStatus,
        message: str | None = None,
    ) -> DerivativeExportItemResult:
        return DerivativeExportItemResult(
            source=item.source,
            destination=item.destination,
            status=status,
            message=message,
        )