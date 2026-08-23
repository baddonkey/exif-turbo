from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from ..models.tgm_localization import TgmConceptLocalization, TgmLocalizationPack


class TgmLocalizationRepository:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self._path = path
        self._pack: TgmLocalizationPack | None = None
        self._by_key: dict[tuple[str, str], TgmConceptLocalization] = {}

    @property
    def exists(self) -> bool:
        return self._path.exists()

    @property
    def checksum(self) -> str:
        if not self._path.exists():
            return ""
        return hashlib.sha256(self._path.read_bytes()).hexdigest()

    def activate(self, pack: TgmLocalizationPack) -> None:
        payload = json.dumps(
            self._to_dict(pack),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        temp_path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as raw_stream:
                with gzip.GzipFile(fileobj=raw_stream, mode="wb", mtime=0) as stream:
                    stream.write(payload)
                raw_stream.flush()
                os.fsync(raw_stream.fileno())
            validated = self._from_dict(json.loads(gzip.decompress(temp_path.read_bytes())))
            os.replace(temp_path, self._path)
        finally:
            temp_path.unlink(missing_ok=True)
        self._set_pack(validated)

    @classmethod
    def read_pack(cls, path: Path) -> TgmLocalizationPack:
        payload = path.read_bytes()
        if path.suffix.casefold() == ".gz":
            payload = gzip.decompress(payload)
        return cls._from_dict(json.loads(payload.decode("utf-8")))

    def load(self) -> TgmLocalizationPack | None:
        if self._pack is None and self._path.exists():
            self._set_pack(
                self._from_dict(json.loads(gzip.decompress(self._path.read_bytes())))
            )
        return self._pack

    def get(self, concept_id: str, locale: str) -> TgmConceptLocalization | None:
        self.load()
        return self._by_key.get((concept_id, locale))

    def records_for(self, concept_id: str) -> tuple[TgmConceptLocalization, ...]:
        pack = self.load()
        if pack is None:
            return ()
        return tuple(record for record in pack.records if record.concept_id == concept_id)

    def _set_pack(self, pack: TgmLocalizationPack) -> None:
        self._pack = pack
        self._by_key = {
            (record.concept_id, record.locale): record for record in pack.records
        }

    @classmethod
    def _to_dict(cls, pack: TgmLocalizationPack) -> dict[str, Any]:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "version": pack.version,
            "created_at": pack.created_at.isoformat(),
            "source_uri": pack.source_uri,
            "license_id": pack.license_id,
            "records": [asdict(record) for record in pack.records],
        }

    @classmethod
    def _from_dict(cls, value: object) -> TgmLocalizationPack:
        if not isinstance(value, dict) or value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported TGM localization pack schema")
        records_value = value.get("records")
        if not isinstance(records_value, list):
            raise ValueError("localization pack records must be an array")
        records = tuple(
            TgmConceptLocalization(
                concept_id=str(record["concept_id"]),
                locale=str(record["locale"]),
                preferred_label=str(record["preferred_label"]),
                aliases=tuple(str(alias) for alias in record.get("aliases", [])),
                source_uri=str(record.get("source_uri", "")),
                license_id=str(record.get("license_id", "")),
                translation_method=str(record.get("translation_method", "manual")),
                review_status=str(record.get("review_status", "unreviewed")),
            )
            for record in records_value
            if isinstance(record, dict)
        )
        return TgmLocalizationPack(
            records=records,
            version=int(value["version"]),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            source_uri=str(value["source_uri"]),
            license_id=str(value["license_id"]),
        )