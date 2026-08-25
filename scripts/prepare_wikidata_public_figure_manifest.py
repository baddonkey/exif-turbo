#!/usr/bin/env python3
"""Prepare a runtime snapshot manifest from public-figure discovery output."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_QID_PATTERN = re.compile(r"^Q[1-9]\d*$")
_REQUIRED_LOCALES = ("de", "en", "fr", "it")
_SOURCE_DUMP_URI = "https://www.wikidata.org/w/api.php"


class PublicFigureManifestError(ValueError):
    """The discovery document cannot produce a runtime manifest."""


class PublicFigureManifestPreparer:
    def prepare(
        self,
        discovery_path: Path,
        entities_path: Path,
        output_path: Path,
    ) -> dict[str, Any]:
        discovery = self._read_discovery(discovery_path)
        discovered_qids = {
            str(concept["qid"]) for concept in discovery["concepts"]
        }
        eligible_qids, exported_qids = self._read_eligible_entity_qids(
            entities_path,
            discovered_qids,
        )
        missing_qids = discovered_qids - exported_qids
        if missing_qids:
            raise PublicFigureManifestError(
                "entity export is missing discovered QIDs: "
                + ", ".join(sorted(missing_qids, key=lambda qid: int(qid[1:])))
            )
        document = {
            "schema_version": 1,
            "snapshot_version": discovery["identity_snapshot_version"],
            "created_at": discovery["created_at"],
            "source": {
                "name": "Wikidata public figures",
                "dump_uri": _SOURCE_DUMP_URI,
                "dump_sha256": hashlib.sha256(entities_path.read_bytes()).hexdigest(),
                "license_id": "CC0-1.0",
                "excluded_missing_required_labels": (
                    len(discovered_qids) - len(eligible_qids)
                ),
            },
            "concepts": [
                {"qid": concept["qid"], "category": "subject"}
                for concept in sorted(
                    (
                        concept
                        for concept in discovery["concepts"]
                        if concept["qid"] in eligible_qids
                    ),
                    key=lambda value: int(value["qid"][1:]),
                )
            ],
        }
        self._write_json(output_path, document)
        return document

    @staticmethod
    def _read_eligible_entity_qids(
        path: Path,
        discovered_qids: set[str],
    ) -> tuple[set[str], set[str]]:
        eligible_qids: set[str] = set()
        exported_qids: set[str] = set()
        try:
            with path.open("r", encoding="utf-8-sig") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        entity = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise PublicFigureManifestError(
                            f"invalid entity JSON on line {line_number}"
                        ) from exc
                    qid = entity.get("id") if isinstance(entity, dict) else None
                    if not isinstance(qid, str) or _QID_PATTERN.fullmatch(qid) is None:
                        raise PublicFigureManifestError(
                            f"invalid entity ID on line {line_number}"
                        )
                    if qid in exported_qids:
                        raise PublicFigureManifestError(
                            f"duplicate entity ID {qid} on line {line_number}"
                        )
                    exported_qids.add(qid)
                    if qid not in discovered_qids:
                        continue
                    labels = entity.get("labels")
                    if isinstance(labels, dict) and all(
                        isinstance(labels.get(locale), dict)
                        and isinstance(labels[locale].get("value"), str)
                        and labels[locale]["value"].strip()
                        for locale in _REQUIRED_LOCALES
                    ):
                        eligible_qids.add(qid)
        except (OSError, UnicodeDecodeError) as exc:
            raise PublicFigureManifestError(
                "entities must be readable UTF-8 JSONL"
            ) from exc
        return eligible_qids, exported_qids

    @staticmethod
    def _read_discovery(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicFigureManifestError(
                "discovery must be readable UTF-8 JSON"
            ) from exc
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("complete") is not True
            or isinstance(value.get("identity_snapshot_version"), bool)
            or not isinstance(value.get("identity_snapshot_version"), int)
            or value["identity_snapshot_version"] < 1
            or not isinstance(value.get("created_at"), str)
            or not isinstance(value.get("concepts"), list)
            or not value["concepts"]
        ):
            raise PublicFigureManifestError(
                "discovery must be a complete non-empty schema-v1 document"
            )
        qids: list[str] = []
        for concept in value["concepts"]:
            qid = concept.get("qid") if isinstance(concept, dict) else None
            if not isinstance(qid, str) or _QID_PATTERN.fullmatch(qid) is None:
                raise PublicFigureManifestError("discovery concepts require valid QIDs")
            qids.append(qid)
        if len(qids) != len(set(qids)):
            raise PublicFigureManifestError("discovery concepts must have unique QIDs")
        return value

    @staticmethod
    def _write_json(path: Path, document: dict[str, Any]) -> None:
        payload = (
            json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("discovery", type=Path)
    parser.add_argument("entities", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    PublicFigureManifestPreparer().prepare(
        arguments.discovery,
        arguments.entities,
        arguments.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())