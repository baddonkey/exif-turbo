from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ...models.search_result import SearchResult
from ...utils.thumb_cache import thumb_cache_name_from_stamp, thumb_cache_path


def _extract_display(metadata_json: str) -> Dict[str, str]:
    """Parse metadata_json once and return the pre-formatted display strings."""
    try:
        exif = json.loads(metadata_json)
    except Exception:
        exif = {}

    # Camera
    make   = exif.get("EXIF:Make")  or exif.get("IFD0:Make")  or exif.get("XMP:Make")  or ""
    model  = exif.get("EXIF:Model") or exif.get("IFD0:Model") or exif.get("XMP:Model") or ""
    if make and model:
        camera = model.strip() if model.startswith(make) else f"{make} {model}".strip()
    else:
        camera = (make or model).strip()

    # Date
    d = (exif.get("EXIF:DateTimeOriginal") or exif.get("EXIF:DateTime")
         or exif.get("IFD0:ModifyDate") or "")
    date = d.replace("T", " ").split(".")[0] if d else ""

    # Dimensions
    w = exif.get("EXIF:ExifImageWidth")  or exif.get("File:ImageWidth")  or exif.get("PNG:ImageWidth")  or ""
    h = exif.get("EXIF:ExifImageHeight") or exif.get("File:ImageHeight") or exif.get("PNG:ImageHeight") or ""
    dims = f"{w} × {h}" if (w and h) else ""

    # Lens / exposure
    fl  = exif.get("EXIF:FocalLength") or ""
    fn  = exif.get("EXIF:FNumber")     or exif.get("EXIF:ApertureValue") or ""
    iso = exif.get("EXIF:ISO")         or exif.get("EXIF:ISOSpeedRatings") or ""
    parts = []
    if fl:  parts.append(f"{fl} mm")
    if fn:  parts.append(f"\u0192/{fn}")
    if iso: parts.append(f"ISO {iso}")
    lens = "  ".join(parts)

    return {"camera": camera, "date": date, "dims": dims, "lens": lens}


class SearchListModel(QAbstractListModel):
    PathRole = Qt.UserRole + 1
    FilenameRole = Qt.UserRole + 2
    MetadataJsonRole = Qt.UserRole + 3
    ThumbnailSourceRole = Qt.UserRole + 4
    FileSizeRole = Qt.UserRole + 5
    CheckedRole = Qt.UserRole + 6
    CameraRole = Qt.UserRole + 7
    DateRole = Qt.UserRole + 8
    DimsRole = Qt.UserRole + 9
    LensRole = Qt.UserRole + 10

    def __init__(self, cache_dir: Path) -> None:
        super().__init__()
        self._rows: List[SearchResult] = []
        self._thumbnail_uris: List[Optional[str]] = []
        self._display_cache: List[Optional[Dict[str, str]]] = []
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._encrypted: bool = False
        self._cached_files: set[str] = self._scan_cache_dir()
        self._checked: set[str] = set()  # file paths — persists across searches
        # path -> bust counter; appended as ?t=<n> to the thumb URI so QML's
        # pixmap cache refetches after recreateThumbnail rebuilds the file.
        self._thumb_bust: Dict[str, int] = {}

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def roleNames(self) -> dict:
        return {
            self.PathRole: b"path",
            self.FilenameRole: b"filename",
            self.MetadataJsonRole: b"metadataJson",
            self.ThumbnailSourceRole: b"thumbnailSource",
            self.FileSizeRole: b"fileSize",
            self.CheckedRole: b"checked",
            self.CameraRole: b"camera",
            self.DateRole: b"date",
            self.DimsRole: b"dims",
            self.LensRole: b"lens",
        }

    def _scan_cache_dir(self) -> set[str]:
        """Return the set of cache filenames currently in the cache directory."""
        result: set[str] = set()
        suffix = ".enc" if self._encrypted else ".png"
        try:
            with os.scandir(self._cache_dir) as it:
                for entry in it:
                    if entry.name.endswith(suffix):
                        result.add(entry.name)
        except OSError:
            pass
        return result

    def _thumbnail_uri(self, item: SearchResult) -> str:
        """Compute the thumbnail cache URI using DB-stored stamps (no live os.stat).

        Always returns an ``image://thumb/<sha1>`` URI (encrypted or plain),
        so QML's pixmap cache can be busted via a ``?t=<n>`` query string —
        see :meth:`bust_thumbnail`.
        """
        if item.mtime:
            name = thumb_cache_name_from_stamp(item.path, item.mtime, item.size)
        else:
            # Fallback for rows without mtime (legacy DB entries)
            name = thumb_cache_path(item.path, self._cache_dir).name
        sha1 = name[:-4]  # strip ".png" suffix
        if self._encrypted:
            if (sha1 + ".enc") not in self._cached_files:
                return ""
        else:
            if name not in self._cached_files:
                return ""
        bust = self._thumb_bust.get(item.path, 0)
        if bust:
            return f"image://thumb/{sha1}?t={bust}"
        return f"image://thumb/{sha1}"

    def set_rows(self, rows: List[SearchResult]) -> None:
        self.beginResetModel()
        self._rows = rows
        self._thumbnail_uris = [None] * len(rows)  # computed lazily on first access
        self._display_cache = [None] * len(rows)
        # _checked is intentionally NOT cleared — marks persist across searches
        self.endResetModel()

    def append_rows(self, rows: List[SearchResult]) -> None:
        if not rows:
            return
        start = len(self._rows)
        end = start + len(rows) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._rows.extend(rows)
        self._thumbnail_uris.extend([None] * len(rows))  # computed lazily on first access
        self._display_cache.extend([None] * len(rows))
        self.endInsertRows()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = index.row()
        item = self._rows[row]
        if role == self.PathRole:
            return item.path
        if role == self.FilenameRole:
            return item.filename
        if role == self.MetadataJsonRole:
            return item.metadata_json
        if role == self.ThumbnailSourceRole:
            if self._thumbnail_uris[row] is None:
                self._thumbnail_uris[row] = self._thumbnail_uri(item)
            return self._thumbnail_uris[row]
        if role == self.FileSizeRole:
            return item.size
        if role == self.CheckedRole:
            return item.path in self._checked
        if role in (self.CameraRole, self.DateRole, self.DimsRole, self.LensRole):
            if self._display_cache[row] is None:
                self._display_cache[row] = _extract_display(item.metadata_json)
            d = self._display_cache[row]
            assert d is not None
            if role == self.CameraRole: return d["camera"]
            if role == self.DateRole:   return d["date"]
            if role == self.DimsRole:   return d["dims"]
            if role == self.LensRole:   return d["lens"]
        return None

    def refresh_thumbnails(self) -> None:
        # Re-scan the cache dir so newly built thumbs are picked up.
        self._cached_files = self._scan_cache_dir()
        if self._rows:
            self._thumbnail_uris = [None] * len(self._rows)  # reset; recomputed lazily on next access
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, 0)
            self.dataChanged.emit(top_left, bottom_right, [self.ThumbnailSourceRole])

    def bust_thumbnail(self, row: int) -> None:
        """Force QML to refetch the thumbnail for *row* on next bind.

        Increments a per-path bust counter that is appended as a ``?t=<n>``
        query string to the ``image://thumb/<sha1>`` URI.  QML's
        ``QQuickPixmapCache`` keys on the full URL, so the new URL bypasses
        the in-memory cache and the provider re-reads the file from disk.
        """
        if not (0 <= row < len(self._rows)):
            return
        path = self._rows[row].path
        self._thumb_bust[path] = self._thumb_bust.get(path, 0) + 1
        # Re-scan in case the rebuilt file isn't yet present (URI will be
        # empty until the worker writes it; refresh_thumbnails will pick it
        # up on the next periodic tick).
        self._cached_files = self._scan_cache_dir()
        self._thumbnail_uris[row] = None
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.ThumbnailSourceRole])

    def set_encryption(self, encrypted: bool) -> None:
        """Switch between plain PNG (``encrypted=False``) and encrypted .enc mode."""
        if self._encrypted == encrypted:
            return
        self._encrypted = encrypted
        self._cached_files = self._scan_cache_dir()
        if self._rows:
            self._thumbnail_uris = [None] * len(self._rows)
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, 0)
            self.dataChanged.emit(top_left, bottom_right, [self.ThumbnailSourceRole])

    def get_path(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].path
        return None

    def get_stamp(self, row: int) -> tuple[float, int] | None:
        """Return DB-stored ``(mtime, size)`` for *row*, or ``None`` if unknown.

        Used by the preview pipeline to compute the on-disk cache filename
        without touching the source file (which may live on a disconnected
        drive).  Legacy rows missing an mtime return ``None``.
        """
        if not (0 <= row < len(self._rows)):
            return None
        item = self._rows[row]
        if not item.mtime:
            return None
        return (item.mtime, item.size)

    def get_pixel_count(self, row: int) -> int | None:
        """Return ``width * height`` parsed from stored exiftool metadata, or ``None``.

        Used by the preview/raw providers to skip a live file probe and route
        large images directly to pyvips without opening the source file.
        """
        if not (0 <= row < len(self._rows)):
            return None
        item = self._rows[row]
        if not item.metadata_json:
            return None
        try:
            meta = json.loads(item.metadata_json)
            for w_key, h_key in (
                ("File:ImageWidth", "File:ImageHeight"),
                ("ExifIFD:ExifImageWidth", "ExifIFD:ExifImageHeight"),
                ("IFD0:ImageWidth", "IFD0:ImageHeight"),
                ("PNG:ImageWidth", "PNG:ImageHeight"),
            ):
                w = meta.get(w_key)
                h = meta.get(h_key)
                if w and h:
                    return int(float(w)) * int(float(h))
        except Exception:  # noqa: BLE001
            pass
        return None

    def get_metadata_json(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].metadata_json
        return None

    # ── Selection helpers ─────────────────────────────────────────────────

    def toggle_checked(self, row: int) -> bool:
        """Flip the mark on *row* and return the new checked state.

        Returns ``False`` for an out-of-range row (no change applied).
        """
        if not (0 <= row < len(self._rows)):
            return False
        path = self._rows[row].path
        if path in self._checked:
            self._checked.discard(path)
            now_checked = False
        else:
            self._checked.add(path)
            now_checked = True
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.CheckedRole])
        return now_checked

    def is_path_checked(self, path: str) -> bool:
        """Return whether *path* is currently marked."""
        return path in self._checked

    def select_all_rows(self) -> None:
        if not self._rows:
            return
        new_paths = {r.path for r in self._rows}
        if new_paths.issubset(self._checked):
            return
        self._checked |= new_paths
        self._emit_checked_range()

    def deselect_all_rows(self) -> None:
        if not self._rows:
            return
        current_paths = {r.path for r in self._rows}
        if not (current_paths & self._checked):
            return
        self._checked -= current_paths
        self._emit_checked_range()

    def invert_selection_rows(self) -> None:
        if not self._rows:
            return
        for r in self._rows:
            if r.path in self._checked:
                self._checked.discard(r.path)
            else:
                self._checked.add(r.path)
        self._emit_checked_range()

    def _emit_checked_range(self) -> None:
        if self._rows:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, 0)
            self.dataChanged.emit(top_left, bottom_right, [self.CheckedRole])

    @property
    def checked_count(self) -> int:
        """Total number of marked images (across all searches)."""
        return len(self._checked)

    def get_checked_paths(self) -> list[str]:
        """Return all marked paths for persistence."""
        return sorted(self._checked)

    def set_checked_paths(self, paths: list[str]) -> None:
        """Restore marks from persistence."""
        self._checked = set(paths)
        if self._rows:
            self._emit_checked_range()

    def get_checked_metadata(self) -> List[dict]:
        """Return metadata dicts for marked rows in the current search results."""
        import json as _json

        result = []
        for item in self._rows:
            if item.path in self._checked:
                try:
                    meta = _json.loads(item.metadata_json or "{}")
                except Exception:
                    meta = {}
                result.append({"path": item.path, "filename": item.filename, "metadata": meta})
        return result
