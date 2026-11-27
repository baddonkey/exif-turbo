from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ...data.ai_search_session import AiSearchSession
from ...data.ai_vector_backend import AiVectorBackend
from ...data.image_index_repository import ImageIndexRepository
from ...i18n import _
from ...indexing.ai_indexer_service import AiIndexerService


class AiSearchWorker(QThread):
    """Run a CLIP vector search off the GUI thread.

    Encodes *query_text* with the CLIP text encoder, queries the active AI index,
    then hydrates the resulting paths into full image rows from the SQLite DB
    and emits them through the same ``results_ready`` signal shape as
    :class:`~exif_turbo.ui.workers.search_worker.SearchWorker` so the
    controller can reuse ``_on_search_finished`` verbatim.

    Signals
    -------
    results_ready(rows, total, format_counts, serial)
        *rows* is a list of ``(id, path, filename, metadata_json, size, mtime)``
        tuples ordered by cosine similarity (highest first).
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
        image_set_id: int | None = None,
        session: AiSearchSession | None = None,
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
        self._image_set_id = image_set_id
        self._session = session or AiSearchSession(db_path)
        self._owns_session = session is None
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
            with self._session.repository(self._key) as vector_repo:
                rows = self._search(vector_repo)
            self.results_ready.emit(rows, len(rows), [], self._serial)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if self._owns_session:
                self._session.close()
            self._key = ""

    def _search(
        self, vector_repo: AiVectorBackend
    ) -> list[tuple[int, str, str, str, int, float]]:
        image_repo = ImageIndexRepository(self._db_path, key=self._key)
        try:
            # Facet scope excludes dates so selecting a year keeps the timeline.
            facet_allowed_paths = image_repo.get_filtered_paths(
                path_filter=self._path_filter,
                ext_filter=self._ext_filter,
                restrict_to_enabled_folders=True,
                image_set_id=self._image_set_id,
            )
            if not facet_allowed_paths:
                self.facet_paths = []
                return []

            display_allowed_paths = facet_allowed_paths
            if self._date_from is not None or self._date_to is not None:
                display_allowed_paths = image_repo.get_filtered_paths(
                    path_filter=self._path_filter,
                    ext_filter=self._ext_filter,
                    restrict_to_enabled_folders=True,
                    date_from=self._date_from,
                    date_to=self._date_to,
                    image_set_id=self._image_set_id,
                )

            query_text = self._query_text.strip()
            if query_text:
                if not vector_repo.get_vector_count():
                    raise RuntimeError(_(
                        "AI index is empty. Run AI Full Scan for every indexed folder."
                    ))
                service = AiIndexerService(vector_repo)
                query_vec = service.encode_text(query_text)

                hits = vector_repo.search_filtered(
                    query_vec,
                    facet_allowed_paths,
                    top_k=None,
                    threshold=self._threshold,
                )
                ranked_facet_paths = [path for path, _ in hits]
                ranked_paths = [
                    path for path in ranked_facet_paths if path in display_allowed_paths
                ][:self._MAX_RESULTS]
            else:
                ranked_facet_paths = sorted(facet_allowed_paths)
                ranked_paths = [path for path in ranked_facet_paths if path in display_allowed_paths]

            self.facet_paths = list(ranked_facet_paths)

            rows = image_repo.get_images_by_paths(
                ranked_paths,
                path_filter=self._path_filter,
                ext_filter=self._ext_filter,
                restrict_to_enabled_folders=True,
                date_from=self._date_from,
                date_to=self._date_to,
                image_set_id=self._image_set_id,
            )
        finally:
            image_repo.close()
        return rows
