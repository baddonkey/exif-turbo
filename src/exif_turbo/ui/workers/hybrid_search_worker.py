from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from PySide6.QtCore import QThread, Signal

from ...data.ai_search_session import AiSearchSession
from ...data.hybrid_search import (
    HybridSearchCanceled,
    HybridSearchResults,
    build_hybrid_results,
)
from ...data.image_index_repository import ImageIndexRepository
from ...i18n import _
from ...indexing.ai_indexer_service import AiIndexerService
from ...search_query import parse_hybrid_search_query
from .ai_search_worker import AiSearchWorker


class _HybridScope(TypedDict):
    sort_by: str
    path_filter: list[str] | None
    ext_filter: str
    restrict_to_enabled_folders: bool
    marked_only: bool
    date_from: int | None
    date_to: int | None
    image_set_id: int | None


class HybridSearchWorker(QThread):
    """Build a Hybrid generation off the UI thread and hydrate its first page."""

    results_ready: Signal = Signal(list, int, int)
    failed: Signal = Signal(str, int)
    canceled: Signal = Signal(int)

    def __init__(
        self,
        db_path: Path,
        key: str,
        query: str,
        serial: int,
        *,
        page_size: int = 50,
        precision: str = "normal",
        sort_by: str = "",
        path_filter: list[str] | None = None,
        ext_filter: str = "",
        restrict_to_enabled_folders: bool = True,
        marked_only: bool = False,
        date_from: int | None = None,
        date_to: int | None = None,
        image_set_id: int | None = None,
        session: AiSearchSession | None = None,
        cached_results: HybridSearchResults | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._query = query
        self._serial = serial
        self._page_size = page_size
        if precision not in AiSearchWorker._PRECISION_THRESHOLD:
            raise ValueError(f"Unknown AI search precision: {precision}")
        self._threshold = AiSearchWorker._PRECISION_THRESHOLD[precision]
        self._options: _HybridScope = {
            "sort_by": sort_by,
            "path_filter": path_filter,
            "ext_filter": ext_filter,
            "restrict_to_enabled_folders": restrict_to_enabled_folders,
            "marked_only": marked_only,
            "date_from": date_from,
            "date_to": date_to,
            "image_set_id": image_set_id,
        }
        self._session = session or AiSearchSession(db_path)
        self._owns_session = session is None
        self._cached_results = cached_results
        self.results: HybridSearchResults | None = None
        self.year_counts: list[tuple[int, int]] = []
        self.format_counts: list[tuple[str, int]] = []
        self.setStackSize(64 * 1024 * 1024)

    def run(self) -> None:
        try:
            parsed = parse_hybrid_search_query(self._query)
            repo = ImageIndexRepository(self._db_path, key=self._key)
            try:
                repo.conn.execute("BEGIN")
                if self.isInterruptionRequested():
                    raise HybridSearchCanceled("Hybrid search was canceled.")
                if self._cached_results is not None:
                    self.results = self._sort_cached(repo, parsed.metadata_query, bool(parsed.semantic_text))
                elif parsed.semantic_text:
                    with self._session.repository(self._key) as vectors:
                        if not vectors.get_vector_count():
                            raise RuntimeError(_(
                                "AI index is empty. Run AI Full Scan for every indexed folder."
                            ))
                        if self.isInterruptionRequested():
                            raise HybridSearchCanceled("Hybrid search was canceled.")
                        query_vector = AiIndexerService(vectors).encode_text(parsed.semantic_text)
                        self.results = build_hybrid_results(
                            repo, vectors, self._query, query_vector,
                            threshold=self._threshold,
                            canceled=self.isInterruptionRequested,
                            **self._options,
                        )
                else:
                    self.results = build_hybrid_results(
                        repo, None, self._query, None,
                        canceled=self.isInterruptionRequested,
                        **self._options,
                    )
                if self.isInterruptionRequested():
                    raise HybridSearchCanceled("Hybrid search was canceled.")
                rows = self.results.hydrate_page(repo, 0, self._page_size)
                self.year_counts = repo.get_year_counts_by_paths(list(self.results.facet_paths))
                self.format_counts = repo.get_format_counts_by_paths(
                    list(self.results.format_paths)
                )
                if self.isInterruptionRequested():
                    raise HybridSearchCanceled("Hybrid search was canceled.")
                self.results_ready.emit(rows, len(self.results.matches), self._serial)
            finally:
                repo.close()
        except HybridSearchCanceled:
            self.results = None
            self.canceled.emit(self._serial)
        except Exception as exc:  # noqa: BLE001
            self.results = None
            self.failed.emit(str(exc), self._serial)
        finally:
            if self._owns_session:
                self._session.close()
            self._key = ""

    def _sort_cached(
        self, repo: ImageIndexRepository, metadata_query: str, has_semantic_text: bool
    ) -> HybridSearchResults:
        results = self._cached_results
        if results is None:
            raise RuntimeError("Hybrid results are unavailable for sorting.")
        if not self._options["sort_by"] and has_semantic_text:
            matches = sorted(results.matches, key=lambda match: (-match.relevance, match.image_id))
        else:
            matches_by_id = {match.image_id: match for match in results.matches}
            matches = []
            options = {**self._options, "sort_by": self._options["sort_by"] or "filename_asc"}
            for position, (image_id, _) in enumerate(
                repo.iter_hybrid_candidates(metadata_query, scope_only=True, **options)
            ):
                if position % 1024 == 0 and self.isInterruptionRequested():
                    raise HybridSearchCanceled("Hybrid search was canceled.")
                match = matches_by_id.get(image_id)
                if match is not None:
                    matches.append(match)
            if len(matches) != len(results.matches):
                raise RuntimeError("Hybrid results changed; repeat the search.")
        return HybridSearchResults(
            tuple(matches), results.facet_paths, results.format_paths, results.total_count
        )
