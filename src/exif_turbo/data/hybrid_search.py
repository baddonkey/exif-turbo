"""Materialize deterministic Hybrid search references without hydrating images."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..search_query import SearchQueryParseError, parse_hybrid_search_query, parse_search_query
from .ai_vector_backend import AiVectorBackend
from .image_index_repository import ImageIndexRepository

_RRF_K = 60
_MAX_SCOPE_IMAGES = 1_000_000
_MAX_SEMANTIC_RESULTS = 2_000


class HybridSearchCanceled(Exception):
    """Raised when a Hybrid search is canceled before completion."""


class HybridSearchStaleError(RuntimeError):
    """Raised when a materialized image no longer exists under the same ID."""


@dataclass(frozen=True)
class HybridMatch:
    image_id: int
    path: str
    relevance: float
    metadata_rank: int | None
    ai_rank: int | None
    ai_score: float | None


@dataclass(frozen=True)
class HybridSearchResults:
    matches: tuple[HybridMatch, ...]
    facet_paths: tuple[str, ...]
    format_paths: tuple[str, ...]
    total_count: int

    def page(self, after_position: int, page_size: int) -> tuple[HybridMatch, ...]:
        if after_position < 0 or page_size <= 0:
            raise ValueError("Invalid Hybrid page position or size.")
        return self.matches[after_position:after_position + page_size]

    def hydrate_page(
        self, repo: ImageIndexRepository, after_position: int, page_size: int
    ) -> list[tuple[int, str, str, str, int, float]]:
        page = self.page(after_position, page_size)
        rows = repo.get_images_by_ids([match.image_id for match in page])
        if [(row[0], row[1]) for row in rows] != [
            (match.image_id, match.path) for match in page
        ]:
            raise HybridSearchStaleError("Hybrid results changed; repeat the search.")
        return rows


def build_hybrid_results(
    repo: ImageIndexRepository,
    vector_repo: AiVectorBackend | None,
    query: str,
    query_vector: np.ndarray | None,
    *,
    threshold: float = 0.20,
    sort_by: str = "",
    ext_filter: str = "",
    path_filter: list[str] | None = None,
    restrict_to_enabled_folders: bool = False,
    marked_only: bool = False,
    date_from: int | None = None,
    date_to: int | None = None,
    image_set_id: int | None = None,
    canceled: Callable[[], bool] | None = None,
) -> HybridSearchResults:
    """Build one immutable ranking, using a single exhaustive semantic search."""
    parsed = parse_hybrid_search_query(query)
    metadata_text = parse_search_query(parsed.metadata_query).text
    has_metadata_text = bool(repo._sanitize_fts_query(metadata_text))
    if parsed.explicit_and and metadata_text and not has_metadata_text:
        raise SearchQueryParseError("The metadata part of the Hybrid query is empty.")

    def check_canceled() -> None:
        if canceled is not None and canceled():
            raise HybridSearchCanceled("Hybrid search was canceled.")

    def collect(
        *, scope_only: bool, use_date: bool, order: str = "", use_format: bool = True
    ) -> list[tuple[int, str]]:
        refs: list[tuple[int, str]] = []
        for ref in repo.iter_hybrid_candidates(
            parsed.metadata_query,
            scope_only=scope_only,
            sort_by=order,
            ext_filter=ext_filter if use_format else "",
            path_filter=path_filter,
            restrict_to_enabled_folders=restrict_to_enabled_folders,
            marked_only=marked_only,
            date_from=date_from if use_date else None,
            date_to=date_to if use_date else None,
            image_set_id=image_set_id,
        ):
            if len(refs) >= _MAX_SCOPE_IMAGES:
                raise ValueError("Hybrid search scope exceeds the one-million-image memory limit.")
            if len(refs) % 1024 == 0:
                check_canceled()
            refs.append(ref)
        return refs

    check_canceled()
    scope = collect(scope_only=True, use_date=False)
    format_scope = (
        collect(scope_only=True, use_date=False, use_format=False) if ext_filter else scope
    )
    by_path = {path: image_id for image_id, path in format_scope}
    scope_ids = {image_id for image_id, _ in scope}
    date_active = date_from is not None or date_to is not None
    display_scope = (
        {image_id for image_id, _ in collect(scope_only=True, use_date=True)}
        if date_active
        else {image_id for image_id, _ in scope}
    )
    format_display_scope = (
        {image_id for image_id, _ in collect(scope_only=True, use_date=True, use_format=False)}
        if date_active and ext_filter else
        display_scope if date_active else {image_id for image_id, _ in format_scope}
    )
    format_metadata = (
        collect(scope_only=False, use_date=False, use_format=False)
        if has_metadata_text and ext_filter else
        collect(scope_only=False, use_date=False) if has_metadata_text else []
    )
    metadata = [(image_id, path) for image_id, path in format_metadata if image_id in scope_ids]
    display_metadata = [(image_id, path) for image_id, path in metadata if image_id in display_scope]
    semantic: list[tuple[int, str, float]] = []
    if parsed.semantic_text:
        if vector_repo is None or query_vector is None:
            raise RuntimeError("AI search is unavailable; Hybrid search requires an AI index.")
        eligible = {path for _, path in format_metadata} if parsed.explicit_and and has_metadata_text else set(by_path)
        check_canceled()
        hits = vector_repo.search_filtered(
            query_vector, eligible, top_k=None, threshold=threshold
        )
        check_canceled()
        pooled: dict[str, float] = {}
        for path, score in hits:
            if path not in eligible:
                continue
            value = float(score)
            if not math.isfinite(value):
                raise ValueError("AI search returned a non-finite similarity score.")
            if value >= threshold and (path not in pooled or value > pooled[path]):
                pooled[path] = value
        semantic = [(by_path[path], path, score) for path, score in pooled.items()]
        semantic.sort(key=lambda hit: (-hit[2], hit[0]))

    if not parsed.semantic_text:
        ordered = collect(scope_only=True, use_date=True, order=sort_by or "filename_asc")
        matches = tuple(HybridMatch(image_id, path, 0.0, None, None, None) for image_id, path in ordered)
        format_paths = tuple(path for image_id, path in format_scope if image_id in format_display_scope)
        return HybridSearchResults(matches, tuple(path for _, path in scope), format_paths, len(matches))

    format_semantic_ids = {image_id for image_id, _, _ in semantic if image_id in format_display_scope}
    format_metadata_ids = {image_id for image_id, _ in format_metadata if image_id in format_display_scope}
    format_ids = format_semantic_ids if parsed.explicit_and else format_metadata_ids | format_semantic_ids
    format_paths = tuple(path for image_id, path in format_scope if image_id in format_ids)
    semantic = [hit for hit in semantic if hit[0] in scope_ids]
    display_semantic = [hit for hit in semantic if hit[0] in display_scope]
    semantic_total = len(display_semantic)
    display_semantic = display_semantic[:_MAX_SEMANTIC_RESULTS]
    metadata_ranks = {
        image_id: rank for rank, (image_id, _) in enumerate(display_metadata, 1)
    }
    ai_ranks = {
        image_id: (rank, score)
        for rank, (image_id, _, score) in enumerate(display_semantic, 1)
    }
    paths_by_id = {image_id: path for image_id, path in scope}

    if parsed.explicit_and:
        ids = set(ai_ranks)
        total_count = semantic_total
        facet_ids = {image_id for image_id, _, _ in semantic}
    else:
        ids = set(metadata_ranks) | set(ai_ranks)
        total_count = len(set(metadata_ranks) | {image_id for image_id, _, _ in semantic if image_id in display_scope})
        facet_ids = {image_id for image_id, _ in metadata} | {image_id for image_id, _, _ in semantic}

    matches_list: list[HybridMatch] = []
    for image_id in ids:
        metadata_rank = metadata_ranks.get(image_id)
        ai_data = ai_ranks.get(image_id)
        ai_rank, ai_score = ai_data if ai_data is not None else (None, None)
        relevance = (
            float(ai_score) if parsed.explicit_and and ai_score is not None else
            (1 / (_RRF_K + metadata_rank) if metadata_rank is not None else 0.0)
            + (1 / (_RRF_K + ai_rank) if ai_rank is not None else 0.0)
        )
        matches_list.append(HybridMatch(image_id, paths_by_id[image_id], relevance, metadata_rank, ai_rank, ai_score))

    if sort_by:
        order = {
            image_id: position
            for position, (image_id, _) in enumerate(collect(scope_only=True, use_date=True, order=sort_by))
        }
        matches_list.sort(key=lambda match: order[match.image_id])
    else:
        matches_list.sort(key=lambda match: (-match.relevance, match.image_id))
    return HybridSearchResults(
        tuple(matches_list),
        tuple(paths_by_id[image_id] for image_id in sorted(facet_ids)),
        format_paths,
        total_count,
    )
