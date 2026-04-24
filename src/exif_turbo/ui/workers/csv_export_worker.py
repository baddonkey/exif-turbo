from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...data.image_index_repository import ImageIndexRepository


class CsvExportWorker(QThread):
    finished = Signal(str)  # file path
    failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        file_path: Path,
        query: str,
        key: str = "",
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._file_path = file_path
        self._query = query
        self._key = key

    def run(self) -> None:
        try:
            repo = ImageIndexRepository(self._db_path, key=self._key)
            total = repo.count_images(self._query)
            batch_size = 500
            offset = 0
            records: list[dict] = []
            all_keys: set[str] = set()
            while offset < total:
                rows = repo.search_images(self._query, batch_size, offset)
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
            repo.close()
            headers = ["path", "filename"] + sorted(all_keys)
            with open(self._file_path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
                writer.writeheader()
                for record in records:
                    writer.writerow(record)
            self.finished.emit(str(self._file_path))
        except Exception as exc:
            self.failed.emit(str(exc))

    @staticmethod
    def _flatten(d: dict, prefix: str = "") -> dict:
        out: dict = {}
        for k, v in d.items():
            key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            if isinstance(v, dict):
                out.update(CsvExportWorker._flatten(v, key))
            else:
                out[key] = v
        return out
