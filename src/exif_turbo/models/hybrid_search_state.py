from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..search_query import parse_hybrid_search_query


@dataclass(frozen=True)
class HybridSearchState:
    query: str
    precision: str
    sort_by: str
    path_filter: tuple[str, ...]
    ext_filter: str
    date_from: int | None
    date_to: int | None
    marked_only: bool
    image_set_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "mode": "hybrid",
            "query": self.query,
            "precision": self.precision,
            "sort_by": self.sort_by,
            "path_filter": list(self.path_filter),
            "ext_filter": self.ext_filter,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "marked_only": self.marked_only,
            "image_set_id": self.image_set_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HybridSearchState:
        if type(data.get("version")) is not int or data.get("version") != 1 or data.get("mode") != "hybrid":
            raise ValueError("Unsupported saved search version or mode.")
        query = data.get("query")
        precision = data.get("precision")
        sort_by = data.get("sort_by")
        paths = data.get("path_filter")
        ext_filter = data.get("ext_filter")
        date_from = data.get("date_from")
        date_to = data.get("date_to")
        marked_only = data.get("marked_only")
        image_set_id = data.get("image_set_id")
        if not isinstance(query, str) or not isinstance(ext_filter, str):
            raise ValueError("Invalid saved search text or format.")
        parse_hybrid_search_query(query)
        if not isinstance(precision, str) or precision not in {"fine", "normal", "broad"}:
            raise ValueError("Invalid saved search precision.")
        if not isinstance(sort_by, str) or sort_by not in {
            "", "filename_asc", "filename_desc", "path_asc", "path_desc",
            "size_asc", "size_desc", "captured_asc", "captured_desc",
        }:
            raise ValueError("Invalid saved search sort order.")
        if not isinstance(paths, list) or not all(isinstance(path, str) and path for path in paths):
            raise ValueError("Invalid saved search folder scope.")
        if any(value is not None and (isinstance(value, bool) or not isinstance(value, int))
               for value in (date_from, date_to)):
            raise ValueError("Invalid saved search date bounds.")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("Invalid saved search date range.")
        if not isinstance(marked_only, bool):
            raise ValueError("Invalid saved search marked filter.")
        if image_set_id is not None and (
            isinstance(image_set_id, bool) or not isinstance(image_set_id, int)
            or image_set_id == 0 or image_set_id < -1
        ):
            raise ValueError("Invalid saved search image-set scope.")
        return cls(
            query, precision, sort_by, tuple(paths), ext_filter,
            date_from, date_to, marked_only, image_set_id,
        )
