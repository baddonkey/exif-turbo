from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...config import (
    ai_id_map_path,
    ai_index_path,
    ai_vector_metadata_path,
    bundled_vocabulary_path,
    tgm_concept_map_path,
    tgm_snapshot_path,
    tgm_term_index_path,
    tgm_vector_metadata_path,
)
from ...data.ai_vector_repository import AiVectorRepository
from ...data.image_index_repository import ImageIndexRepository
from ...data.tgm_vector_repository import TgmVectorRepository
from ...tagging.sidecar_repository import FilesystemSidecarRepository
from ...tagging.tagging_service import TaggingService
from ...tagging.tgm_clip_proposal_provider import TgmClipProposalProvider
from ...tagging.tgm_proposal_service import TgmProposalService
from ...tagging.tgm_snapshot_repository import TgmSnapshotRepository
from ...tagging.tgm_vector_index_service import TgmVectorIndexService
from ...tagging.vocabulary_snapshot_repository import VocabularySnapshotRepository
from ...indexing.ai_indexer_service import AiIndexerService


class TgmProposalWorker(QThread):
    progress = Signal(int, int, str)
    result_ready = Signal(object, object)
    failed = Signal(str)
    canceled = Signal(object)

    def __init__(
        self,
        db_path: Path,
        key: str,
        image_paths: list[str],
        *,
        threshold: float,
        auto_accept_threshold: float | None = None,
        top_k: int = 20,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._key = key
        self._image_paths = tuple(image_paths)
        self._threshold = threshold
        self._auto_accept_threshold = auto_accept_threshold
        self._top_k = top_k
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        image_repository: ImageIndexRepository | None = None
        try:
            image_repository = ImageIndexRepository(self._db_path, key=self._key)
            legacy_tgm = TgmSnapshotRepository(tgm_snapshot_path(self._db_path))
            vocabulary = VocabularySnapshotRepository(bundled_vocabulary_path())
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
            term_vectors.load()
            fingerprint = TgmVectorIndexService(
                vocabulary,
                term_vectors,
                AiIndexerService(image_vectors),
            ).expected_fingerprint()
            proposals = TgmProposalService(
                image_repository,
                TgmClipProposalProvider(image_vectors, term_vectors, vocabulary),
            ).generate(
                self._image_paths,
                fingerprint,
                top_k=self._top_k,
                threshold=self._threshold,
                auto_accept_threshold=self._auto_accept_threshold,
                on_progress=self.progress.emit,
                cancel_check=self._cancel_event.is_set,
            )
            if proposals.cancelled:
                self.canceled.emit(proposals)
                return
            bulk_result = None
            if self._auto_accept_threshold is not None:
                bulk_result = TaggingService(
                    image_repository,
                    FilesystemSidecarRepository(),
                    legacy_tgm,
                    vocabulary_repository=vocabulary,
                ).accept_auto_candidates(
                    proposals,
                    on_progress=self.progress.emit,
                    cancel_check=self._cancel_event.is_set,
                )
            self.result_ready.emit(proposals, bulk_result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if image_repository is not None:
                image_repository.close()