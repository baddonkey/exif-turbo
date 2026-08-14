from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Protocol
from urllib import error, parse, request

from ..data.image_index_repository import ImageIndexRepository
from ..models.tgm import TgmSnapshot, TgmSourceFormat
from .tgm_importer import TgmImporter, TgmImportError
from .tgm_snapshot_repository import TgmSnapshotRepository


OFFICIAL_TGM_XML_URL = "https://guides.loc.gov/ld.php?content_id=76255776"
OFFICIAL_TGM_TEXT_URL = "https://guides.loc.gov/ld.php?content_id=76255770"
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_SANITY_MINIMUM = 7000


class TgmDownloadError(RuntimeError):
    """Raised when a managed source cannot be downloaded safely."""


class TgmValidationError(ValueError):
    """Raised when a parsed candidate fails managed-update sanity checks."""


class TgmUpdateError(RuntimeError):
    """Raised when both managed source formats fail."""


class TgmDownloader(Protocol):
    def download(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> bytes: ...


class UrlLibTgmDownloader:
    def download(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> bytes:
        self._require_https(url)
        source_request = request.Request(
            url,
            headers={"User-Agent": "EXIF-Turbo TGM updater"},
        )
        try:
            with request.urlopen(source_request, timeout=timeout_seconds) as response:
                final_url = response.geturl()
                self._require_https(final_url)
                declared_size = response.headers.get("Content-Length")
                if declared_size is not None and int(declared_size) > max_bytes:
                    raise TgmDownloadError("TGM source exceeds maximum size")
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(64 * 1024, max_bytes + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise TgmDownloadError("TGM source exceeds maximum size")
                    chunks.append(chunk)
                return b"".join(chunks)
        except TgmDownloadError:
            raise
        except (error.URLError, error.HTTPError, TimeoutError, OSError, ValueError) as exc:
            raise TgmDownloadError(f"failed to download TGM source: {url}") from exc

    @staticmethod
    def _require_https(url: str) -> None:
        if parse.urlparse(url).scheme.casefold() != "https":
            raise TgmDownloadError("TGM source URL must use HTTPS")


class TgmUpdateService:
    def __init__(
        self,
        repository: TgmSnapshotRepository,
        downloader: TgmDownloader | None = None,
        *,
        xml_url: str = OFFICIAL_TGM_XML_URL,
        text_url: str = OFFICIAL_TGM_TEXT_URL,
        sanity_minimum: int = DEFAULT_SANITY_MINIMUM,
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        work_dir: Path | None = None,
        clock: Callable[[], datetime] | None = None,
        image_repository: ImageIndexRepository | None = None,
    ) -> None:
        self.repository = repository
        self._downloader = downloader or UrlLibTgmDownloader()
        self._xml_url = xml_url
        self._text_url = text_url
        self.sanity_minimum = sanity_minimum
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds
        self._work_dir = work_dir
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._image_repository = image_repository
        self._importer = TgmImporter()

    def update(self) -> TgmSnapshot:
        failures: list[str] = []
        for url, source_format in (
            (self._xml_url, TgmSourceFormat.XML),
            (self._text_url, TgmSourceFormat.TAGGED_TEXT),
        ):
            try:
                raw = self._downloader.download(
                    url,
                    timeout_seconds=self._timeout_seconds,
                    max_bytes=self._max_bytes,
                )
                return self._install_download(raw, url, source_format)
            except (TgmDownloadError, TgmImportError, TgmValidationError, ValueError) as exc:
                failures.append(f"{source_format.value}: {exc}")
        raise TgmUpdateError("; ".join(failures))

    def _install_download(
        self,
        raw: bytes,
        source_url: str,
        source_format: TgmSourceFormat,
    ) -> TgmSnapshot:
        if self._work_dir is not None:
            self._work_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="tgm-download-",
            suffix=f".{source_format.value}",
            dir=self._work_dir,
            delete=False,
        ) as stream:
            stream.write(raw)
            temp_path = Path(stream.name)
        try:
            return self.install_from_path(
                temp_path,
                source_url=source_url,
                source_format=source_format,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def install_from_path(
        self,
        path: Path,
        *,
        source_url: str,
        source_format: TgmSourceFormat,
    ) -> TgmSnapshot:
        if path.stat().st_size > self._max_bytes:
            raise TgmDownloadError("TGM source exceeds maximum size")
        return self.install_from_bytes(
            path.read_bytes(),
            source_url=source_url,
            source_format=source_format,
        )

    def install_from_bytes(
        self,
        raw: bytes,
        *,
        source_url: str,
        source_format: TgmSourceFormat,
    ) -> TgmSnapshot:
        UrlLibTgmDownloader._require_https(source_url)
        if len(raw) > self._max_bytes:
            raise TgmDownloadError("TGM source exceeds maximum size")
        snapshot = self._importer.import_bytes(
            raw,
            source_url=source_url,
            source_format=source_format,
            imported_at=self._clock(),
        )
        selectable_count = len(snapshot.selectable_concepts)
        if selectable_count < self.sanity_minimum:
            raise TgmValidationError(
                f"TGM candidate has {selectable_count} selectable concepts; "
                f"sanity minimum is {self.sanity_minimum}"
            )
        self.repository.activate(snapshot)
        if self._image_repository is not None:
            self._image_repository.refresh_accepted_tag_aliases(
                {
                    concept.concept_id: concept.aliases
                    for concept in snapshot.selectable_concepts
                }
            )
        return snapshot