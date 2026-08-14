#!/usr/bin/env python3
"""Run a hands-on acceptance check for the tagging workflow.

The check uses temporary copies of repository sample images and leaves source
fixtures and the user's EXIF Turbo profile untouched. It downloads the current
official TGM distribution and requires a working ExifTool installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

ARTIFACTS_DIR = REPO_ROOT / "build" / "tagging-acceptance"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-ai",
        action="store_true",
        help="download/cache OpenCLIP and verify real image-to-TGM proposals",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sample_images() -> list[Path]:
    sample_root = REPO_ROOT / "tests" / "sample-data" / "schweiz"
    images = [
        sample_root
        / "Wildlife"
        / "002 Wild Alpine Ibex Swiss Alps and Creux du Van Photo by Giles Laurent.jpg",
        sample_root
        / "Sky"
        / "035 Vertical panorama of the Milky Way during Perseids seen from Oeschinensee Photo by Giles Laurent.jpg",
    ]
    if not all(image.is_file() for image in images):
        raise RuntimeError("required tagging acceptance sample images are missing")
    return images


def _copy_samples(source_dir: Path) -> list[Path]:
    source_dir.mkdir(parents=True)
    copied: list[Path] = []
    for index, source in enumerate(_sample_images(), 1):
        destination = source_dir / f"sample-{index}{source.suffix.casefold()}"
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def _image_is_nonblank(path: Path) -> bool:
    from PySide6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull() or image.width() < 600 or image.height() < 600:
        return False
    colors: set[int] = set()
    step_x = max(1, image.width() // 24)
    step_y = max(1, image.height() // 18)
    for y in range(0, image.height(), step_y):
        for x in range(0, image.width(), step_x):
            colors.add(image.pixel(x, y))
            if len(colors) >= 12:
                return True
    return False


def _wait_for(app: Any, predicate: Any, description: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise RuntimeError(f"timed out waiting for {description}")


def _capture_nonblank(app: Any, root: Any, path: Path, description: str) -> None:
    def capture() -> bool:
        return root.grabWindow().save(str(path)) and _image_is_nonblank(path)

    _wait_for(app, capture, description)


def _capture_valid(app: Any, root: Any, path: Path, description: str) -> None:
    from PySide6.QtGui import QImage

    def capture() -> bool:
        if not root.grabWindow().save(str(path)):
            return False
        image = QImage(str(path))
        return not image.isNull() and image.width() >= 600 and image.height() >= 600

    _wait_for(app, capture, description)


def _read_derivative_keywords(path: Path) -> dict[str, Any]:
    import subprocess

    from exif_turbo.indexing.exif_metadata_extractor import find_exiftool

    result = subprocess.run(
        [
            find_exiftool(),
            "-json",
            "-G1",
            "-XMP-dc:Subject",
            "-IPTC:Keywords",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)[0]


def main() -> int:
    arguments = _arguments()
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    for old_screenshot in ARTIFACTS_DIR.glob("*.png"):
        old_screenshot.unlink()

    with tempfile.TemporaryDirectory(
        prefix="exif-turbo-tagging-acceptance-",
        ignore_cleanup_errors=True,
    ) as temp:
        workspace = Path(temp)
        profile_dir = workspace / "profile"
        os.environ["HOME"] = str(profile_dir)
        os.environ["USERPROFILE"] = str(profile_dir)

        from PySide6.QtCore import QMetaObject, QObject, Qt, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuickControls2 import QQuickStyle

        from exif_turbo.config import (
            ai_id_map_path,
            ai_index_path,
            tgm_concept_map_path,
            tgm_snapshot_path,
            tgm_term_index_path,
            tgm_vector_metadata_path,
        )
        from exif_turbo.data.ai_vector_repository import AiVectorRepository
        from exif_turbo.data.image_index_repository import ImageIndexRepository
        from exif_turbo.data.indexed_folder_repository import IndexedFolderRepository
        from exif_turbo.data.tgm_vector_repository import TgmVectorRepository
        from exif_turbo.indexing.ai_indexer_service import AiIndexerService
        from exif_turbo.indexing.exif_metadata_extractor import (
            ExifMetadataExtractor,
            get_exiftool_version,
        )
        from exif_turbo.models.search_result import SearchResult
        from exif_turbo.tagging.derivative_export_service import DerivativeExportService
        from exif_turbo.tagging.tgm_clip_proposal_provider import TgmClipProposalProvider
        from exif_turbo.tagging.tgm_proposal_service import TgmProposalService
        from exif_turbo.tagging.tgm_snapshot_repository import TgmSnapshotRepository
        from exif_turbo.tagging.tgm_update_service import TgmUpdateService
        from exif_turbo.tagging.tgm_vector_index_service import TgmVectorIndexService
        from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel
        from exif_turbo.ui.models.exif_list_model import ExifListModel
        from exif_turbo.ui.models.folder_list_model import FolderListModel
        from exif_turbo.ui.models.search_list_model import SearchListModel
        from exif_turbo.ui.models.settings_model import SettingsModel
        from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
        from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
        from exif_turbo.ui.view_models.app_controller import AppController

        exiftool_version = get_exiftool_version()
        if not exiftool_version:
            raise RuntimeError("ExifTool is required for acceptance")

        source_dir = workspace / "source"
        images = _copy_samples(source_dir)
        original_state = {
            path: (_sha256(path), path.stat().st_mtime_ns) for path in images
        }
        db_path = workspace / "acceptance.db"
        extractor = ExifMetadataExtractor()
        repository = ImageIndexRepository(db_path, key="")
        for image in images:
            stat = image.stat()
            metadata = extractor.extract(image)
            repository.upsert_image(
                str(image),
                image.name,
                stat.st_mtime,
                stat.st_size,
                metadata,
                " ".join(metadata.values()),
            )
        repository.commit()
        repository.close()

        folder_repository = IndexedFolderRepository(db_path, key="")
        folder = folder_repository.add(str(source_dir))
        folder_repository.update_status(folder.id, "indexed", image_count=len(images))
        folder_repository.close()

        started = time.perf_counter()
        snapshot_repository = TgmSnapshotRepository(tgm_snapshot_path(db_path))
        snapshot = TgmUpdateService(snapshot_repository).update()
        tgm_seconds = time.perf_counter() - started

        ai_report: dict[str, Any] | None = None
        if arguments.with_ai:
            image_vectors = AiVectorRepository(
                ai_index_path(db_path), ai_id_map_path(db_path)
            )
            image_vectors.load()
            encoder = AiIndexerService(
                image_vectors,
                cache_dir=ARTIFACTS_DIR / "open_clip",
            )
            image_started = time.perf_counter()
            indexed_count, image_errors = encoder.build_index(
                [str(image) for image in images]
            )
            image_vectors.save()
            if indexed_count != len(images) or image_errors:
                raise RuntimeError(
                    f"real CLIP image scan failed: {indexed_count=}, {image_errors=}"
                )

            term_vectors = TgmVectorRepository(
                tgm_term_index_path(db_path),
                tgm_concept_map_path(db_path),
                tgm_vector_metadata_path(db_path),
            )
            term_vectors.load()
            vector_service = TgmVectorIndexService(
                snapshot_repository,
                term_vectors,
                encoder,
            )
            term_started = time.perf_counter()
            build_result = vector_service.build(batch_size=64)
            if not build_result.completed or term_vectors.count != len(
                snapshot.selectable_concepts
            ):
                raise RuntimeError("real TGM vector build was incomplete")

            proposal_repository = ImageIndexRepository(db_path, key="")
            proposal_service = TgmProposalService(
                proposal_repository,
                TgmClipProposalProvider(
                    image_vectors,
                    term_vectors,
                    snapshot_repository,
                ),
            )
            proposal_result = proposal_service.generate(
                [str(image) for image in images],
                vector_service.expected_fingerprint(),
                top_k=5,
                threshold=0.0,
            )
            pending_count = int(
                proposal_repository.conn.execute(
                    "SELECT COUNT(*) FROM image_tag_proposals "
                    "WHERE status = 'pending'"
                ).fetchone()[0]
            )
            proposal_repository.close()
            if pending_count:
                raise RuntimeError("proposal generation persisted undecided suggestions")
            proposals = [
                proposal
                for result in proposal_result.results
                for proposal in result.proposals
            ]
            if proposal_result.cancelled or not proposals:
                raise RuntimeError("real CLIP proposal generation returned no candidates")
            ranked_labels = [
                tuple(proposal.label for proposal in result.proposals)
                for result in proposal_result.results
            ]
            if len(set(ranked_labels)) != len(ranked_labels):
                raise RuntimeError(
                    "real CLIP returned identical rankings for distinct sample images"
                )
            ai_report = {
                "images_encoded": indexed_count,
                "image_encode_seconds": round(term_started - image_started, 2),
                "tgm_vectors_built": term_vectors.count,
                "term_encode_seconds": round(time.perf_counter() - term_started, 2),
                "proposals_generated": len(proposals),
                "proposals_at_default_threshold": sum(
                    proposal.score >= 0.24 for proposal in proposals
                ),
                "top_proposals": [
                    {
                        "image": Path(proposal.image_path).name,
                        "label": proposal.label,
                        "score": round(proposal.score, 4),
                    }
                    for proposal in proposals
                ],
            }

        settings = SettingsModel(workspace / "settings.json")
        settings.setTaggingEnabled(True)
        search_model = SearchListModel(workspace / "thumbs")
        exif_model = ExifListModel()
        folder_model = FolderListModel()
        controller = AppController(
            db_path,
            search_model,
            exif_model,
            folder_model,
            settings,
            cache_dir=workspace / "thumbs",
        )
        proxy = CheckedFilterProxyModel()
        proxy.setSourceModel(search_model)
        controller.set_filter_proxy(proxy)

        QQuickStyle.setStyle("Material")
        app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        engine = QQmlApplicationEngine()
        engine.addImageProvider("preview", PreviewImageProvider())
        engine.addImageProvider("raw", RawImageProvider())
        context = engine.rootContext()
        context.setContextProperty("controller", controller)
        context.setContextProperty("searchModel", search_model)
        context.setContextProperty("filteredSearchModel", proxy)
        context.setContextProperty("exifModel", exif_model)
        context.setContextProperty("folderListModel", folder_model)
        context.setContextProperty("settingsModel", settings)
        context.setContextProperty("thirdPartyLicensesHtml", "")
        context.setContextProperty("userManualUrl", "")
        qml_path = SRC_ROOT / "exif_turbo" / "ui" / "qml" / "Main.qml"
        engine.load(QUrl.fromLocalFile(str(qml_path)))
        if not engine.rootObjects():
            raise RuntimeError("production QML failed to load")
        root = engine.rootObjects()[0]
        root.showNormal()
        root.setWidth(1440)
        root.setHeight(900)
        controller._do_unlock("")

        rows = [
            SearchResult(
                path=str(image),
                filename=image.name,
                metadata_json="{}",
                size=image.stat().st_size,
                mtime=image.stat().st_mtime,
                image_id=index,
            )
            for index, image in enumerate(images, 1)
        ]
        search_model.set_rows(rows)
        controller.selectResult(0)
        _wait_for(app, lambda: controller.taggingAvailable, "tagging availability")

        controller.searchTgm("forest")
        if controller.tgmSearchModel.rowCount() == 0:
            raise RuntimeError("official TGM search returned no result for 'forest'")
        concept_id = str(
            controller.tgmSearchModel.data(
                controller.tgmSearchModel.index(0),
                controller.tgmSearchModel.ConceptIdRole,
            )
        )
        concept_label = str(
            controller.tgmSearchModel.data(
                controller.tgmSearchModel.index(0),
                controller.tgmSearchModel.LabelRole,
            )
        )
        controller.addSelectedTgmConcept(concept_id)
        if controller.acceptedTagsModel.rowCount() != 1:
            raise RuntimeError("manual tag was not reflected in the accepted-tags model")

        controller.toggleChecked(0)
        controller.toggleChecked(1)
        controller.applyConceptToMarked(concept_id)
        _wait_for(app, lambda: not controller.isTaggingBulk, "bulk tag operation")
        if controller.markedTagImageCount != 2:
            raise RuntimeError("marked-image aggregate did not include both images")
        if controller.markedTagsModel.rowCount() != 1:
            raise RuntimeError("bulk tagging did not update the marked tag model")

        drawer = root.findChild(QObject, "taggingDrawer")
        if drawer is None:
            raise RuntimeError("tagging drawer was not created")
        QMetaObject.invokeMethod(drawer, "openAndFocus", Qt.ConnectionType.DirectConnection)
        _wait_for(app, lambda: bool(drawer.property("opened")), "tagging drawer open")

        desktop_path = ARTIFACTS_DIR / "tagging-desktop.png"
        _capture_nonblank(app, root, desktop_path, "desktop tagging screenshot")

        root.showNormal()
        root.setWidth(900)
        root.setHeight(600)
        _wait_for(
            app,
            lambda: int(root.width()) == 900 and int(root.height()) == 600,
            "minimum supported viewport",
        )
        constrained_path = ARTIFACTS_DIR / "tagging-constrained.png"
        _capture_nonblank(app, root, constrained_path, "constrained tagging screenshot")
        if int(drawer.property("width")) > int(root.width()):
            raise RuntimeError("tagging drawer exceeds the constrained viewport")

        root.showNormal()
        root.setWidth(1200)
        root.setHeight(800)
        QMetaObject.invokeMethod(
            root,
            "openTaggingSettingsForAutomation",
            Qt.ConnectionType.DirectConnection,
        )
        tagging_switch = root.findChild(QObject, "taggingEnabledSwitch")
        _wait_for(
            app,
            lambda: (
                not bool(drawer.property("opened"))
                and not bool(drawer.property("visible"))
                and tagging_switch is not None
                and bool(tagging_switch.property("visible"))
            ),
            "tagging settings section",
        )
        settings_path = ARTIFACTS_DIR / "tagging-settings.png"
        _capture_valid(app, root, settings_path, "tagging settings screenshot")

        repository = ImageIndexRepository(db_path, key="")
        tagged_results = repository.search_images(concept_label, limit=100, offset=0)
        if {str(result[1]) for result in tagged_results} != {str(path) for path in images}:
            raise RuntimeError("accepted TGM tag was not searchable for both images")

        output_dir = workspace / "derivatives"
        unused_root = workspace / "unused-indexed-root"
        unused_root.mkdir()
        exporter = DerivativeExportService(repository)
        plan = exporter.create_plan(
            {source_dir: "Block54K", unused_root: "Other"},
            output_dir,
        )
        export_result = exporter.export(plan)
        if export_result.copied_count != 2 or export_result.failed_count:
            raise RuntimeError(f"derivative export failed: {export_result}")
        derivative = output_dir / images[0].name
        if (output_dir / "Block54K").exists():
            raise RuntimeError("single-used-root export created a redundant root folder")
        keyword_data = _read_derivative_keywords(derivative)
        serialized_keywords = json.dumps(keyword_data, ensure_ascii=False)
        if concept_label not in serialized_keywords:
            raise RuntimeError("ExifTool readback did not contain the accepted tag")
        repository.close()

        sidecars = [Path(f"{image}.sidecar.json") for image in images]
        if not all(sidecar.exists() for sidecar in sidecars):
            raise RuntimeError("one or more authoritative sidecars are missing")
        for image, (expected_hash, expected_mtime) in original_state.items():
            if _sha256(image) != expected_hash or image.stat().st_mtime_ns != expected_mtime:
                raise RuntimeError(f"source image changed during tagging: {image.name}")

        report = {
            "status": "PASS",
            "exiftool_version": exiftool_version,
            "tgm_source_format": snapshot.source_format.value,
            "tgm_selectable_concepts": len(snapshot.selectable_concepts),
            "tgm_download_import_seconds": round(tgm_seconds, 2),
            "tag": {"concept_id": concept_id, "label": concept_label},
            "images_tagged_and_searchable": len(tagged_results),
            "sidecars_written": len(sidecars),
            "derivatives_verified": export_result.copied_count,
            "source_hashes_and_mtimes_unchanged": True,
            "screenshots": [
                desktop_path.name,
                constrained_path.name,
                settings_path.name,
            ],
        }
        if ai_report is not None:
            report["real_clip"] = ai_report
        (ARTIFACTS_DIR / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))

        controller.close()
        engine.deleteLater()
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())