#!/usr/bin/env python3
"""Merge deterministic Wikidata JSON-lines exports by QID."""
from __future__ import annotations

import argparse
from collections.abc import Iterator
import heapq
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_QID_PATTERN = re.compile(r"^Q[1-9]\d*$")


class WikidataEntityMergeError(ValueError):
    """Raised when entity exports cannot be merged safely."""


def merge_wikidata_entities(inputs: list[Path], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            iterators = [_iter_entities(path) for path in inputs]
            pending: list[tuple[int, int, str, dict[str, Any]]] = []
            for index, iterator in enumerate(iterators):
                try:
                    qid, entity = next(iterator)
                except StopIteration:
                    continue
                heapq.heappush(pending, (int(qid[1:]), index, qid, entity))
            previous_qid: str | None = None
            while pending:
                _numeric_qid, index, qid, entity = heapq.heappop(pending)
                if qid == previous_qid:
                    raise WikidataEntityMergeError(f"duplicate entity ID: {qid}")
                json.dump(
                    entity,
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                stream.write("\n")
                previous_qid = qid
                try:
                    next_qid, next_entity = next(iterators[index])
                except StopIteration:
                    continue
                heapq.heappush(
                    pending,
                    (int(next_qid[1:]), index, next_qid, next_entity),
                )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)


def _iter_entities(path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    previous_number = 0
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                entity = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WikidataEntityMergeError(
                    f"invalid JSON on line {line_number} of {path.name}"
                ) from exc
            if not isinstance(entity, dict):
                raise WikidataEntityMergeError(
                    f"entity on line {line_number} of {path.name} must be an object"
                )
            qid = entity.get("id")
            if not isinstance(qid, str) or not _QID_PATTERN.fullmatch(qid):
                raise WikidataEntityMergeError(
                    f"invalid entity ID on line {line_number} of {path.name}"
                )
            number = int(qid[1:])
            if number <= previous_number:
                raise WikidataEntityMergeError(
                    f"entity IDs are not strictly sorted in {path.name}"
                )
            previous_number = number
            yield qid, entity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    merge_wikidata_entities(arguments.inputs, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
