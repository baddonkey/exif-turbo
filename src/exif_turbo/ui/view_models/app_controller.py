from __future__ import annotations

import csv
import html as html_lib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ...data.image_index_repository import ImageIndexRepository
from ...models.search_result import SearchResult
from ..models.exif_list_model import ExifListModel
from ..models.search_list_model import SearchListModel
from ..workers.index_worker import IndexWorker
from ..workers.thumb_worker import ThumbWorker

_PAGE_SIZE = 100


class AppController(QObject):
    statusTextChanged = Signal()
    isIndexingChanged = Signal()
    isBuildingThumbsChanged = Signal()
    detailsHtmlChanged = Signal()
    findScrollFractionChanged = Signal()
    selectedImageSourceChanged = Signal()
    totalResultsChanged = Signal()
    loadedResultsChanged = Signal()

    def __init__(
        self,
        repo: ImageIndexRepository,
        search_model: SearchListModel,
        exif_model: ExifListModel,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._search_model = search_model
        self._exif_model = exif_model
        self._status_text = "Ready"
        self._is_indexing = False
        self._is_building_thumbs = False
        self._details_html = ""
        self._find_scroll_fraction = 0.0
        self._selected_image_source = ""
        self._total_results = 0
        self._loaded_results = 0
        self._loading = False
        self._details_plain_text = ""
        self._query_text = ""
        self._find_text = ""
        self._find_positions: List[Tuple[int, int]] = []
        self._find_index = -1
        self._index_worker: IndexWorker | None = None
        self._thumb_worker: ThumbWorker | None = None

    # ── Properties ───────────────────────────────────────────────────────────

    @Property(str, notify=statusTextChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(bool, notify=isIndexingChanged)
    def isIndexing(self) -> bool:
        return self._is_indexing

    @Property(bool, notify=isBuildingThumbsChanged)
    def isBuildingThumbs(self) -> bool:
        return self._is_building_thumbs

    @Property(str, notify=detailsHtmlChanged)
    def detailsHtml(self) -> str:
        return self._details_html

    @Property(float, notify=findScrollFractionChanged)
    def findScrollFraction(self) -> float:
        return self._find_scroll_fraction

    @Property(str, notify=selectedImageSourceChanged)
    def selectedImageSource(self) -> str:
        return self._selected_image_source

    @Property(int, notify=totalResultsChanged)
    def totalResults(self) -> int:
        return self._total_results

    @Property(int, notify=loadedResultsChanged)
    def loadedResults(self) -> int:
        return self._loaded_results

    # ── Slots ─────────────────────────────────────────────────────────────────

    @Slot(str)
    def search(self, query: str) -> None:
        self._query_text = query.strip()
        rows = self._repo.search_images(self._query_text, _PAGE_SIZE, 0)
        results = [SearchResult(path=r[1], filename=r[2], metadata_json=r[3]) for r in rows]
        self._search_model.set_rows(results)
        total = self._repo.count_images(self._query_text)
        self._total_results = total
        self._loaded_results = len(results)
        self._loading = False
        self.totalResultsChanged.emit()
        self.loadedResultsChanged.emit()
        self._set_status(f"{len(results)} of {total} results")
        if results:
            self.selectResult(0)
        else:
            self._clear_details()

    @Slot()
    def loadMore(self) -> None:
        if self._loading or self._loaded_results >= self._total_results:
            return
        self._loading = True
        rows = self._repo.search_images(self._query_text, _PAGE_SIZE, self._loaded_results)
        results = [SearchResult(path=r[1], filename=r[2], metadata_json=r[3]) for r in rows]
        self._search_model.append_rows(results)
        self._loaded_results += len(results)
        self.loadedResultsChanged.emit()
        self._set_status(f"{self._loaded_results} of {self._total_results} results")
        self._loading = False

    @Slot(int)
    def selectResult(self, row: int) -> None:
        meta_json = self._search_model.get_metadata_json(row)
        path = self._search_model.get_path(row)
        if not meta_json:
            self._clear_details()
            return
        try:
            parsed = json.loads(meta_json)
            plain_text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            plain_text = meta_json
        self._details_plain_text = plain_text
        self._find_text = ""
        self._find_positions = []
        self._find_index = -1
        self._update_details_html()
        self._update_exif_table(meta_json)
        if path and os.path.exists(path):
            self._selected_image_source = QUrl.fromLocalFile(path).toString()
        else:
            self._selected_image_source = ""
        self.selectedImageSourceChanged.emit()

    @Slot(str)
    def findNext(self, find_text: str) -> None:
        if find_text != self._find_text:
            self._find_text = find_text
            self._find_positions = self._find_all(self._details_plain_text, find_text)
            self._find_index = -1
        if not self._find_positions:
            return
        self._find_index = (self._find_index + 1) % len(self._find_positions)
        self._update_find_scroll()
        self._update_details_html()

    @Slot(str)
    def findPrev(self, find_text: str) -> None:
        if find_text != self._find_text:
            self._find_text = find_text
            self._find_positions = self._find_all(self._details_plain_text, find_text)
            self._find_index = len(self._find_positions)
        if not self._find_positions:
            return
        self._find_index = (self._find_index - 1) % len(self._find_positions)
        self._update_find_scroll()
        self._update_details_html()

    @Slot(str)
    def startIndexing(self, folder_url: str) -> None:
        folder = Path(QUrl(folder_url).toLocalFile())
        if not folder.is_dir():
            return
        self._clear_thumbnail_cache()
        self._is_indexing = True
        self.isIndexingChanged.emit()
        self._set_status("Indexing...")
        self._index_worker = IndexWorker(self._repo.db_path, [folder], workers=12)
        self._index_worker.finished.connect(self._on_index_done)
        self._index_worker.failed.connect(self._on_index_failed)
        self._index_worker.progress.connect(self._on_index_progress)
        self._index_worker.canceled.connect(self._on_index_canceled)
        self._index_worker.start()

    @Slot()
    def cancelIndex(self) -> None:
        if self._index_worker and self._index_worker.isRunning():
            self._set_status("Canceling...")
            self._index_worker.cancel()

    @Slot()
    def buildThumbnails(self) -> None:
        rows = self._repo.all_images()
        paths = [r[0] for r in rows]
        if not paths:
            return
        self._is_building_thumbs = True
        self.isBuildingThumbsChanged.emit()
        self._set_status("Building thumbnails...")
        self._thumb_worker = ThumbWorker(
            paths,
            self._search_model.cache_dir,
            self._search_model.max_thumb_bytes,
            workers=12,
        )
        self._thumb_worker.progress.connect(self._on_thumb_progress)
        self._thumb_worker.finished.connect(self._on_thumb_done)
        self._thumb_worker.failed.connect(self._on_thumb_failed)
        self._thumb_worker.canceled.connect(self._on_thumb_canceled)
        self._thumb_worker.start()

    @Slot()
    def cancelThumbnails(self) -> None:
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._set_status("Canceling thumbs...")
            self._thumb_worker.cancel()

    @Slot(str)
    def exportCsv(self, file_url: str) -> None:
        file_path = Path(QUrl(file_url).toLocalFile())
        query = self._query_text
        total = self._repo.count_images(query)
        if total == 0:
            return
        batch_size = 500
        offset = 0
        records: list[dict] = []
        all_keys: set[str] = set()
        while offset < total:
            rows = self._repo.search_images(query, batch_size, offset)
            for r in rows:
                meta: dict = {}
                try:
                    parsed = json.loads(r[3])
                    if isinstance(parsed, dict):
                        meta = self._flatten(parsed)
                except Exception:
                    pass
                all_keys.update(meta.keys())
                records.append({"path": r[1], "filename": r[2], **meta})
            offset += batch_size
        headers = ["path", "filename"] + sorted(all_keys)
        with open(file_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                writer.writerow(record)
        self._set_status("CSV export completed.")

    @Slot(str)
    def openImage(self, path: str) -> None:
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def openFolder(self, path: str) -> None:
        if not path:
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ── Private helpers ───────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        if self._status_text != text:
            self._status_text = text
            self.statusTextChanged.emit()

    def _clear_details(self) -> None:
        self._details_plain_text = ""
        self._details_html = ""
        self.detailsHtmlChanged.emit()
        self._exif_model.set_rows([])
        self._selected_image_source = ""
        self.selectedImageSourceChanged.emit()

    def _update_exif_table(self, meta_json: str) -> None:
        try:
            parsed = json.loads(meta_json)
            if isinstance(parsed, dict):
                rows = sorted(
                    [(str(k), str(v)) for k, v in parsed.items()],
                    key=lambda r: r[0].lower(),
                )
                self._exif_model.set_rows(rows)
                return
        except Exception:
            pass
        self._exif_model.set_rows([])

    def _update_details_html(self) -> None:
        text = self._details_plain_text
        ranges: List[Tuple[int, int, str]] = []
        if self._query_text:
            for s, e in self._find_all(text, self._query_text):
                ranges.append((s, e, "#fff176"))
        if self._find_positions and self._find_index >= 0:
            s, e = self._find_positions[self._find_index]
            ranges.append((s, e, "#ffab40"))
        self._details_html = self._build_html(text, ranges)
        self.detailsHtmlChanged.emit()

    def _update_find_scroll(self) -> None:
        if not self._find_positions or self._find_index < 0:
            return
        char_pos = self._find_positions[self._find_index][0]
        text_len = len(self._details_plain_text)
        self._find_scroll_fraction = char_pos / text_len if text_len else 0.0
        self.findScrollFractionChanged.emit()

    def _on_index_done(self, count: int) -> None:
        self._is_indexing = False
        self.isIndexingChanged.emit()
        self._set_status(f"Indexed {count} images")
        self.search(self._query_text)

    def _on_index_failed(self, error: str) -> None:
        self._is_indexing = False
        self.isIndexingChanged.emit()
        self._set_status(f"Index failed: {error}")

    def _on_index_canceled(self, count: int) -> None:
        self._is_indexing = False
        self.isIndexingChanged.emit()
        self._set_status("Index canceled")
        self.search(self._query_text)

    def _on_index_progress(self, current: int, total: int, path: str) -> None:
        self._set_status(f"Indexing... {current} / {total}")

    def _on_thumb_progress(self, current: int, total: int, path: str) -> None:
        self._set_status(f"Building thumbnails... {current} / {total}")

    def _on_thumb_done(self, cached: int, total: int) -> None:
        self._is_building_thumbs = False
        self.isBuildingThumbsChanged.emit()
        self._set_status(f"Thumbnails cached: {cached} / {total}")
        self._search_model.refresh_thumbnails()

    def _on_thumb_failed(self, error: str) -> None:
        self._is_building_thumbs = False
        self.isBuildingThumbsChanged.emit()
        self._set_status(f"Build thumbs failed: {error}")

    def _on_thumb_canceled(self, cached: int, total: int) -> None:
        self._is_building_thumbs = False
        self.isBuildingThumbsChanged.emit()
        self._set_status("Build thumbs canceled")

    def _clear_thumbnail_cache(self) -> None:
        cache_dir = Path(tempfile.gettempdir()) / "exif_turbo_thumbs"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _find_all(text: str, query: str) -> List[Tuple[int, int]]:
        if not query:
            return []
        positions: List[Tuple[int, int]] = []
        lower_text = text.lower()
        lower_query = query.lower()
        start = 0
        while True:
            pos = lower_text.find(lower_query, start)
            if pos == -1:
                break
            positions.append((pos, pos + len(query)))
            start = pos + 1
        return positions

    @staticmethod
    def _build_html(text: str, ranges: List[Tuple[int, int, str]]) -> str:
        sorted_ranges = sorted(ranges, key=lambda r: r[0])
        parts: List[str] = [
            "<pre style=\"font-family: 'Consolas', 'Courier New', monospace;"
            " white-space: pre-wrap; word-break: break-all;"
            " font-size: 11pt; margin: 0; padding: 8px;\">"
        ]
        last = 0
        for start, end, color in sorted_ranges:
            if start < last:
                continue
            parts.append(html_lib.escape(text[last:start]))
            parts.append(f'<span style="background-color:{color}">')
            parts.append(html_lib.escape(text[start:end]))
            parts.append("</span>")
            last = end
        parts.append(html_lib.escape(text[last:]))
        parts.append("</pre>")
        return "".join(parts)

    @staticmethod
    def _flatten(metadata: dict) -> dict:
        flat: dict = {}
        for key, value in metadata.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    flat[f"{key}:{sub_key}"] = str(sub_value)
            else:
                flat[str(key)] = str(value)
        return flat
