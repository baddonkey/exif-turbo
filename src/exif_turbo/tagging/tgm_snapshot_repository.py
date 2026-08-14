from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from ..models.tgm import (
    TgmCategory,
    TgmConcept,
    TgmDiagnostic,
    TgmDiagnosticCode,
    TgmSnapshot,
    TgmSourceFormat,
)


class TgmSnapshotRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._snapshot: TgmSnapshot | None = None
        self._by_id: dict[str, TgmConcept] = {}
        self._by_label: dict[str, TgmConcept] = {}

    def activate(self, snapshot: TgmSnapshot) -> None:
        payload = json.dumps(
            self._to_dict(snapshot),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(file_descriptor, "wb") as raw_stream:
                with gzip.GzipFile(fileobj=raw_stream, mode="wb", mtime=0) as stream:
                    stream.write(payload)
                raw_stream.flush()
                os.fsync(raw_stream.fileno())
            self._from_dict(json.loads(gzip.decompress(temp_path.read_bytes())))
            os.replace(temp_path, self._path)
        finally:
            temp_path.unlink(missing_ok=True)
        self._set_snapshot(snapshot)

    def load(self) -> TgmSnapshot:
        if self._snapshot is None:
            data = json.loads(gzip.decompress(self._path.read_bytes()))
            self._set_snapshot(self._from_dict(data))
        assert self._snapshot is not None
        return self._snapshot

    def metadata(self) -> TgmSnapshot:
        return self.load()

    def get(self, concept_id: str) -> TgmConcept | None:
        self.load()
        return self._by_id.get(concept_id)

    def resolve_label(self, label: str) -> TgmConcept | None:
        self.load()
        return self._by_label.get(label.casefold())

    def list_selectable(self) -> tuple[TgmConcept, ...]:
        return self.load().selectable_concepts

    def counts(self) -> dict[TgmCategory, int]:
        concepts = self.list_selectable()
        return {
            category: sum(category in concept.categories for concept in concepts)
            for category in TgmCategory
        }

    def search(self, query: str, limit: int = 20) -> tuple[TgmConcept, ...]:
        normalized = query.strip().casefold()
        if not normalized or limit <= 0:
            return ()
        matches: list[tuple[int, str, TgmConcept]] = []
        for concept in self.list_selectable():
            labels = (concept.label, *concept.aliases)
            folded = tuple(label.casefold() for label in labels)
            if not any(normalized in label for label in folded):
                continue
            rank = 0 if any(label.startswith(normalized) for label in folded) else 1
            matches.append((rank, concept.label.casefold(), concept))
        matches.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in matches[:limit])

    def _set_snapshot(self, snapshot: TgmSnapshot) -> None:
        self._snapshot = snapshot
        self._by_id = {concept.concept_id: concept for concept in snapshot.concepts}
        self._by_label = {}
        for concept in snapshot.concepts:
            for label in (concept.label, *concept.aliases):
                self._by_label[label.casefold()] = concept

    @staticmethod
    def _to_dict(snapshot: TgmSnapshot) -> dict[str, Any]:
        return {
            "normalization_version": snapshot.normalization_version,
            "source_url": snapshot.source_url,
            "source_format": snapshot.source_format.value,
            "distribution_date": snapshot.distribution_date,
            "imported_at": snapshot.imported_at.isoformat(),
            "raw_sha256": snapshot.raw_sha256,
            "raw_size_bytes": snapshot.raw_size_bytes,
            "concepts": [asdict(concept) for concept in snapshot.concepts],
            "diagnostics": [asdict(diagnostic) for diagnostic in snapshot.diagnostics],
        }

    @staticmethod
    def _from_dict(data: object) -> TgmSnapshot:
        if not isinstance(data, dict):
            raise ValueError("TGM snapshot must be a JSON object")
        concepts_data = data.get("concepts")
        diagnostics_data = data.get("diagnostics")
        if not isinstance(concepts_data, list) or not isinstance(diagnostics_data, list):
            raise ValueError("TGM snapshot concepts and diagnostics must be arrays")
        concepts = tuple(
            TgmConcept(
                **{
                    **item,
                    "categories": tuple(TgmCategory(value) for value in item["categories"]),
                    **{
                        key: tuple(value)
                        for key, value in item.items()
                        if isinstance(value, list) and key != "categories"
                    },
                }
            )
            for item in concepts_data
            if isinstance(item, dict)
        )
        diagnostics = tuple(
            TgmDiagnostic(
                code=TgmDiagnosticCode(item["code"]),
                message=item["message"],
                label=item.get("label"),
            )
            for item in diagnostics_data
            if isinstance(item, dict)
        )
        return TgmSnapshot(
            concepts=concepts,
            diagnostics=diagnostics,
            source_url=str(data["source_url"]),
            source_format=TgmSourceFormat(str(data["source_format"])),
            distribution_date=(
                str(data["distribution_date"])
                if data.get("distribution_date") is not None
                else None
            ),
            imported_at=datetime.fromisoformat(str(data["imported_at"])),
            raw_sha256=str(data["raw_sha256"]),
            raw_size_bytes=int(data["raw_size_bytes"]),
            normalization_version=int(data["normalization_version"]),
        )