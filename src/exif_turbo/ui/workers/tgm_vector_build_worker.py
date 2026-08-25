from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...config import (
    ai_id_map_path,
    ai_index_path,
    ai_vector_metadata_path,
    bundled_public_figure_vocabulary_path,
    bundled_vocabulary_path,
    public_figure_concept_map_path,
    public_figure_term_index_path,
    public_figure_vector_metadata_path,
    tgm_concept_map_path,
    tgm_term_index_path,
    tgm_vector_metadata_path,
)
from ...data.ai_vector_repository import AiVectorRepository
from ...data.tgm_vector_repository import TgmVectorRepository
from ...indexing.ai_indexer_service import AiIndexerService
from ...tagging.tgm_vector_index_service import TgmVectorIndexService
from ...tagging.public_figure_prompt_builder import PublicFigurePromptBuilder
from ...tagging.vocabulary_snapshot_repository import VocabularySnapshotRepository


class TgmVectorBuildWorker(QThread):
    progress = Signal(int, int, str)
    result_ready = Signal(object)
    failed = Signal(str)
    canceled = Signal(object)

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self._db_path = db_path
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            image_vectors = AiVectorRepository(
                ai_index_path(self._db_path),
                ai_id_map_path(self._db_path),
                ai_vector_metadata_path(self._db_path),
            )
            image_vectors.load()
            term_vectors = TgmVectorRepository(
                tgm_term_index_path(self._db_path),
                tgm_concept_map_path(self._db_path),
                tgm_vector_metadata_path(self._db_path),
            )
            term_vectors.load_for_rebuild()
            service = TgmVectorIndexService(
                VocabularySnapshotRepository(bundled_vocabulary_path()),
                term_vectors,
                AiIndexerService(image_vectors),
            )
            result = service.build(
                on_progress=self.progress.emit,
                cancel_check=self._cancel_event.is_set,
            )
            if result.completed:
                public_figure_path = bundled_public_figure_vocabulary_path()
                if public_figure_path.exists():
                    public_figure_vectors = TgmVectorRepository(
                        public_figure_term_index_path(self._db_path),
                        public_figure_concept_map_path(self._db_path),
                        public_figure_vector_metadata_path(self._db_path),
                    )
                    public_figure_vectors.load_for_rebuild()
                    result = TgmVectorIndexService(
                        VocabularySnapshotRepository(public_figure_path),
                        public_figure_vectors,
                        AiIndexerService(image_vectors),
                        PublicFigurePromptBuilder(),
                    ).build(
                        on_progress=self.progress.emit,
                        cancel_check=self._cancel_event.is_set,
                    )
            if not result.completed:
                self.canceled.emit(result)
                return
            self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))