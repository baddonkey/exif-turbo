from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ..models.image_sidecar import ImageSidecar
from ..models.image_tag import SidecarValidationError


class SidecarConflictError(RuntimeError):
    """Raised when a sidecar changed after it was loaded."""


@dataclass(frozen=True)
class SidecarStamp:
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class SidecarRevision:
    mtime_ns: int
    size: int
    sha256: str


@dataclass(frozen=True)
class LoadedSidecar:
    sidecar: ImageSidecar
    revision: SidecarRevision


class SidecarReadError(SidecarValidationError):
    def __init__(self, message: str, revision: SidecarRevision) -> None:
        super().__init__(message)
        self.revision = revision


class FilesystemSidecarRepository:
    @staticmethod
    def sidecar_path(image_path: Path) -> Path:
        return image_path.with_name(f"{image_path.name}.sidecar.json")

    def read(self, image_path: Path) -> LoadedSidecar | None:
        path = self.sidecar_path(image_path)
        if not path.exists():
            return None
        raw, revision = self._read_stable(path)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SidecarReadError(
                f"invalid sidecar JSON: {path}", revision
            ) from exc
        try:
            return LoadedSidecar(ImageSidecar.from_dict(data), revision)
        except SidecarValidationError as exc:
            raise SidecarReadError(str(exc), revision) from exc

    def stat(self, image_path: Path) -> SidecarStamp | None:
        try:
            stat = self.sidecar_path(image_path).stat()
        except FileNotFoundError:
            return None
        return SidecarStamp(mtime_ns=stat.st_mtime_ns, size=stat.st_size)

    def write(
        self,
        image_path: Path,
        sidecar: ImageSidecar,
        expected_revision: SidecarRevision | None,
    ) -> SidecarRevision:
        path = self.sidecar_path(image_path)
        if sidecar.source.filename != image_path.name:
            raise SidecarValidationError(
                "source.filename must match the original image filename"
            )
        self._assert_expected_revision(path, expected_revision)

        serialized = (
            json.dumps(
                sidecar.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        ImageSidecar.from_dict(json.loads(serialized.decode("utf-8")))

        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(file_descriptor, "wb") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            self._assert_expected_revision(path, expected_revision)
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

        _, revision = self._read_stable(path)
        return revision

    def _assert_expected_revision(
        self,
        path: Path,
        expected_revision: SidecarRevision | None,
    ) -> None:
        if not path.exists():
            if expected_revision is not None:
                raise SidecarConflictError(f"sidecar was removed: {path}")
            return
        if expected_revision is None:
            raise SidecarConflictError(f"sidecar was created externally: {path}")
        _, current_revision = self._read_stable(path)
        if current_revision != expected_revision:
            raise SidecarConflictError(f"sidecar changed externally: {path}")

    @staticmethod
    def _read_stable(path: Path) -> tuple[bytes, SidecarRevision]:
        for _attempt in range(2):
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if (
                before.st_mtime_ns == after.st_mtime_ns
                and before.st_size == after.st_size
            ):
                return raw, SidecarRevision(
                    mtime_ns=after.st_mtime_ns,
                    size=after.st_size,
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
        raise SidecarConflictError(f"sidecar changed while being read: {path}")