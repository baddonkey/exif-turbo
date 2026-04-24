from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ...models.search_result import SearchResult
from ...utils.thumb_cache import thumb_cache_path


class SearchListModel(QAbstractListModel):
    PathRole = Qt.UserRole + 1
    FilenameRole = Qt.UserRole + 2
    MetadataJsonRole = Qt.UserRole + 3
    ThumbnailSourceRole = Qt.UserRole + 4
    FileSizeRole = Qt.UserRole + 5

    def __init__(self, cache_dir: Path) -> None:
        super().__init__()
        self._rows: List[SearchResult] = []
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_thumb_bytes = 200 * 1024 * 1024

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def max_thumb_bytes(self) -> int:
        return self._max_thumb_bytes

    def roleNames(self) -> dict:
        return {
            self.PathRole: b"path",
            self.FilenameRole: b"filename",
            self.MetadataJsonRole: b"metadataJson",
            self.ThumbnailSourceRole: b"thumbnailSource",
            self.FileSizeRole: b"fileSize",
        }

    def set_rows(self, rows: List[SearchResult]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def append_rows(self, rows: List[SearchResult]) -> None:
        if not rows:
            return
        start = len(self._rows)
        end = start + len(rows) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._rows.extend(rows)
        self.endInsertRows()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        item = self._rows[index.row()]
        if role == self.PathRole:
            return item.path
        if role == self.FilenameRole:
            return item.filename
        if role == self.MetadataJsonRole:
            return item.metadata_json
        if role == self.ThumbnailSourceRole:
            cache_path = thumb_cache_path(item.path, self._cache_dir)
            if cache_path.exists():
                return cache_path.as_uri()
            return ""
        if role == self.FileSizeRole:
            return item.size
        return None

    def refresh_thumbnails(self) -> None:
        if self._rows:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, 0)
            self.dataChanged.emit(top_left, bottom_right, [self.ThumbnailSourceRole])

    def get_path(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].path
        return None

    def get_metadata_json(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].metadata_json
        return None
