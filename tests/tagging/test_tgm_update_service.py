from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.models.tgm import TgmSourceFormat
from exif_turbo.tagging.tgm_snapshot_repository import TgmSnapshotRepository
from exif_turbo.tagging.tgm_update_service import (
    TgmDownloadError,
    TgmUpdateService,
    TgmValidationError,
)


XML_BYTES = b"""<THESAURUS>
    <CONCEPT><DESCRIPTOR>Sunlight</DESCRIPTOR><TNR>tgm000001</TNR><UF>Sun rays</UF><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
</THESAURUS>"""

TEXT_BYTES = b"""7/29/2026 11:55:28 AM

Sunlight
  TNR: tgm000001
  TTCSubj: MARC 150/650
"""


class FakeDownloader:
    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self._responses = responses
        self.requested_urls: list[str] = []

    def download(self, url: str, *, timeout_seconds: float, max_bytes: int) -> bytes:
        self.requested_urls.append(url)
        response = self._responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def _service(
    tmp_path: Path,
    downloader: FakeDownloader,
    *,
    sanity_minimum: int = 1,
    max_bytes: int = 25 * 1024 * 1024,
    image_repository: ImageIndexRepository | None = None,
) -> TgmUpdateService:
    return TgmUpdateService(
        repository=TgmSnapshotRepository(tmp_path / "tgm.json.gz"),
        downloader=downloader,
        xml_url="https://example.test/tgm.xml",
        text_url="https://example.test/tgm.txt",
        sanity_minimum=sanity_minimum,
        max_bytes=max_bytes,
        clock=lambda: datetime(2026, 8, 9, tzinfo=timezone.utc),
        image_repository=image_repository,
    )


def test_tgm_update_service_xml_failure_downloads_tagged_text_fallback(
    tmp_path: Path,
) -> None:
    # Arrange
    downloader = FakeDownloader(
        {
            "https://example.test/tgm.xml": TgmDownloadError("unavailable"),
            "https://example.test/tgm.txt": TEXT_BYTES,
        }
    )
    service = _service(tmp_path, downloader)

    # Act
    snapshot = service.update()

    # Assert
    assert snapshot.source_format is TgmSourceFormat.TAGGED_TEXT
    assert downloader.requested_urls == [
        "https://example.test/tgm.xml",
        "https://example.test/tgm.txt",
    ]


def test_tgm_update_service_install_from_path_activates_candidate(
    tmp_path: Path,
) -> None:
    # Arrange
    source_path = tmp_path / "tgm.xml"
    source_path.write_bytes(XML_BYTES)
    service = _service(tmp_path, FakeDownloader({}))

    # Act
    snapshot = service.install_from_path(
        source_path,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
    )

    # Assert
    assert snapshot.concepts[0].concept_id == "loc-tgm:tgm000001"
    assert service.repository.load() == snapshot


def test_tgm_update_service_rejected_truncation_preserves_active_snapshot(
    tmp_path: Path,
) -> None:
    # Arrange
    service = _service(tmp_path, FakeDownloader({}), sanity_minimum=1)
    original = service.install_from_bytes(
        XML_BYTES,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
    )
    service.sanity_minimum = 2

    # Act / Assert
    with pytest.raises(TgmValidationError, match="sanity minimum"):
        service.install_from_bytes(
            XML_BYTES,
            source_url="https://example.test/tgm.xml",
            source_format=TgmSourceFormat.XML,
        )
    assert service.repository.load() == original


def test_tgm_update_service_rejects_non_https_source(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, FakeDownloader({}))

    # Act / Assert
    with pytest.raises(TgmDownloadError, match="HTTPS"):
        service.install_from_bytes(
            XML_BYTES,
            source_url="http://example.test/tgm.xml",
            source_format=TgmSourceFormat.XML,
        )


def test_tgm_update_service_rejects_oversized_source(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, FakeDownloader({}), max_bytes=len(XML_BYTES) - 1)

    # Act / Assert
    with pytest.raises(TgmDownloadError, match="maximum size"):
        service.install_from_bytes(
            XML_BYTES,
            source_url="https://example.test/tgm.xml",
            source_format=TgmSourceFormat.XML,
        )


def test_tgm_update_service_activation_refreshes_fts_aliases_only(
    tmp_path: Path,
) -> None:
    # Arrange
    image_repository = ImageIndexRepository(tmp_path / "images.db")
    image_path = "/photos/photo.jpg"
    image_repository.upsert_image(
        image_path, "photo.jpg", 1.0, 100, {}, "Make Canon"
    )
    tag = ImageTag(
        concept_id="loc-tgm:tgm000001",
        label="Sunlight",
        category="subject",
        provenance=TagProvenance(
            method="manual",
            accepted_at="2026-08-01T00:00:00Z",
            vocabulary_checksum="sha256:old-snapshot",
        ),
    )
    image_repository.replace_accepted_tags_and_sidecar_state(
        image_path,
        ImageSidecar(
            source=SidecarSource(filename="photo.jpg"),
            updated_at="2026-08-01T00:00:00Z",
            tags=(tag,),
        ),
        sidecar_path=f"{image_path}.sidecar.json",
        sidecar_mtime_ns=1,
        sidecar_size=1,
        sidecar_checksum="sidecar",
        sync_status="synced",
        aliases={tag.concept_id: ("Old sunlight alias",)},
    )
    service = _service(
        tmp_path,
        FakeDownloader({}),
        image_repository=image_repository,
    )

    # Act
    service.install_from_bytes(
        XML_BYTES,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
    )

    # Assert
    assert image_repository.get_accepted_tags(image_path) == (tag,)
    assert image_repository.count_images('"Old sunlight alias"') == 0
    assert image_repository.count_images('"Sun rays"') == 1