from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SidecarSyncState:
    sidecar_path: str
    mtime_ns: int
    size: int
    checksum: str
    schema_version: int
    sync_status: str
    error: str | None