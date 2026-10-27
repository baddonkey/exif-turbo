from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from ..data.image_index_repository import ImageIndexRepository
from ..models.derivative_export_flavour import (
    DerivativeExportFlavour,
    DerivativeFormat,
    MetadataMode,
)
from .exif_metadata_writer import ExifMetadataWriter
from .media_conversion import DerivativeMediaConverter, MediaConversionCanceled
from .sidecar_repository import FilesystemSidecarRepository, LoadedSidecar


_EMBEDDED_KEYWORD_KEYS = (
    "XMP-dc:Subject",
    "XMP:Subject",
    "IPTC:Keywords",
    "XMP-lr:HierarchicalSubject",
    "XMP:HierarchicalSubject",
)


def merge_keyword_labels(*groups: Iterable[str]) -> tuple[str, ...]:
    labels_by_key: dict[str, str] = {}
    for group in groups:
        for value in group:
            label = value.strip()
            if label:
                labels_by_key.setdefault(label.casefold(), label)
    return tuple(
        sorted(labels_by_key.values(), key=lambda label: (label.casefold(), label))
    )


def extract_embedded_keyword_labels(
    metadata: Mapping[str, object],
) -> tuple[str, ...]:
    labels: list[str] = []
    for key in _EMBEDDED_KEYWORD_KEYS:
        value = metadata.get(key)
        values: object = value
        if isinstance(value, str) and value.strip().startswith(("[", "(")):
            try:
                values = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                values = value
        candidates = values if isinstance(values, (list, tuple)) else (values,)
        labels.extend(str(candidate) for candidate in candidates if candidate is not None)
    return merge_keyword_labels(labels)


def extract_embedded_description(metadata: Mapping[str, object]) -> str:
    descriptions: list[str] = []
    for key, value in metadata.items():
        group, _, name = key.rpartition(":")
        supported = (
            (group in {"IFD0", "IFD1", "EXIF"} and name == "ImageDescription")
            or (group in {"ExifIFD", "EXIF", "XMP-exif", "XMP"} and name == "UserComment")
            or (group == "IPTC" and name == "Caption-Abstract")
            or (
                group in {"XMP-dc", "XMP", "PNG", "QuickTime", "ItemList", "Keys", "UserData"}
                and (name == "Description" or name.startswith("Description-"))
            )
        )
        if not supported:
            continue
        values = value.values() if isinstance(value, dict) else (value,)
        for candidate in values:
            if not isinstance(candidate, str):
                continue
            text = candidate.replace("\r\n", "\n").replace("\r", "\n").strip()
            if text and text not in descriptions:
                descriptions.append(text)
    return "\n\n".join(descriptions)


def final_derivative_description(
    embedded: str, custom: str, exclude_embedded: bool
) -> str:
    return "\n\n".join(text for text in ("" if exclude_embedded else embedded, custom) if text)


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
    excluded_embedded_tags: tuple[str, ...] = ()
    exclude_all_embedded_tags: bool = False
    planned_status: DerivativeExportStatus | None = None
    message: str | None = None
    exclude_embedded_description: bool = False
    description: str | None = None
    flavour: DerivativeExportFlavour | None = None
    metadata_mode: MetadataMode | None = None


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
    metadata_errors: tuple[str, ...] = ()
    flavour_name: str | None = None


@dataclass(frozen=True)
class DerivativeExportResult:
    items: tuple[DerivativeExportItemResult, ...]
    error_report_path: Path | None = None
    error_report_error: str | None = None

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

    @property
    def metadata_warning_count(self) -> int:
        return sum(bool(item.metadata_errors) for item in self.items)


DerivativeProgress = Callable[[int, int, DerivativeExportItemResult], None]
CancelCheck = Callable[[], bool]


class MetadataWriter(Protocol):
    def write_description(
        self, target: Path, description: str, *, forbidden_sources: Iterable[Path] = ()
    ) -> None: ...

    def discard_embedded_description(
        self, target: Path, *, forbidden_sources: Iterable[Path] = ()
    ) -> None: ...

    def write_keywords(
        self,
        target: Path,
        labels: Sequence[str],
        *,
        forbidden_sources: Iterable[Path] = (),
        excluded_labels: Iterable[str] = (),
        preserve_existing_keywords: bool = True,
    ) -> None: ...


class DerivativeExportService:
    def __init__(
        self,
        image_repository: ImageIndexRepository,
        metadata_writer: MetadataWriter | None = None,
        sidecar_repository: FilesystemSidecarRepository | None = None,
        *,
        auto_repair_tags: bool = True,
        write_description_to_xpcomment: bool = True,
        media_converter: DerivativeMediaConverter | None = None,
    ) -> None:
        self._image_repository = image_repository
        self._metadata_writer = metadata_writer or ExifMetadataWriter(
            auto_repair_tags=auto_repair_tags,
            write_description_to_xpcomment=write_description_to_xpcomment,
        )
        self._sidecar_repository = sidecar_repository or FilesystemSidecarRepository()
        self._media_converter = media_converter or DerivativeMediaConverter()

    def create_plan(
        self,
        indexed_roots: Mapping[Path | str, str],
        output_root: Path,
        *,
        image_paths: Iterable[Path | str] | None = None,
        flavours: Sequence[DerivativeExportFlavour] | None = None,
        metadata_modes: Mapping[str, MetadataMode | str] | None = None,
        preserve_folder_structure: bool = True,
    ) -> DerivativeExportPlan:
        if flavours is not None and not flavours:
            raise DerivativeExportError("at least one export flavour must be selected")
        flavour_ids = [flavour.flavour_id for flavour in flavours or ()]
        if len(flavour_ids) != len(set(flavour_ids)):
            raise DerivativeExportError("selected export flavour IDs must be unique")
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
            loaded = self._sidecar_repository.read(source)
            labels, excluded_labels, exclude_all, exclude_description = self._derivative_labels(source, loaded)
            rows = self._image_repository.get_images_by_paths([str(source)])
            metadata = json.loads(rows[0][3]) if rows else {}
            if not isinstance(metadata, dict):
                raise DerivativeExportError(f"invalid indexed metadata for {source}")
            embedded_description = extract_embedded_description(metadata)
            custom_description = (
                loaded.sidecar.description if loaded is not None else ""
            )
            description = final_derivative_description(
                embedded_description, custom_description, exclude_description
            ) or None
            selected_flavours: Sequence[DerivativeExportFlavour | None] = (
                flavours if flavours is not None else (None,)
            )
            for flavour in selected_flavours:
                destination_root = resolved_output
                if len(used_roots) > 1:
                    destination_root /= labels_by_root[root]
                if preserve_folder_structure:
                    destination_root /= relative.parent
                if flavour is None:
                    destination_name = source.name
                    metadata_mode = None
                else:
                    metadata_mode = self._effective_metadata_mode(
                        flavour, metadata_modes
                    )
                    extension = self._extension_for_flavour(flavour, source)
                    destination_name = f"{source.stem}{flavour.filename_suffix}{extension}"
                destination = (destination_root / destination_name).resolve()
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
                status: DerivativeExportStatus | None = None
                message: str | None = None
                if destination.exists():
                    status = DerivativeExportStatus.SKIPPED_EXISTING
                    message = "destination already exists"
                items.append(
                    DerivativeExportPlanItem(
                        source=source,
                        destination=destination,
                        labels=labels,
                        excluded_embedded_tags=excluded_labels,
                        exclude_all_embedded_tags=exclude_all,
                        planned_status=status,
                        message=message,
                        exclude_embedded_description=exclude_description,
                        description=description,
                        flavour=flavour,
                        metadata_mode=metadata_mode,
                    )
                )
        return DerivativeExportPlan(resolved_output, sources, tuple(items))

    @staticmethod
    def _effective_metadata_mode(
        flavour: DerivativeExportFlavour,
        metadata_modes: Mapping[str, MetadataMode | str] | None,
    ) -> MetadataMode:
        mode: MetadataMode | str = flavour.metadata_mode
        if metadata_modes is not None and flavour.flavour_id in metadata_modes:
            mode = metadata_modes[flavour.flavour_id]
        try:
            effective_mode = mode if isinstance(mode, MetadataMode) else MetadataMode(mode)
        except ValueError as exc:
            raise DerivativeExportError(
                f"invalid metadata mode for flavour {flavour.name}: {mode}"
            ) from exc
        if (
            flavour.output_format is DerivativeFormat.ORIGINAL
            and effective_mode is not MetadataMode.ORIGINAL
        ):
            raise DerivativeExportError(
                "Original (as is) requires Original metadata mode"
            )
        return effective_mode

    @staticmethod
    def _extension_for_flavour(
        flavour: DerivativeExportFlavour, source: Path
    ) -> str:
        if flavour.output_format is DerivativeFormat.ORIGINAL:
            return source.suffix
        return {
            DerivativeFormat.JPEG: ".jpg",
            DerivativeFormat.PNG: ".png",
            DerivativeFormat.TIFF: ".tif",
        }[flavour.output_format]

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
        report_items = [
            item
            for item in results
            if item.status is DerivativeExportStatus.FAILED or item.metadata_errors
        ]
        report_path: Path | None = None
        report_error: str | None = None
        if report_items:
            report_path = self._write_error_report(plan.output_root, report_items)
            if report_path is None:
                report_error = "unable to write derivative export error report"
        return DerivativeExportResult(tuple(results), report_path, report_error)

    def _export_item(
        self,
        item: DerivativeExportPlanItem,
        sources: tuple[Path, ...],
        cancel_check: CancelCheck | None,
    ) -> DerivativeExportItemResult:
        temporary = item.destination.with_name(
            f".{item.destination.stem}.{uuid.uuid4().hex}.tmp{item.destination.suffix}"
        )
        metadata_errors: list[str] = []
        try:
            if item.destination.exists():
                return self._result(
                    item,
                    DerivativeExportStatus.SKIPPED_EXISTING,
                    "destination already exists",
                )
            item.destination.parent.mkdir(parents=True, exist_ok=True)
            if item.flavour is None or item.flavour.output_format is DerivativeFormat.ORIGINAL:
                shutil.copy2(item.source, temporary)
            else:
                self._media_converter.convert(
                    item.source,
                    temporary,
                    item.flavour,
                    item.metadata_mode or item.flavour.metadata_mode,
                    cancel_check=cancel_check,
                )
            if cancel_check is not None and cancel_check():
                return self._result(
                    item, DerivativeExportStatus.CANCELED, "export canceled"
                )
            should_write_custom_metadata = (
                item.flavour is None
                or item.metadata_mode is MetadataMode.CUSTOM
            )
            if should_write_custom_metadata and (
                item.labels or item.excluded_embedded_tags or item.exclude_all_embedded_tags
            ):
                try:
                    self._metadata_writer.write_keywords(
                        temporary,
                        item.labels,
                        forbidden_sources=sources,
                        excluded_labels=item.excluded_embedded_tags,
                        preserve_existing_keywords=not item.exclude_all_embedded_tags,
                    )
                except Exception as exc:  # noqa: BLE001 — preserve the derivative and report metadata trouble
                    metadata_errors.append(f"keyword metadata: {exc}")
            if should_write_custom_metadata and item.description is not None:
                try:
                    self._metadata_writer.write_description(
                        temporary, item.description, forbidden_sources=sources
                    )
                except Exception as exc:  # noqa: BLE001 — preserve the derivative and report metadata trouble
                    metadata_errors.append(f"description metadata: {exc}")
            elif should_write_custom_metadata and item.exclude_embedded_description:
                try:
                    self._metadata_writer.discard_embedded_description(
                        temporary, forbidden_sources=sources
                    )
                except Exception as exc:  # noqa: BLE001 — preserve the derivative and report metadata trouble
                    metadata_errors.append(f"description metadata: {exc}")
            if cancel_check is not None and cancel_check():
                return self._result(
                    item,
                    DerivativeExportStatus.CANCELED,
                    "export canceled",
                    metadata_errors=tuple(metadata_errors),
                )
            if item.destination.exists():
                return self._result(
                    item,
                    DerivativeExportStatus.SKIPPED_EXISTING,
                    "destination appeared during export",
                    metadata_errors=tuple(metadata_errors),
                )
            os.replace(temporary, item.destination)
            return self._result(
                item,
                DerivativeExportStatus.COPIED,
                "; ".join(metadata_errors) or None,
                metadata_errors=tuple(metadata_errors),
            )
        except MediaConversionCanceled:
            return self._result(item, DerivativeExportStatus.CANCELED, "export canceled")
        except Exception as exc:  # noqa: BLE001
            return self._result(
                item,
                DerivativeExportStatus.FAILED,
                str(exc),
                metadata_errors=tuple(metadata_errors),
            )
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _derivative_labels(
        self,
        source: Path,
        loaded_sidecar: LoadedSidecar | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...], bool, bool]:
        if loaded_sidecar is None:
            return (), (), False, False
        custom_labels = [
            label.strip()
            for label in loaded_sidecar.sidecar.free_tags
            if label.strip()
        ]
        if not custom_labels:
            return (
                (), loaded_sidecar.sidecar.excluded_embedded_tags,
                loaded_sidecar.sidecar.exclude_all_embedded_tags,
                loaded_sidecar.sidecar.exclude_embedded_description,
            )
        embedded_labels: tuple[str, ...] = ()
        if not loaded_sidecar.sidecar.exclude_all_embedded_tags:
            rows = self._image_repository.get_images_by_paths([str(source)])
        else:
            rows = []
        if rows:
            try:
                metadata = json.loads(rows[0][3])
                if isinstance(metadata, dict):
                    embedded_labels = extract_embedded_keyword_labels(metadata)
            except (TypeError, json.JSONDecodeError):
                pass
        excluded_keys = {
            label.casefold()
            for label in loaded_sidecar.sidecar.excluded_embedded_tags
        }
        embedded_labels = tuple(
            label for label in embedded_labels if label.casefold() not in excluded_keys
        )
        return (
            merge_keyword_labels(custom_labels, embedded_labels),
            loaded_sidecar.sidecar.excluded_embedded_tags,
            loaded_sidecar.sidecar.exclude_all_embedded_tags,
            loaded_sidecar.sidecar.exclude_embedded_description,
        )

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
        matches = [root for root, _label in roots if cls._is_within(source, root)]
        if not matches:
            raise DerivativeExportError(
                f"source does not belong to any indexed root: {source}"
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
        *,
        metadata_errors: tuple[str, ...] = (),
    ) -> DerivativeExportItemResult:
        return DerivativeExportItemResult(
            source=item.source,
            destination=item.destination,
            status=status,
            message=message,
            metadata_errors=metadata_errors,
            flavour_name=item.flavour.name if item.flavour is not None else None,
        )

    @staticmethod
    def _write_error_report(
        output_root: Path,
        items: Sequence[DerivativeExportItemResult],
    ) -> Path | None:
        report_path = output_root / "derivative-export-errors.json"
        suffix = 2
        while report_path.exists():
            report_path = output_root / f"derivative-export-errors-{suffix}.json"
            suffix += 1
        records = []
        for item in items:
            record: dict[str, object] = {
                "source": str(item.source),
                "destination": str(item.destination),
                "status": item.status.value,
                "error": item.message,
                "metadataErrors": list(item.metadata_errors),
            }
            if item.flavour_name is not None:
                record["flavour"] = item.flavour_name
            records.append(record)
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps({"items": records}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return None
        return report_path