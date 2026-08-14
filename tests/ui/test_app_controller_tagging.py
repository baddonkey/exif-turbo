from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, QMetaObject, Qt, QUrl, Signal
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.models.search_result import SearchResult
from exif_turbo.models.tag_proposal import TagProposal, TagProposalStatus
from exif_turbo.models.tag_proposal import (
    ProposalBatchResult,
    ProposalGenerationResult,
    ProposalGenerationStatus,
)
from exif_turbo.models.tgm import TgmCategory, TgmConcept, TgmSnapshot, TgmSourceFormat
from exif_turbo.tagging.tgm_snapshot_repository import TgmSnapshotRepository
from exif_turbo.tagging.derivative_export_service import (
    DerivativeExportItemResult,
    DerivativeExportResult,
    DerivativeExportStatus,
)
from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.view_models import app_controller as app_controller_module
from exif_turbo.ui.view_models.app_controller import AppController


_QML_DIR = Path(__file__).resolve().parents[2] / "src" / "exif_turbo" / "ui" / "qml"


def _snapshot() -> TgmSnapshot:
    return TgmSnapshot(
        concepts=(
            TgmConcept(
                concept_id="loc-tgm:tgm000001",
                tnr="tgm000001",
                label="Forests",
                categories=(TgmCategory.SUBJECT,),
                aliases=("Woods",),
            ),
        ),
        diagnostics=(),
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        distribution_date="2026-07-29",
        imported_at=datetime(2026, 8, 9, tzinfo=UTC),
        raw_sha256="snapshot",
        raw_size_bytes=100,
    )


@pytest.fixture
def tagging_controller(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AppController, SearchListModel, Path, Path]:
    db_path = tmp_path / "images.db"
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"image")
    repository = ImageIndexRepository(db_path)
    repository.upsert_image(str(image_path), image_path.name, 1.0, 5, {}, "")
    repository.close()
    snapshot_path = tmp_path / "tgm-snapshot.json.gz"
    TgmSnapshotRepository(snapshot_path).activate(_snapshot())
    monkeypatch.setattr(app_controller_module, "tgm_snapshot_path", lambda _db: snapshot_path)
    monkeypatch.setattr(
        app_controller_module,
        "tgm_vector_metadata_path",
        lambda _db: tmp_path / "missing-vector-metadata.json",
    )
    monkeypatch.setattr(app_controller_module, "get_exiftool_version", lambda: "test")
    search_model = SearchListModel(tmp_path / "thumbs")
    settings = SettingsModel(tmp_path / "settings.json")
    settings.setTaggingEnabled(True)
    controller = AppController(
        db_path,
        search_model,
        ExifListModel(),
        FolderListModel(),
        settings=settings,
        cache_dir=tmp_path / "thumbs",
    )
    monkeypatch.setattr(controller, "search", lambda _query: None)
    monkeypatch.setattr(controller, "_start_auto_thumbs", lambda: None)
    controller._do_unlock("")
    search_model.set_rows(
        [
            SearchResult(
                path=str(image_path),
                filename=image_path.name,
                metadata_json="{}",
                size=5,
                mtime=1.0,
                image_id=1,
            )
        ]
    )
    controller._current_result_row = 0
    yield controller, search_model, db_path, image_path
    controller.close()


def test_app_controller_unlock_initializes_tagging_services_and_status(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange / Act
    controller, _model, _db_path, _image_path = tagging_controller

    # Assert
    assert controller.taggingAvailable is True
    assert controller.tgmInstalled is True
    assert controller.tgmSourceDate == "2026-07-29"
    assert controller.tgmSubjectCount == 1


def test_app_controller_selection_exposes_deduplicated_embedded_tags_read_only(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, _db_path, image_path = tagging_controller
    search_model.set_rows(
        [
            SearchResult(
                path=str(image_path),
                filename=image_path.name,
                metadata_json=json.dumps(
                    {
                        "XMP-dc:Subject": "['Family', 'Summer']",
                        "IPTC:Keywords": ["family", "Vacation"],
                    }
                ),
                size=5,
                mtime=1.0,
                image_id=1,
            )
        ]
    )

    # Act
    controller._select_source_row(0)

    # Assert
    model = controller.embeddedTagsModel
    assert [model.data(model.index(row), model.LabelRole) for row in range(3)] == [
        "Family",
        "Summer",
        "Vacation",
    ]
    derivative_model = controller.derivativeTagsModel
    assert [
        derivative_model.data(derivative_model.index(row), derivative_model.LabelRole)
        for row in range(3)
    ] == ["Family", "Summer", "Vacation"]
    assert controller.freeTagsModel.rowCount() == 0


def test_app_controller_clear_selection_clears_embedded_tags(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, _db_path, image_path = tagging_controller
    search_model.set_rows(
        [
            SearchResult(
                path=str(image_path),
                filename=image_path.name,
                metadata_json='{"IPTC:Keywords": ["Family"]}',
                size=5,
                mtime=1.0,
                image_id=1,
            )
        ]
    )
    controller._select_source_row(0)

    # Act
    controller._clear_details()

    # Assert
    assert controller.embeddedTagsModel.rowCount() == 0


def test_app_controller_restart_reuses_installed_tgm_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    db_path = tmp_path / "library.db"
    ImageIndexRepository(db_path).close()
    snapshot_path = tmp_path / ".library.exif-turbo" / "tgm" / "tgm-snapshot.json.gz"
    TgmSnapshotRepository(snapshot_path).activate(_snapshot())
    monkeypatch.setattr(app_controller_module, "tgm_snapshot_path", lambda _db: snapshot_path)
    monkeypatch.setattr(
        app_controller_module,
        "tgm_vector_metadata_path",
        lambda _db: tmp_path / "missing-vector-metadata.json",
    )
    monkeypatch.setattr(app_controller_module, "get_exiftool_version", lambda: "test")

    def create_controller() -> AppController:
        controller = AppController(
            db_path,
            SearchListModel(tmp_path / "thumbs"),
            ExifListModel(),
            FolderListModel(),
            settings=SettingsModel(tmp_path / "settings.json"),
            cache_dir=tmp_path / "thumbs",
        )
        monkeypatch.setattr(controller, "search", lambda _query: None)
        monkeypatch.setattr(controller, "_start_auto_thumbs", lambda: None)
        controller._do_unlock("")
        return controller

    first_controller = create_controller()
    assert first_controller.tgmInstalled is True
    first_controller.close()

    # Act
    restarted_controller = create_controller()

    # Assert
    assert restarted_controller.tgmInstalled is True
    assert restarted_controller.tgmSourceDate == "2026-07-29"
    restarted_controller.close()


def test_app_controller_selected_filename_comes_from_selected_model_row(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange / Act
    controller, _model, _db_path, image_path = tagging_controller

    # Assert
    assert controller.selectedFilename == image_path.name


def test_app_controller_tgm_search_resolves_alias(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, _image_path = tagging_controller

    # Act
    controller.searchTgm("wood")

    # Assert
    model = controller.tgmSearchModel
    assert model.rowCount() == 1
    assert model.data(model.index(0), model.LabelRole) == "Forests"


def test_tagging_drawer_clicking_tgm_result_populates_search_field(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, _db_path, _image_path = tagging_controller
    settings_model = SettingsModel(search_model.cache_dir.parent / "qml-settings.json")
    filter_proxy = CheckedFilterProxyModel()
    filter_proxy.setSourceModel(search_model)
    controller.set_filter_proxy(filter_proxy)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    context = engine.rootContext()
    context.setContextProperty("controller", controller)
    context.setContextProperty("searchModel", search_model)
    context.setContextProperty("filteredSearchModel", filter_proxy)
    context.setContextProperty("exifModel", ExifListModel())
    context.setContextProperty("folderListModel", FolderListModel())
    context.setContextProperty("settingsModel", settings_model)
    context.setContextProperty("thirdPartyLicensesHtml", "")
    context.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_DIR / "Main.qml")))
    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5_000)
    root: QQuickWindow = engine.rootObjects()[0]  # type: ignore[assignment]
    root.setWidth(1200)
    root.setHeight(800)
    root.show()
    qtbot.waitExposed(root, timeout=3_000)

    drawer = root.findChild(QObject, "taggingDrawer")
    search_field = root.findChild(QQuickItem, "tgmSearchField")
    results = root.findChild(QQuickItem, "tgmSearchResults")
    assert drawer is not None
    assert search_field is not None
    assert results is not None
    QMetaObject.invokeMethod(drawer, "openAndFocus", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("opened")), timeout=3_000)
    controller.searchTgm("wood")
    qtbot.waitUntil(
        lambda: int(results.property("count")) == 1
        and bool(results.property("visible"))
        and float(results.property("width")) > 0
        and float(results.property("height")) > 0,
        timeout=3_000,
    )
    click_position = results.mapToScene(QPointF(results.width() / 2.0, 24.0))

    # Act
    QTest.mouseClick(
        root,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(click_position.x()), int(click_position.y())),
    )

    # Assert
    qtbot.waitUntil(
        lambda: search_field.property("text") == "Forests",
        timeout=3_000,
    )
    engine.deleteLater()
    qtbot.wait(100)


def test_tagging_drawer_double_clicking_tgm_result_adds_concept(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, _db_path, _image_path = tagging_controller
    settings_model = SettingsModel(search_model.cache_dir.parent / "qml-settings.json")
    filter_proxy = CheckedFilterProxyModel()
    filter_proxy.setSourceModel(search_model)
    controller.set_filter_proxy(filter_proxy)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    context = engine.rootContext()
    context.setContextProperty("controller", controller)
    context.setContextProperty("searchModel", search_model)
    context.setContextProperty("filteredSearchModel", filter_proxy)
    context.setContextProperty("exifModel", ExifListModel())
    context.setContextProperty("folderListModel", FolderListModel())
    context.setContextProperty("settingsModel", settings_model)
    context.setContextProperty("thirdPartyLicensesHtml", "")
    context.setContextProperty("userManualUrl", "")
    engine.load(QUrl.fromLocalFile(str(_QML_DIR / "Main.qml")))
    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5_000)
    root: QQuickWindow = engine.rootObjects()[0]  # type: ignore[assignment]
    root.setWidth(1200)
    root.setHeight(800)
    root.show()
    qtbot.waitExposed(root, timeout=3_000)

    drawer = root.findChild(QObject, "taggingDrawer")
    search_field = root.findChild(QQuickItem, "tgmSearchField")
    results = root.findChild(QQuickItem, "tgmSearchResults")
    assert drawer is not None
    assert search_field is not None
    assert results is not None
    QMetaObject.invokeMethod(drawer, "openAndFocus", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("opened")), timeout=3_000)
    search_field.setProperty("text", "wood")
    controller.searchTgm("wood")
    qtbot.waitUntil(
        lambda: int(results.property("count")) == 1
        and bool(results.property("visible"))
        and float(results.property("width")) > 0
        and float(results.property("height")) > 0,
        timeout=3_000,
    )
    click_position = results.mapToScene(QPointF(results.width() / 2.0, 24.0))

    # Act
    QTest.mouseDClick(
        root,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(click_position.x()), int(click_position.y())),
    )

    # Assert
    assert controller.acceptedTagsModel.rowCount() == 1
    assert search_field.property("text") == "wood"
    engine.deleteLater()
    qtbot.wait(100)


def test_app_controller_manual_add_and_remove_refreshes_accepted_model(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller

    # Act
    controller.addSelectedTgmConcept("Woods")
    added_count = controller.acceptedTagsModel.rowCount()
    derivative_label = controller.derivativeTagsModel.data(
        controller.derivativeTagsModel.index(0),
        controller.derivativeTagsModel.LabelRole,
    )
    controller.removeSelectedTgmConcept("loc-tgm:tgm000001")

    # Assert
    assert added_count == 1
    assert derivative_label == "Forests"
    assert controller.acceptedTagsModel.rowCount() == 0
    assert controller.derivativeTagsModel.rowCount() == 0
    assert Path(f"{image_path}.sidecar.json").exists()


def test_app_controller_free_tags_work_without_tgm_and_remain_suggestions(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    controller._tgm_metadata = {}

    # Act
    controller.addSelectedFreeTag(" Family ")
    added_label = controller.freeTagsModel.data(
        controller.freeTagsModel.index(0),
        controller.freeTagsModel.LabelRole,
    )
    controller.removeSelectedFreeTag("family")
    controller.searchFreeTags("fam")
    suggestion = controller.freeTagSuggestionsModel.data(
        controller.freeTagSuggestionsModel.index(0),
        controller.freeTagSuggestionsModel.LabelRole,
    )

    # Assert
    assert controller.taggingAvailable is False
    assert controller.freeTaggingAvailable is True
    assert added_label == "Family"
    assert controller.freeTagsModel.rowCount() == 0
    assert suggestion == "Family"
    assert Path(f"{image_path}.sidecar.json").exists()


def test_app_controller_proposal_accept_and_reject_refresh_state(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, db_path, image_path = tagging_controller
    repository = ImageIndexRepository(db_path)
    proposal = TagProposal(
        image_path=str(image_path),
        concept_id="loc-tgm:tgm000001",
        label="Forests",
        category="subject",
        provider_fingerprint="provider-a",
        score=0.8,
        rank=1,
    )
    controller._pending_proposals_model.set_rows([proposal])

    # Act
    controller.rejectSelectedProposal(proposal.concept_id, "provider-a")
    rejected = repository.get_proposals(
        str(image_path), status=TagProposalStatus.REJECTED
    )
    accepted_proposal = TagProposal(
        image_path=str(image_path),
        concept_id=proposal.concept_id,
        label=proposal.label,
        category=proposal.category,
        provider_fingerprint="provider-b",
        score=proposal.score,
        rank=proposal.rank,
    )
    controller._pending_proposals_model.set_rows([accepted_proposal])
    controller.acceptSelectedProposal(proposal.concept_id, "provider-b")
    repository.close()

    # Assert
    assert len(rejected) == 1
    assert controller.acceptedTagsModel.rowCount() == 1
    assert controller.pendingProposalsModel.rowCount() == 0


def test_app_controller_proposal_result_for_previous_selection_is_ignored(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, search_model, _db_path, first_path = tagging_controller
    second_path = tmp_path / "second.jpg"
    second_path.write_bytes(b"second")
    search_model.set_rows(
        [
            SearchResult(str(first_path), first_path.name, "{}", 5, 1.0, 1),
            SearchResult(str(second_path), second_path.name, "{}", 6, 1.0, 2),
        ]
    )
    proposal = TagProposal(
        image_path=str(first_path),
        concept_id="loc-tgm:tgm000001",
        label="Forests",
        category="subject",
        provider_fingerprint="provider-a",
        score=0.8,
        rank=1,
    )
    result = ProposalBatchResult(
        (
            ProposalGenerationResult(
                str(first_path),
                ProposalGenerationStatus.COMPLETED,
                proposals=(proposal,),
            ),
        ),
        False,
    )
    controller._current_result_row = 1

    # Act
    controller._on_proposal_result(result, None)

    # Assert
    assert controller.pendingProposalsModel.rowCount() == 0


def test_app_controller_refresh_selection_clears_ephemeral_proposals(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _search_model, _db_path, image_path = tagging_controller
    proposal = TagProposal(
        image_path=str(image_path),
        concept_id="loc-tgm:tgm000001",
        label="Forests",
        category="subject",
        provider_fingerprint="provider-a",
        score=0.8,
        rank=1,
    )
    controller._pending_proposals_model.set_rows([proposal])

    # Act
    controller.refreshSelectedTaggingState()

    # Assert
    assert controller.pendingProposalsModel.rowCount() == 0


class FakeDerivativeWorker(QObject):
    progress = Signal(int, int, object)
    result_ready = Signal(object)
    canceled = Signal(object)
    failed = Signal(str)
    finished = Signal()
    instances: list[FakeDerivativeWorker] = []

    def __init__(
        self,
        db_path: Path,
        key: str,
        indexed_roots: dict[Path, str],
        output_root: Path,
        **options: object,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.key = key
        self.indexed_roots = indexed_roots
        self.output_root = output_root
        self.options = options
        self.started = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        pass

    def isRunning(self) -> bool:
        return False


def test_app_controller_derivative_slot_converts_url_and_all_indexed_roots(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    controller, _model, _db_path, _image_path = tagging_controller
    source_root = tmp_path / "source"
    source_root.mkdir()
    assert controller._folder_repo is not None
    controller._folder_repo.add(str(source_root))
    disabled_root = tmp_path / "disabled"
    disabled_root.mkdir()
    disabled = controller._folder_repo.add(str(disabled_root))
    controller._folder_repo.set_enabled(disabled.id, False)
    FakeDerivativeWorker.instances.clear()
    monkeypatch.setattr(app_controller_module, "DerivativeExportWorker", FakeDerivativeWorker)
    output_root = tmp_path / "output"

    # Act
    controller.generateDerivativesForMarked(QUrl.fromLocalFile(str(output_root)).toString())

    # Assert
    worker = FakeDerivativeWorker.instances[0]
    assert worker.output_root == output_root
    assert worker.indexed_roots == {
        disabled_root: "disabled",
        source_root: "source",
    }
    assert worker.started is True


def test_app_controller_current_results_forwards_complete_search_scope(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    controller, _model, _db_path, _image_path = tagging_controller
    source_root = tmp_path / "source"
    source_root.mkdir()
    assert controller._folder_repo is not None
    controller._folder_repo.add(str(source_root))
    controller._query_text = "family"
    controller._ext_filter = ".jpg"
    controller._folder_filter = str(source_root)
    controller._checked_only_filter_active = True
    controller._date_from = 100
    controller._date_to = 200
    FakeDerivativeWorker.instances.clear()
    monkeypatch.setattr(app_controller_module, "DerivativeExportWorker", FakeDerivativeWorker)

    # Act
    controller.generateDerivativesForCurrentResults(
        QUrl.fromLocalFile(str(tmp_path / "output")).toString()
    )

    # Assert
    assert FakeDerivativeWorker.instances[0].options == {
        "matching_results": True,
        "query": "family",
        "ext_filter": ".jpg",
        "path_filter": [str(source_root)],
        "restrict_to_enabled_folders": True,
        "marked_only": True,
        "date_from": 100,
        "date_to": 200,
    }


def test_app_controller_current_ai_results_passes_complete_cached_paths(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    second_path = tmp_path / "second.jpg"
    controller._is_ai_search_mode = True
    controller._last_ai_query = "family"
    controller._ai_result_cache = [
        SearchResult(
            path=str(image_path),
            filename=image_path.name,
            metadata_json="{}",
            size=1,
            mtime=1.0,
            image_id=1,
        ),
        SearchResult(
            path=str(second_path),
            filename=second_path.name,
            metadata_json="{}",
            size=1,
            mtime=1.0,
            image_id=2,
        ),
    ]
    FakeDerivativeWorker.instances.clear()
    monkeypatch.setattr(app_controller_module, "DerivativeExportWorker", FakeDerivativeWorker)

    # Act
    controller.generateDerivativesForCurrentResults(
        QUrl.fromLocalFile(str(tmp_path / "output")).toString()
    )

    # Assert
    assert FakeDerivativeWorker.instances[0].options == {
        "image_paths": [str(image_path), str(second_path)]
    }


def test_app_controller_derivative_result_explains_destinations_and_skip_reasons(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    destination = tmp_path / "output" / image_path.name
    result = DerivativeExportResult(
        (
            DerivativeExportItemResult(
                image_path,
                destination,
                DerivativeExportStatus.COPIED,
            ),
            DerivativeExportItemResult(
                tmp_path / "untagged.jpg",
                tmp_path / "output" / "untagged.jpg",
                DerivativeExportStatus.SKIPPED_UNTAGGED,
                "image has no accepted tags",
            ),
            DerivativeExportItemResult(
                tmp_path / "existing.jpg",
                tmp_path / "output" / "existing.jpg",
                DerivativeExportStatus.SKIPPED_EXISTING,
                "destination already exists",
            ),
        )
    )

    # Act
    controller._on_derivative_result(result)

    # Assert
    assert str(destination) in controller.derivativeResultSummary
    assert "1 image(s) had no accepted tags" in controller.derivativeResultSummary
    assert "1 destination file(s) already existed" in controller.derivativeResultSummary


def test_app_controller_derivative_result_for_multiple_files_names_output_folder(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    output_dir = tmp_path / "output"
    result = DerivativeExportResult(
        (
            DerivativeExportItemResult(
                image_path,
                output_dir / image_path.name,
                DerivativeExportStatus.COPIED,
            ),
            DerivativeExportItemResult(
                tmp_path / "second.jpg",
                output_dir / "second.jpg",
                DerivativeExportStatus.COPIED,
            ),
        )
    )

    # Act
    controller._on_derivative_result(result)

    # Assert
    assert controller.derivativeResultSummary == (
        f"Created 2 derivatives in {output_dir}."
    )


def test_app_controller_derivative_result_reports_canceled_images(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    result = DerivativeExportResult(
        (
            DerivativeExportItemResult(
                image_path,
                tmp_path / "output" / image_path.name,
                DerivativeExportStatus.CANCELED,
                "export canceled",
            ),
        )
    )

    # Act
    controller._on_derivative_result(result)

    # Assert
    assert controller.derivativeResultSummary == (
        "No derivatives were created. 1 derivative(s) canceled."
    )


def test_app_controller_derivative_result_reports_first_failure_detail(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, _model, _db_path, _image_path = tagging_controller
    source = tmp_path / "broken.png"
    result = DerivativeExportResult(
        (
            DerivativeExportItemResult(
                source,
                tmp_path / "output" / source.name,
                DerivativeExportStatus.FAILED,
                "ExifTool metadata write failed: unsupported metadata",
            ),
        )
    )

    # Act
    controller._on_derivative_result(result)

    # Assert
    assert "First failure (broken.png): ExifTool metadata write failed" in (
        controller.derivativeResultSummary
    )


def test_app_controller_bulk_add_result_explains_unchanged_images(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, _image_path = tagging_controller
    controller._bulk_tag_action = "add"
    result = SimpleNamespace(
        succeeded_count=1,
        skipped_count=2,
        conflicted_count=1,
        failed_count=1,
        cancelled=False,
    )

    # Act
    controller._on_bulk_tag_result(result)

    # Assert
    assert controller.taggingBulkSummary == (
        "Added to 1 image(s). Already tagged: 2. Problems: 2."
    )


def test_app_controller_bulk_remove_result_explains_unchanged_images(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, _image_path = tagging_controller
    controller._bulk_tag_action = "remove"
    result = SimpleNamespace(
        succeeded_count=2,
        skipped_count=1,
        conflicted_count=0,
        failed_count=0,
        cancelled=False,
    )

    # Act
    controller._on_bulk_tag_result(result)

    # Assert
    assert controller.taggingBulkSummary == (
        "Removed from 2 image(s). Already absent: 1. Problems: 0."
    )