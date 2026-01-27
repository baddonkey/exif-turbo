from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QPixmap

from ...models.search_result import SearchResult
from ...utils.thumb_cache import thumb_cache_path


class SearchModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: List[SearchResult] = []
        self._pixmaps: List[QPixmap | None] = []
        self._cache_dir = Path(tempfile.gettempdir()) / "exif_turbo_thumbs"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_thumb_bytes = 200 * 1024 * 1024

    def _thumb_cache_path(self, path: str) -> Path:
        return thumb_cache_path(path, self._cache_dir)

    def set_rows(self, rows: List[SearchResult]) -> None:
        self.beginResetModel()
        self._rows = rows
        self._pixmaps = [None] * len(rows)
        self.endResetModel()

    def append_rows(self, rows: List[SearchResult]) -> None:
        if not rows:
            return
        start = len(self._rows)
        end = start + len(rows) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._rows.extend(rows)
        self._pixmaps.extend([None] * len(rows))
        self.endInsertRows()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 3

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        item = self._rows[row]

        if role == Qt.TextAlignmentRole and col == 0:
            return Qt.AlignCenter
        if role == Qt.DisplayRole:
            if col == 1:
                return item.filename
            if col == 2:
                return item.path
        if role == Qt.DecorationRole and col == 0:
            if self._pixmaps[row] is None:
                cache_path = self._thumb_cache_path(item.path)
                if cache_path.exists():
                    pix = QPixmap(str(cache_path))
                else:
                    try:
                        if os.path.getsize(item.path) > self._max_thumb_bytes:
                            return None
                    except OSError:
                        return None
                    pix = QPixmap(item.path)
                    if not pix.isNull():
                        pix = pix.scaled(
                            144,
                            144,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                        pix.save(str(cache_path), "PNG")
                if not pix.isNull():
                    self._pixmaps[row] = pix
            return self._pixmaps[row]
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ["Preview", "File", "Path"][section]

    def get_path(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].path
        return None

    def get_metadata_json(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].metadata_json
        return None
