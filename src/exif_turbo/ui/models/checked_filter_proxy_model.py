from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Signal, Slot

from .search_list_model import SearchListModel


class CheckedFilterProxyModel(QSortFilterProxyModel):
    """Proxy that optionally shows only checked rows from SearchListModel."""

    filterActiveChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._active: bool = False

    # ── Source model wiring ───────────────────────────────────────────────

    def setSourceModel(self, model: SearchListModel | None) -> None:  # type: ignore[override]
        old = self.sourceModel()
        if old is not None:
            try:
                old.dataChanged.disconnect(self._on_source_data_changed)
                old.modelReset.disconnect(self.invalidateFilter)
            except RuntimeError:
                pass
        super().setSourceModel(model)
        if model is not None:
            model.dataChanged.connect(self._on_source_data_changed)
            model.modelReset.connect(self.invalidateFilter)

    def _on_source_data_changed(
        self,
        top_left: QModelIndex,
        bottom_right: QModelIndex,
        roles: list[int],
    ) -> None:
        if self._active and SearchListModel.CheckedRole in roles:
            self.invalidateFilter()

    # ── Filter control ────────────────────────────────────────────────────

    @property
    def filter_active(self) -> bool:
        return self._active

    @Slot(bool)
    def setFilterActive(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.invalidateFilter()
        self.filterActiveChanged.emit()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._active:
            return True
        src = self.sourceModel()
        if src is None:
            return True
        idx = src.index(source_row, 0, source_parent)
        return bool(src.data(idx, SearchListModel.CheckedRole))

    # ── Index helpers (used by AppController) ─────────────────────────────

    def proxy_row_for(self, source_row: int) -> int:
        """Map a source row to its proxy row; -1 if filtered out."""
        src = self.sourceModel()
        if src is None:
            return source_row
        source_idx = src.index(source_row, 0)
        proxy_idx = self.mapFromSource(source_idx)
        return proxy_idx.row()

    def source_row_for(self, proxy_row: int) -> int:
        """Map a proxy row to its source row."""
        proxy_idx = self.index(proxy_row, 0)
        source_idx = self.mapToSource(proxy_idx)
        return source_idx.row() if source_idx.isValid() else proxy_row
