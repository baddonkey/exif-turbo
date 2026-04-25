from __future__ import annotations

from typing import List

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ...models.indexed_folder import IndexedFolder


class FolderListModel(QAbstractListModel):
    FolderIdRole = Qt.UserRole + 1
    PathRole = Qt.UserRole + 2
    DisplayNameRole = Qt.UserRole + 3
    EnabledRole = Qt.UserRole + 4
    RecursiveRole = Qt.UserRole + 5
    StatusRole = Qt.UserRole + 6
    ImageCountRole = Qt.UserRole + 7
    ErrorMessageRole = Qt.UserRole + 8

    def __init__(self) -> None:
        super().__init__()
        self._rows: List[IndexedFolder] = []

    def roleNames(self) -> dict:
        return {
            self.FolderIdRole:    b"folderId",
            self.PathRole:        b"path",
            self.DisplayNameRole: b"displayName",
            self.EnabledRole:     b"enabled",
            self.RecursiveRole:   b"recursive",
            self.StatusRole:      b"status",
            self.ImageCountRole:  b"imageCount",
            self.ErrorMessageRole: b"errorMessage",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        f = self._rows[index.row()]
        if role == self.FolderIdRole:
            return f.id
        if role == self.PathRole:
            return f.path
        if role == self.DisplayNameRole:
            return f.display_name
        if role == self.EnabledRole:
            return f.enabled
        if role == self.RecursiveRole:
            return f.recursive
        if role == self.StatusRole:
            return f.status
        if role == self.ImageCountRole:
            return f.image_count
        if role == self.ErrorMessageRole:
            return f.error_message or ""
        return None

    def set_rows(self, folders: List[IndexedFolder]) -> None:
        self.beginResetModel()
        self._rows = list(folders)
        self.endResetModel()

    def add_folder(self, folder: IndexedFolder) -> None:
        pos = len(self._rows)
        self.beginInsertRows(QModelIndex(), pos, pos)
        self._rows.append(folder)
        self.endInsertRows()

    def update_folder(self, folder: IndexedFolder) -> None:
        for i, f in enumerate(self._rows):
            if f.id == folder.id:
                self._rows[i] = folder
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, list(self.roleNames().keys()))
                return

    def remove_folder(self, folder_id: int) -> None:
        for i, f in enumerate(self._rows):
            if f.id == folder_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._rows[i]
                self.endRemoveRows()
                return
