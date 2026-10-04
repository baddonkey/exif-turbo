from __future__ import annotations

import json
from pathlib import Path

from exif_turbo.config import ai_index_path, database_data_dir
from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.image_sidecar import ImageSidecar, SidecarSource
from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.tagging.custom_tag_migration import CustomTagMigrationService
from exif_turbo.tagging.sidecar_repository import FilesystemSidecarRepository


def test_custom_tag_migration_removes_vocabulary_tags_and_preserves_custom_data(
    tmp_path: Path,
    repo: ImageIndexRepository,
) -> None:
    # Arrange
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"image")
    image_stat = image_path.stat()
    repo.upsert_image(
        str(image_path), image_path.name, image_stat.st_mtime, image_stat.st_size, {}, ""
    )
    sidecar_repository = FilesystemSidecarRepository()
    sidecar = ImageSidecar(
        source=SidecarSource(filename=image_path.name),
        updated_at="2026-08-09T12:30:00Z",
        tags=(
            ImageTag(
                concept_id="wikidata:Q42",
                label="Douglas Adams",
                vocabulary="wikidata",
                category="subject",
                provenance=TagProvenance(
                    method="manual",
                    accepted_at="2026-08-09T12:30:00Z",
                    vocabulary_checksum=f"sha256:{'a' * 64}",
                ),
            ),
            ImageTag(
                concept_id="loc-tgm:tgm000001",
                label="Mountains",
                vocabulary="loc-tgm",
                category="subject",
                provenance=TagProvenance(
                    method="manual",
                    accepted_at="2026-08-09T12:30:00Z",
                    vocabulary_checksum="sha256:legacy",
                ),
            ),
        ),
        free_tags=("Family",),
        excluded_embedded_tags=("Camera",),
        schema_version=2,
        extra={"future_top_level": {"keep": True}},
    )
    revision = sidecar_repository.write(image_path, sidecar, expected_revision=None)
    repo.replace_custom_tags_and_sidecar_state(
        str(image_path),
        sidecar,
        sidecar_path=str(sidecar_repository.sidecar_path(image_path)),
        sidecar_mtime_ns=revision.mtime_ns,
        sidecar_size=revision.size,
        sidecar_checksum=revision.sha256,
        sync_status="synced",
    )
    with repo.conn:
        repo.conn.executescript(
            """
            CREATE TABLE accepted_image_tags (image_id INTEGER, concept_id TEXT);
            CREATE TABLE accepted_image_tag_aliases (
                image_id INTEGER, concept_id TEXT, alias TEXT
            );
            CREATE TABLE tgm_concept_search_labels (
                concept_id TEXT, label TEXT
            );
            CREATE TABLE image_tag_proposals (image_id INTEGER, concept_id TEXT);
            INSERT INTO accepted_image_tags VALUES (1, 'wikidata:Q42');
            INSERT INTO image_tag_proposals VALUES (1, 'wikidata:Q42');
            """
        )
    legacy_tgm_dir = database_data_dir(repo.db_path) / "tgm"
    legacy_tgm_dir.mkdir(parents=True)
    (legacy_tgm_dir / "tgm-snapshot.json.gz").write_bytes(b"legacy snapshot")
    image_ai_index = ai_index_path(repo.db_path)
    image_ai_index.write_bytes(b"image vectors")

    # Act
    result = CustomTagMigrationService(repo, sidecar_repository).migrate()

    # Assert
    loaded = sidecar_repository.read(image_path)
    assert loaded is not None
    serialized = json.loads(
        sidecar_repository.sidecar_path(image_path).read_text(encoding="utf-8")
    )
    assert result.completed is True
    assert result.sidecars_updated == 1
    assert loaded.sidecar.tags == ()
    assert loaded.sidecar.free_tags == ("Family",)
    assert loaded.sidecar.excluded_embedded_tags == ("Camera",)
    assert serialized["future_top_level"] == {"keep": True}
    assert repo.get_free_tags(str(image_path)) == ("Family",)
    assert repo.count_images("Family") == 1
    assert repo.migration_completed(CustomTagMigrationService.MIGRATION_NAME)
    legacy_tables = {
        str(row[0])
        for row in repo.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert not legacy_tables.intersection(
        {
            "accepted_image_tags",
            "accepted_image_tag_aliases",
            "tgm_concept_search_labels",
            "image_tag_proposals",
        }
    )
    assert not legacy_tgm_dir.exists()
    assert image_ai_index.read_bytes() == b"image vectors"