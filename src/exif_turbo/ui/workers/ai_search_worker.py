from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ...config import ai_id_map_path, ai_index_path
from ...data.ai_vector_repository import AiVectorRepository
from ...data.image_index_repository import ImageIndexRepository
from ...indexing.ai_indexer_service import AiIndexerService


class AiSearchWorker(QThread):
    """Run a CLIP vector search off the GUI thread.

    Encodes *query_text* with the CLIP text encoder, queries the FAISS index,
    then hydrates the resulting paths into full image rows from the SQLite DB
    and emits them through the same ``results_ready`` signal shape as
    :class:`~exif_turbo.ui.workers.search_worker.SearchWorker` so the
    controller can reuse ``_on_search_finished`` verbatim.

    Signals
    -------
    results_ready(rows, total, format_counts, serial)
        *rows* is a list of ``(id, path, filename, metadata_json, size, mtime)``
        tuples ordered by FAISS cosine similarity (highest first).
        *total* equals ``len(rows)``.
        *format_counts* is always ``[]`` (no file-type facets in AI mode).
        *serial* matches the constructor argument.
    failed(str)
        Emitted if the search raises an exception.
    """

    results_ready: Signal = Signal(list, int, list, int)
    failed: Signal = Signal(str)

    _PRECISION_THRESHOLD: dict[str, float] = {
        "fine":   0.22,
        "normal": 0.20,
        "broad":  0.18,
    }
    _MAX_RESULTS = 2000

    def __init__(
        self,
        db_path: Path,
        key: str,
        query_text: str,
        serial: int,
        *,
        precision: str = "normal",
        path_filter: List[str] | None = None,
        ext_filter: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._query_text = query_text
        self._serial = serial
        self._threshold = self._PRECISION_THRESHOLD.get(precision, 0.20)
        self._path_filter = path_filter
        self._ext_filter = ext_filter
        self._date_from = date_from
        self._date_to = date_to
        # Semantic result paths BEFORE the date filter is applied.  The
        # controller reads this to build the year-histogram so selecting a
        # single year does not collapse the other selectable years.
        self.facet_paths: List[str] = []
        # macOS limits secondary thread stacks to 512 kB by default, which is
        # too small for the lazy torch + open_clip imports.  64 MB gives ample
        # headroom without measurable overhead.
        self.setStackSize(64 * 1024 * 1024)

    def run(self) -> None:
        try:
            index_path = ai_index_path(self._db_path)
            id_map_path = ai_id_map_path(self._db_path)

            vector_repo = AiVectorRepository(index_path, id_map_path)
            vector_repo.load()

            image_repo = ImageIndexRepository(self._db_path, key=self._key)
            try:
                # Facet scope: path/ext/folder filters WITHOUT the date filter.
                # Drives the timeline so picking a single year does not collapse
                # the other selectable years.
                facet_allowed_paths = image_repo.get_filtered_paths(
                    path_filter=self._path_filter,
                    ext_filter=self._ext_filter,
                    restrict_to_enabled_folders=True,
                )
                if not facet_allowed_paths:
                    self.facet_paths = []
                    self.results_ready.emit([], 0, [], self._serial)
                    return

                query_text = self._query_text.strip()
                if query_text:
                    service = AiIndexerService(vector_repo)
                    query_vec = service.encode_text(query_text)

                    hits = vector_repo.search_filtered(
                        query_vec,
                        facet_allowed_paths,
                        top_k=self._MAX_RESULTS,
                        threshold=self._threshold,
                    )
                    ranked_facet_paths = [path for path, _score in hits]
                else:
                    # Empty AI query means "show everything in scope".
                    ranked_facet_paths = sorted(facet_allowed_paths)

                # The timeline facet source is the full semantic set, before the
                # date filter narrows the displayed rows.
                self.facet_paths = list(ranked_facet_paths)

                # Displayed rows additionally honour the active date filter.
                if self._date_from is not None or self._date_to is not None:
                    date_allowed_paths = image_repo.get_filtered_paths(
                        path_filter=self._path_filter,
                        ext_filter=self._ext_filter,
                        restrict_to_enabled_folders=True,
                        date_from=self._date_from,
                        date_to=self._date_to,
                    )
                    ranked_paths = [
                        path for path in ranked_facet_paths
                        if path in date_allowed_paths
                    ]
                else:
                    ranked_paths = ranked_facet_paths

                rows = image_repo.get_images_by_paths(
                    ranked_paths,
                    path_filter=self._path_filter,
                    ext_filter=self._ext_filter,
                    restrict_to_enabled_folders=True,
                    date_from=self._date_from,
                    date_to=self._date_to,
                )
            finally:
                image_repo.close()

            self.results_ready.emit(rows, len(rows), [], self._serial)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
