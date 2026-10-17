from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QObject, QPoint, QPointF, QMetaObject, Qt, QUrl, Signal
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from exif_turbo.data.image_index_repository import ImageIndexRepository
from exif_turbo.mcp.mcp_session_service import McpSessionService
from exif_turbo.models.search_result import SearchResult
from exif_turbo.tagging.derivative_export_service import (
    DerivativeExportItemResult,
    DerivativeExportResult,
    DerivativeExportStatus,
)
from exif_turbo.tagging.sidecar_repository import FilesystemSidecarRepository
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


@pytest.fixture
def tagging_controller(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AppController, SearchListModel, Path, Path]:
    db_path = tmp_path / "images.db"
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"image")
    repository = ImageIndexRepository(db_path, key="")
    repository.upsert_image(str(image_path), image_path.name, 1.0, 5, {}, "")
    repository.close()
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


def test_app_controller_set_member_tagging_keeps_search_selection(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, search_model, _, search_path = tagging_controller
    set_path = tmp_path / "set-member.jpg"
    set_path.write_bytes(b"image")
    assert controller._repo is not None
    controller._repo.upsert_image(
        str(set_path), set_path.name, 1.0, 5, {"IPTC:Keywords": ["Set embedded"]}, ""
    )
    set_id = controller.createImageSet("Tagging set")
    controller._repo.add_images_to_set(set_id, [str(set_path)])

    # Act
    controller.setActionImageSet(set_id)
    controller.selectImageSetMember(str(set_path))
    controller.addSelectedFreeTag("Set custom")

    # Assert
    assert controller.taggingFilename == set_path.name
    assert controller.hasTaggingSelection
    assert controller._repo.get_free_tags(str(set_path)) == ("Set custom",)
    assert controller._repo.get_free_tags(str(search_path)) == ()
    assert search_model.get_path(controller.currentResultRow) == str(search_path)
    assert controller.embeddedTagsModel.rowCount() == 1
    controller._update_exif_table('{"IPTC:Keywords": ["Unrelated Search tag"]}')
    embedded_model = controller.embeddedTagsModel
    assert embedded_model.data(embedded_model.index(0), embedded_model.LabelRole) == "Set embedded"
    controller.setSelectedEmbeddedTagExcluded("Set embedded", True)
    controller.setExcludeAllSelectedEmbeddedTags(True)
    loaded = FilesystemSidecarRepository().read(set_path)
    assert loaded is not None
    assert loaded.sidecar.excluded_embedded_tags == ("Set embedded",)
    assert loaded.sidecar.exclude_all_embedded_tags
    controller.removeSelectedFreeTag("Set custom")
    assert controller._repo.get_free_tags(str(set_path)) == ()
    assert not FilesystemSidecarRepository.sidecar_path(search_path).exists()
    controller.selectImageSetMember(str(search_path))
    assert controller.selectedSetMemberPath == str(set_path)
    controller.setActionImageSet(0)
    assert controller.taggingFilename == search_path.name
    assert controller.selectedSetMemberPath == ""


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_app_controller_mcp_batch_updates_selected_set_member_custom_tags(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    mode: str,
) -> None:
    # Arrange
    controller, search_model, _, search_path = tagging_controller
    set_path = tmp_path / "set-member.jpg"
    set_path.write_bytes(b"image")
    assert controller._repo is not None
    controller._repo.upsert_image(str(set_path), set_path.name, 1.0, 5, {}, "")
    image_id = controller._repo.get_images_by_paths([str(set_path)])[0][0]
    set_id = controller.createImageSet("MCP tagging set")
    controller._repo.add_images_to_set(set_id, [str(set_path)])
    controller.setActionImageSet(set_id)
    controller.selectImageSetMember(str(set_path))
    controller.addSelectedFreeTag("Original")
    session = McpSessionService(controller._mcp)

    # Act
    result = session.set_custom_tags_batch(
        [{"image_id": image_id, "path": str(set_path), "tags": ["MCP tag"], "mode": mode}]
    )

    # Assert
    expected_tags = ("Original", "MCP tag") if mode == "append" else ("MCP tag",)
    assert result["succeeded"] == 1, result
    assert controller._repo.get_free_tags(str(set_path)) == expected_tags
    model = controller.freeTagsModel
    assert tuple(
        model.data(model.index(row), model.LabelRole)
        for row in range(model.rowCount())
    ) == tuple(sorted(expected_tags))
    controller.selectImageSetMember("")
    controller.selectImageSetMember(str(set_path))
    assert tuple(
        model.data(model.index(row), model.LabelRole)
        for row in range(model.rowCount())
    ) == tuple(sorted(expected_tags))
    assert search_model.get_path(controller.currentResultRow) == str(search_path)


def test_app_controller_mcp_selected_image_targets_set_member_not_search_image(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, search_model, _, search_path = tagging_controller
    set_path = tmp_path / "selected-member.jpg"
    set_path.write_bytes(b"image")
    assert controller._repo is not None
    controller._repo.upsert_image(
        str(set_path), set_path.name, 1.0, 5, {"Make": "Set camera"}, ""
    )
    image_id = controller._repo.get_images_by_paths([str(set_path)])[0][0]
    set_id = controller.createImageSet("Selected MCP set")
    controller._repo.add_images_to_set(set_id, [str(set_path)])
    controller.setActionImageSet(set_id)
    controller.selectImageSetMember(str(set_path))
    controller.addSelectedFreeTag("Existing")
    session = McpSessionService(controller._mcp)

    # Act
    selected = session.get_selected_image(include_preview=False)
    result = session.add_custom_tags(["MCP tag"])

    # Assert
    assert selected.path == str(set_path)
    assert selected.image_id == image_id
    assert selected.metadata == {"Make": "Set camera"}
    assert selected.free_tags == ("Existing",)
    assert result["path"] == str(set_path)
    assert controller._repo.get_free_tags(str(set_path)) == ("Existing", "MCP tag")
    assert controller._repo.get_free_tags(str(search_path)) == ()
    assert not FilesystemSidecarRepository.sidecar_path(search_path).exists()
    assert search_model.get_path(controller.currentResultRow) == str(search_path)


def test_app_controller_mcp_unselected_set_does_not_fall_back_to_search_image(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, search_path = tagging_controller
    set_id = controller.createImageSet("No member selected")
    controller.setActionImageSet(set_id)
    session = McpSessionService(controller._mcp)

    # Act / Assert
    with pytest.raises(RuntimeError, match="No image is currently selected"):
        session.add_custom_tags(["Wrong target"])
    assert not FilesystemSidecarRepository.sidecar_path(search_path).exists()


def test_app_controller_mcp_set_selection_preview_ignores_search_preview(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, _, _, search_path = tagging_controller
    set_path = tmp_path / "blue.png"
    Image.new("RGB", (8, 8), "blue").save(set_path)
    Image.new("RGB", (8, 8), "red").save(search_path)
    assert controller._repo is not None
    controller._repo.upsert_image(str(set_path), set_path.name, 1.0, 5, {}, "")
    set_id = controller.createImageSet("Preview set")
    controller._repo.add_images_to_set(set_id, [str(set_path)])
    controller.setActionImageSet(set_id)
    controller.selectImageSetMember(str(set_path))
    controller._pending_preview_path = str(search_path)
    controller._selected_has_preview = True

    # Act
    selected = McpSessionService(controller._mcp).get_selected_image()

    # Assert
    assert selected.path == str(set_path)
    assert selected.has_preview is False
    assert selected.preview_jpeg_base64 is not None
    with Image.open(io.BytesIO(base64.b64decode(selected.preview_jpeg_base64))) as preview:
        red, green, blue = preview.convert("RGB").getpixel((0, 0))
        assert blue > 240
        assert red < 10
        assert green < 10


def test_app_controller_mcp_search_selection_still_targets_search_image(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, search_path = tagging_controller
    session = McpSessionService(controller._mcp)

    # Act
    selected = session.get_selected_image(include_preview=False)
    result = session.add_custom_tags(["Search tag"])

    # Assert
    assert selected.path == str(search_path)
    assert selected.image_id == 1
    assert result["path"] == str(search_path)
    assert controller._repo is not None
    assert controller._repo.get_free_tags(str(search_path)) == ("Search tag",)


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


def test_app_controller_embedded_exclusion_updates_preview_and_sidecar(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, _db_path, image_path = tagging_controller
    search_model.set_rows(
        [
            SearchResult(
                path=str(image_path),
                filename=image_path.name,
                metadata_json='{"IPTC:Keywords": ["Family", "Private"]}',
                size=5,
                mtime=1.0,
                image_id=1,
            )
        ]
    )
    controller._select_source_row(0)

    # Act
    controller.setSelectedEmbeddedTagExcluded("private", True)

    # Assert
    model = controller.embeddedTagsModel
    loaded = FilesystemSidecarRepository().read(image_path)
    assert model.data(model.index(1), model.ExcludedRole) is True
    assert controller.derivativeTagsModel.rowCount() == 1
    assert controller.derivativeTagsModel.data(
        controller.derivativeTagsModel.index(0),
        controller.derivativeTagsModel.LabelRole,
    ) == "Family"
    assert loaded is not None
    assert loaded.sidecar.excluded_embedded_tags == ("private",)


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


def test_app_controller_selected_filename_comes_from_selected_model_row(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange / Act
    controller, _model, _db_path, image_path = tagging_controller

    # Assert
    assert controller.selectedFilename == image_path.name


def test_tagging_drawer_leaving_search_or_browse_closes_drawer(
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
    tab_bar = root.findChild(QQuickItem, "mainTabBar")
    assert drawer is not None
    assert tab_bar is not None
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("visible")), timeout=3_000)

    # Act / Assert: leave Search.
    tab_bar.setProperty("currentIndex", 1)
    qtbot.waitUntil(lambda: not bool(drawer.property("visible")), timeout=3_000)

    # Act / Assert: leave Browse.
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("visible")), timeout=3_000)
    tab_bar.setProperty("currentIndex", 0)
    qtbot.waitUntil(lambda: not bool(drawer.property("visible")), timeout=3_000)

    engine.deleteLater()
    qtbot.wait(100)


def test_app_controller_custom_tags_add_remove_and_remain_suggestions(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller

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
    assert controller.freeTaggingAvailable is True
    assert added_label == "Family"
    assert controller.freeTagsModel.rowCount() == 0
    assert suggestion == "Family"
    assert Path(f"{image_path}.sidecar.json").exists()


def test_tagging_panel_opens_unfocused_with_existing_tag_suggestions(
    qtbot: QtBot,
    tmp_path: Path,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, _db_path, _image_path = tagging_controller
    controller.addSelectedFreeTag("Family")
    controller.removeSelectedFreeTag("family")
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
    context.setContextProperty("settingsModel", SettingsModel(tmp_path / "panel-settings.json"))
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
    tag_field = root.findChild(QQuickItem, "freeTagField")
    suggestions = root.findChild(QQuickItem, "freeTagSuggestions")
    assert drawer is not None
    assert tag_field is not None
    assert suggestions is not None

    # Act
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("visible")), timeout=3_000)
    qtbot.waitUntil(lambda: int(suggestions.property("count")) == 1, timeout=3_000)

    # Assert
    assert tag_field.property("activeFocus") is False
    assert int(suggestions.property("count")) == 1
    assert drawer.property("showFreeTagSuggestions") is False
    assert suggestions.property("visible") is False

    # Act: focusing the field reveals the already-loaded suggestions.
    if root.isActive():
        tag_field.forceActiveFocus()
        qtbot.waitUntil(lambda: bool(suggestions.property("visible")), timeout=1_000)
        assert int(suggestions.property("count")) == 1

    engine.deleteLater()
    qtbot.wait(100)


def test_tag_remove_button_removes_selected_free_tag(
    qtbot: QtBot,
    tmp_path: Path,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, _db_path, _image_path = tagging_controller
    controller.addSelectedFreeTag("Family")
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
    context.setContextProperty("settingsModel", SettingsModel(tmp_path / "settings.json"))
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
    current_tags = root.findChild(QQuickItem, "currentFreeTags")
    assert drawer is not None
    assert current_tags is not None
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("visible")), timeout=3_000)
    qtbot.waitUntil(lambda: int(current_tags.property("count")) == 1, timeout=3_000)

    def find_remove_button(item: QQuickItem) -> QQuickItem | None:
        if item.objectName() == "removeFreeTagButton":
            return item
        for child in item.childItems():
            found = find_remove_button(child)
            if found is not None:
                return found
        return None

    remove_button = find_remove_button(current_tags)
    assert remove_button is not None

    # Act
    assert remove_button.width() >= 36
    assert remove_button.height() >= 36
    center = remove_button.mapToScene(
        QPointF(float(remove_button.width()) / 2.0, float(remove_button.height()) / 2.0)
    )
    if (
        root.isActive()
        and 0 <= center.x() < root.width()
        and 0 <= center.y() < root.height()
    ):
        QTest.mouseClick(
            root,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(center.x()), round(center.y())),
        )
    else:
        remove_button.clicked.emit()
    qtbot.waitUntil(lambda: int(current_tags.property("count")) == 0, timeout=1_000)

    controller.addSelectedFreeTag("Family")
    qtbot.waitUntil(lambda: int(current_tags.property("count")) == 1, timeout=1_000)
    remove_button = find_remove_button(current_tags)
    assert remove_button is not None
    remove_mouse_area = next(
        child
        for child in remove_button.childItems()
        if child.objectName() == "removeTagMouseArea"
    )
    center = remove_button.mapToScene(
        QPointF(float(remove_button.width()) / 2.0, float(remove_button.height()) / 2.0)
    )
    right_edge = remove_button.mapToScene(
        QPointF(float(remove_button.width()) - 3.0, float(remove_button.height()) / 2.0)
    )
    if (
        root.isActive()
        and 0 <= right_edge.x() < root.width()
        and 0 <= right_edge.y() < root.height()
    ):
        QTest.mouseMove(root, QPoint(round(center.x()), round(center.y())))
        qtbot.wait(100)
        center_hovered = bool(remove_mouse_area.property("containsMouse"))
        QTest.mouseMove(root, QPoint(round(right_edge.x()), round(right_edge.y())))
        qtbot.wait(100)
        edge_hovered = bool(remove_mouse_area.property("containsMouse"))
        assert center_hovered is True
        assert edge_hovered is True
        QTest.mouseClick(
            root,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(right_edge.x()), round(right_edge.y())),
        )
    else:
        remove_button.clicked.emit()

    # Assert
    qtbot.waitUntil(lambda: int(current_tags.property("count")) == 0, timeout=1_000)

    engine.deleteLater()
    qtbot.wait(100)


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


class FakeCopyTagsWorker(QObject):
    progress = Signal(int, int, object)
    result_ready = Signal(object)
    canceled = Signal(object)
    failed = Signal(str)
    finished = Signal()
    instances: list[FakeCopyTagsWorker] = []

    def __init__(
        self,
        db_path: Path,
        key: str,
        source_image_path: str,
        mode: str,
        **options: object,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.key = key
        self.source_image_path = source_image_path
        self.mode = mode
        self.options = options
        self.started = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        pass

    def isRunning(self) -> bool:
        return False


@pytest.mark.parametrize("scope, mode", [
    ("set", "add"), ("set", "replace"),
    ("marked", "add"), ("marked", "replace"),
])
def test_app_controller_sets_copy_tags_keeps_outside_images_untouched(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    scope: str,
    mode: str,
) -> None:
    # Arrange
    controller, _, _, source_path = tagging_controller
    target_path = tmp_path / "target.jpg"
    outside_path = tmp_path / "outside.jpg"
    assert controller._repo is not None
    for path in (target_path, outside_path):
        path.write_bytes(b"image")
        controller._repo.upsert_image(str(path), path.name, 1.0, 5, {}, "")
        controller._repo.mark_image(str(path), True)
    set_id = controller.createImageSet("Copy tags set")
    controller._repo.add_images_to_set(set_id, [str(source_path), str(target_path)])
    controller.setActionImageSet(set_id)
    controller.selectImageSetMember(str(source_path))
    controller.addSelectedFreeTag("Shared tag")
    controller._query_text = "unrelated search"
    controller._is_ai_search_mode = True

    # Act
    controller.copySelectedTags(scope, mode)
    qtbot.waitUntil(lambda: not controller.isTaggingBulk, timeout=5000)

    # Assert
    assert controller._repo.get_free_tags(str(target_path)) == ("Shared tag",)
    assert controller._repo.get_free_tags(str(outside_path)) == ()
    assert not FilesystemSidecarRepository.sidecar_path(outside_path).exists()
    assert controller._repo.get_free_tags(str(source_path)) == ("Shared tag",)


@pytest.mark.parametrize("source_tab, mode", [
    ("sets", "add"), ("sets", "replace"),
    ("search", "add"), ("search", "replace"),
])
def test_app_controller_copy_tags_to_other_set_only_changes_destination_members(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    source_tab: str,
    mode: str,
) -> None:
    # Arrange
    controller, _, _, source_path = tagging_controller
    peer_path = tmp_path / "source-peer.jpg"
    target_path = tmp_path / "destination.jpg"
    outside_path = tmp_path / "outside.jpg"
    assert controller._repo is not None
    for path in (peer_path, target_path, outside_path):
        path.write_bytes(b"image")
        controller._repo.upsert_image(str(path), path.name, 1.0, 5, {}, "")
    source_set_id = controller.createImageSet("Source set")
    target_set_id = controller.createImageSet("Destination set")
    controller._repo.add_images_to_set(source_set_id, [str(source_path), str(peer_path)])
    controller._repo.add_images_to_set(target_set_id, [str(source_path), str(target_path)])
    if source_tab == "sets":
        controller.setActionImageSet(source_set_id)
        controller.selectImageSetMember(str(source_path))
    controller.addSelectedFreeTag("Shared tag")
    source_sidecar = FilesystemSidecarRepository.sidecar_path(source_path)
    source_revision = source_sidecar.stat().st_mtime_ns
    controller._query_text = "unrelated search"
    controller._is_ai_search_mode = True

    # Act
    controller.copySelectedTags(f"set:{target_set_id}", mode)
    qtbot.waitUntil(lambda: not controller.isTaggingBulk, timeout=5000)

    # Assert
    assert controller._repo.get_free_tags(str(target_path)) == ("Shared tag",)
    assert controller._repo.get_free_tags(str(peer_path)) == ()
    assert controller._repo.get_free_tags(str(outside_path)) == ()
    assert controller._repo.get_free_tags(str(source_path)) == ("Shared tag",)
    assert source_sidecar.stat().st_mtime_ns == source_revision


def test_app_controller_copy_tags_deleted_destination_does_not_start(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, _ = tagging_controller
    set_id = controller.createImageSet("Deleted destination")
    controller.addSelectedFreeTag("Shared tag")
    controller.deleteImageSet(set_id)

    # Act
    controller.copySelectedTags(f"set:{set_id}", "add")

    # Assert
    assert not controller.isTaggingBulk


def test_app_controller_copy_tags_folder_forwards_current_browse_scope(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    folder = tmp_path / "browse"
    controller._folder_filter = str(folder)
    controller._query_text = ""
    controller._ext_filter = ".jpg"
    controller._date_from = 100
    controller._date_to = 200
    FakeCopyTagsWorker.instances.clear()
    monkeypatch.setattr(app_controller_module, "CopyTagsWorker", FakeCopyTagsWorker)

    # Act
    controller.copySelectedTags("folder", "replace")

    # Assert
    worker = FakeCopyTagsWorker.instances[0]
    assert worker.source_image_path == str(image_path)
    assert worker.mode == "replace"
    assert worker.options == {
        "query": "",
        "ext_filter": ".jpg",
        "path_filter": [str(folder)],
        "restrict_to_enabled_folders": True,
        "date_from": 100,
        "date_to": 200,
        "image_set_id": None,
    }
    assert worker.started is True


def test_app_controller_copy_tags_results_uses_complete_ai_cache(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    second_path = tmp_path / "second.jpg"
    controller._is_ai_search_mode = True
    controller._last_ai_query = "forest"
    controller._ai_result_cache = [
        SearchResult(str(image_path), image_path.name, "{}", 5, 1.0, 1),
        SearchResult(str(second_path), second_path.name, "{}", 5, 1.0, 2),
    ]
    FakeCopyTagsWorker.instances.clear()
    monkeypatch.setattr(app_controller_module, "CopyTagsWorker", FakeCopyTagsWorker)

    # Act
    controller.copySelectedTags("results", "add")

    # Assert
    worker = FakeCopyTagsWorker.instances[0]
    assert worker.options == {
        "image_paths": [str(image_path), str(second_path)]
    }
    assert worker.started is True


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


@pytest.mark.parametrize("image_set_id", [None, 7])
def test_app_controller_current_results_forwards_complete_search_scope(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    image_set_id: int | None,
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
    controller._search_image_set_id = image_set_id
    assert controller._settings is not None
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
        "image_set_id": image_set_id,
    }


@pytest.mark.parametrize("marked_only", [False, True])
def test_app_controller_sets_derivatives_ignore_search_scope(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marked_only: bool,
) -> None:
    # Arrange
    controller, _, _, _ = tagging_controller
    controller.setActionImageSet(23)
    controller._query_text = "unrelated"
    controller._is_ai_search_mode = True
    FakeDerivativeWorker.instances.clear()
    monkeypatch.setattr(app_controller_module, "DerivativeExportWorker", FakeDerivativeWorker)

    # Act
    output_url = QUrl.fromLocalFile(str(tmp_path / "output")).toString()
    if marked_only:
        controller.generateDerivativesForMarked(output_url)
    else:
        controller.generateDerivativesForCurrentResults(output_url)

    # Assert
    expected_options = {"matching_results": True, "image_set_id": 23}
    if marked_only:
        expected_options["marked_only"] = True
    assert FakeDerivativeWorker.instances[0].options == expected_options


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
        "image_paths": [str(image_path), str(second_path)],
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
                "image has no tags",
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
    assert "1 image(s) had no tags" in controller.derivativeResultSummary
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
