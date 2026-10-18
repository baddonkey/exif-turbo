from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QObject, QPoint, QPointF, QMetaObject, Qt, QUrl, Signal
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
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
from exif_turbo.tagging.tagging_service import TaggingService
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


def test_sets_and_tagging_views_null_controller_emit_no_type_errors(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, image_path = tagging_controller
    set_id = controller.createImageSet("Teardown set")
    assert controller._repo is not None
    controller._repo.add_images_to_set(set_id, [str(image_path)])
    controller.addSelectedFreeTag("Example")
    engine = QQmlApplicationEngine()
    warnings: list[str] = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    window = QQuickWindow()
    window.setWidth(1200)
    window.setHeight(800)
    window.show()
    components: list[QQmlComponent] = []
    views: list[QObject] = []
    for filename in ("SetsPage.qml", "TaggingDrawer.qml"):
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(_QML_DIR / filename)))
        components.append(component)
        properties: dict[str, object] = {"appController": controller}
        if filename == "TaggingDrawer.qml":
            properties["appSettings"] = controller._settings
        view = component.createWithInitialProperties(properties)
        assert view is not None, [error.toString() for error in component.errors()]
        views.append(view)
        if isinstance(view, QQuickItem):
            view.setParentItem(window.contentItem())
            view.setWidth(1200)
            view.setHeight(800)
        else:
            view.setProperty("parent", window.contentItem())
    sets_page, drawer = views
    QMetaObject.invokeMethod(sets_page, "reloadSets", Qt.ConnectionType.DirectConnection)
    sets_page.setProperty("selectedSetId", set_id)
    member_list = sets_page.findChild(QQuickItem, "imageSetMemberList")
    assert member_list is not None
    qtbot.waitUntil(
        lambda: int(member_list.property("count")) == 1
            and member_list.property("currentItem") is not None,
        timeout=3000,
    )
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    warnings.clear()

    # Act
    sets_page.setProperty("appController", None)
    drawer.setProperty("appController", None)
    qtbot.waitUntil(lambda: not bool(sets_page.property("canEditSets")), timeout=3000)
    for view in views:
        view.deleteLater()
    window.close()
    window.deleteLater()
    qtbot.wait(100)

    # Assert
    assert [warning for warning in warnings if "TypeError" in warning] == []
    engine.deleteLater()


@pytest.mark.parametrize(("width", "height"), [(1200, 800), (720, 420)])
@pytest.mark.parametrize("copy_mode", [False, True])
def test_tagging_drawer_two_columns_group_controls_and_scroll_independently(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    width: int,
    height: int,
    copy_mode: bool,
) -> None:
    # Arrange
    controller, _, _, _ = tagging_controller
    controller.addSelectedFreeTag("Example")
    controller._update_exif_table(json.dumps({
        "IFD0:ImageDescription": "\n".join(f"Embedded line {index}" for index in range(80)),
    }))
    engine = QQmlApplicationEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(_QML_DIR / "TaggingDrawer.qml")))
    drawer = component.createWithInitialProperties({
        "appController": controller, "appSettings": controller._settings, "copyMode": copy_mode,
    })
    assert drawer is not None, [error.toString() for error in component.errors()]
    window = QQuickWindow()
    window.setWidth(width)
    window.setHeight(height)
    drawer.setProperty("parent", window.contentItem())
    window.show()
    qtbot.waitExposed(window)

    # Act
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("opened")), timeout=3000)

    # Assert
    left = drawer.findChild(QQuickItem, "customTaggingColumn")
    right = drawer.findChild(QQuickItem, "copyTaggingColumn" if copy_mode else "existingTaggingColumn")
    assert left is not None and right is not None
    copy_scroll = drawer.findChild(QQuickItem, "copyTaggingScrollView")
    embedded_scroll = drawer.findChild(QQuickItem, "existingTaggingScrollView")
    assert copy_scroll is not None and embedded_scroll is not None
    assert copy_scroll.isVisible() is copy_mode
    assert embedded_scroll.isVisible() is not copy_mode
    left.ensurePolished()
    right.ensurePolished()
    assert left.width() > 300
    assert left.width() == pytest.approx(right.width(), abs=2)
    assert left.mapToScene(QPointF(left.width(), 0)).x() < right.mapToScene(QPointF()).x()
    for column, names in (
        (left, ("customTagsGroup", "descriptionEditor") if copy_mode else (
            "existingImageTagsGroup", "customTagsGroup",
        )),
        (right, ("copyTagsGroup", "copyDescriptionGroup") if copy_mode else (
            "existingEmbeddedDescriptionGroup", "descriptionEditor",
        )),
    ):
        previous_bottom = 0.0
        for name in names:
            group = drawer.findChild(QQuickItem, name)
            assert group is not None and group.parentItem() == column
            assert group.isVisible() and group.height() > 0
            assert group.y() >= previous_bottom
            previous_bottom = group.y() + group.height()
            assert group.x() + group.width() <= column.width() + 1

    columns = drawer.findChild(QQuickItem, "taggingColumns")
    footer = drawer.findChild(QQuickItem, "finalDerivativesFooter")
    tags_preview = drawer.findChild(QQuickItem, "derivativeTagsFooter")
    description_preview = drawer.findChild(QQuickItem, "derivativeDescriptionFooter")
    assert columns is not None and footer is not None
    assert tags_preview is not None and description_preview is not None
    footer_parent = footer.parentItem()
    assert footer_parent is not None and footer_parent == columns.parentItem()
    assert footer.y() >= columns.y() + columns.height()
    assert footer.y() + footer.height() == pytest.approx(footer_parent.height(), abs=1)
    assert footer.width() == pytest.approx(columns.width(), abs=1)
    assert tags_preview.parentItem() == footer and description_preview.parentItem() == footer
    assert tags_preview.width() == pytest.approx(description_preview.width(), abs=2)
    assert tags_preview.x() + tags_preview.width() < description_preview.x()
    assert tags_preview.height() > 100 and description_preview.height() > 100

    if height == 420:
        flickables: list[QQuickItem] = []
        for name in (
            "taggingScrollView", "copyTaggingScrollView" if copy_mode else "existingTaggingScrollView",
        ):
            scroll = drawer.findChild(QQuickItem, name)
            assert scroll is not None
            flickable = scroll.property("contentItem")
            assert isinstance(flickable, QQuickItem)
            if not copy_mode or name == "copyTaggingScrollView":
                assert float(flickable.property("contentHeight")) > flickable.height()
            flickables.append(flickable)
        left_flickable, right_flickable = flickables
        if not copy_mode:
            left_flickable.setProperty("contentY", 40)
        assert float(right_flickable.property("contentY")) == 0
        right_flickable.setProperty("contentY", 60)
        assert float(left_flickable.property("contentY")) == (0 if copy_mode else 40)
        assert footer.y() >= columns.y() + columns.height()

    drawer.deleteLater()
    window.close()
    window.deleteLater()
    qtbot.wait(100)
    engine.deleteLater()


def test_copy_panel_source_previews_are_read_only_and_use_saved_text(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, path = tagging_controller
    controller.addSelectedFreeTag("Custom tag")
    controller._update_exif_table(json.dumps({
        "XMP-dc:Subject": ["Embedded tag"], "IFD0:ImageDescription": "Embedded caption",
    }))
    controller.updateSelectedDescriptionDraft("Saved caption")
    assert controller.saveSelectedDescription("replace")
    controller.updateSelectedDescriptionDraft("Unsaved draft")
    before = FilesystemSidecarRepository().read(path)
    engine = QQmlApplicationEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(_QML_DIR / "TaggingDrawer.qml")))
    drawer = component.createWithInitialProperties({
        "appController": controller, "appSettings": controller._settings, "copyMode": True,
    })
    assert drawer is not None, [error.toString() for error in component.errors()]
    window = QQuickWindow()
    window.setWidth(1200)
    window.setHeight(800)
    drawer.setProperty("parent", window.contentItem())
    window.show()
    qtbot.waitExposed(window)
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("opened")), timeout=3000)
    editor = drawer.findChild(QQuickItem, "descriptionDraftEditor")
    preview = drawer.findChild(QQuickItem, "finalDerivativeDescription")
    tags = drawer.findChild(QQuickItem, "currentFreeTags")
    final_tags = drawer.findChild(QQuickItem, "finalDerivativeTags")
    assert editor is not None and preview is not None
    assert tags is not None and final_tags is not None
    tags.ensurePolished()
    final_tags.ensurePolished()

    # Act
    editor.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(window, Qt.Key.Key_Backspace)
    QTest.keyClick(window, Qt.Key.Key_Return)

    # Assert
    assert editor.property("readOnly") and preview.property("readOnly")
    assert editor.property("text") == "Saved caption"
    assert preview.property("text") == "Embedded caption\n\nSaved caption"
    assert int(tags.property("count")) == 1
    assert int(final_tags.property("count")) == 2
    assert controller.descriptionDraft == "Unsaved draft"
    assert FilesystemSidecarRepository().read(path) == before
    for name in ("freeTagField", "saveDescriptionButton", "discardDescriptionDraftButton"):
        control = drawer.findChild(QQuickItem, name)
        assert control is not None and not control.isVisible() and not control.isEnabled()
    qtbot.waitUntil(lambda: tags.property("currentItem") is not None, timeout=3000)
    tag_item = tags.property("currentItem")
    assert isinstance(tag_item, QQuickItem)
    remove_button = tag_item.findChild(QQuickItem, "removeFreeTagButton")
    assert remove_button is not None and not remove_button.isVisible() and not remove_button.isEnabled()
    for name in ("copyTagsButton", "copyDescriptionButton"):
        control = drawer.findChild(QQuickItem, name)
        assert control is not None and control.isVisible() and control.isEnabled()
    drawer.deleteLater()
    window.close()
    window.deleteLater()
    qtbot.wait(100)
    engine.deleteLater()


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


def test_app_controller_ifd0_description_visible_without_sidecar(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, model, _, image_path = tagging_controller
    description = 'PRC92-15\r"Desktop Universe"\rGuide Star Catalogue Compression\rrelease data 5/92\rInstrument = PDS Scanner\rInvestigator = Marc Postman\r'
    metadata = {"IFD0:ImageDescription": description}
    assert controller._repo is not None
    controller._repo.upsert_image(str(image_path), image_path.name, 1, 5, metadata, description)
    model.set_rows([SearchResult(str(image_path), image_path.name, json.dumps(metadata), 5, 1, 1)])

    # Act
    controller._select_source_row(0)

    # Assert
    assert controller.embeddedImageDescription == description.replace("\r", "\n").strip()
    assert controller.selectedImageDescription == ""
    assert not FilesystemSidecarRepository.sidecar_path(image_path).exists()


def test_app_controller_embedded_description_follows_set_selection_not_search(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, _, _, _ = tagging_controller
    set_path = tmp_path / "member.jpg"
    set_path.write_bytes(b"image")
    assert controller._repo is not None
    controller._repo.upsert_image(
        str(set_path), set_path.name, 1, 5, {"IFD0:ImageDescription": "Set caption"}, ""
    )
    set_id = controller.createImageSet("Description set")
    controller._repo.add_images_to_set(set_id, [str(set_path)])

    # Act / Assert
    controller.setActionImageSet(set_id)
    assert controller.embeddedImageDescription == ""
    controller.selectImageSetMember(str(set_path))
    controller._update_exif_table('{"IFD0:ImageDescription": "Unrelated Search caption"}')
    assert controller.embeddedImageDescription == "Set caption"
    controller.selectImageSetMember("")
    assert controller.embeddedImageDescription == ""


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


def test_app_controller_description_draft_requires_explicit_append_or_replace(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    controller.updateSelectedDescriptionDraft("First paragraph")

    # Act
    appended = controller.saveSelectedDescription("append")
    controller.updateSelectedDescriptionDraft("Replacement")
    replaced = controller.saveSelectedDescription("replace")
    saved = FilesystemSidecarRepository().read(image_path)

    # Assert
    assert appended is True
    assert replaced is True
    assert controller.selectedImageDescription == "Replacement"
    assert saved is not None
    assert saved.sidecar.description == "Replacement"
    assert controller.descriptionDraftActive is False


def test_app_controller_description_draft_remains_bound_to_original_image(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
) -> None:
    # Arrange
    controller, search_model, _db_path, original_path = tagging_controller
    other_path = tmp_path / "other.jpg"
    other_path.write_bytes(b"image")
    assert controller._repo is not None
    controller._repo.upsert_image(str(other_path), other_path.name, 1.0, 5, {}, "")
    search_model.set_rows(
        [
            SearchResult(str(original_path), original_path.name, "{}", 5, 1.0, 1),
            SearchResult(str(other_path), other_path.name, "{}", 5, 1.0, 2),
        ]
    )
    controller._select_source_row(0)
    controller.updateSelectedDescriptionDraft("Draft for first image")

    # Act
    controller._select_source_row(1)
    edited_other = controller.updateSelectedDescriptionDraft("Wrong image")
    saved_other = controller.saveSelectedDescription("replace")
    controller._select_source_row(0)

    # Assert
    assert edited_other is False
    assert saved_other is False
    assert controller.descriptionDraftMatchesSelection is True
    assert controller.descriptionDraft == "Draft for first image"
    assert FilesystemSidecarRepository().read(other_path) is None


def test_app_controller_mcp_description_update_preserves_draft_and_flags_conflict(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller
    controller.updateSelectedDescriptionDraft("Local draft")
    assert controller._repo is not None
    image_id = controller._repo.get_images_by_paths([str(image_path)])[0][0]

    # Act
    saved_description, changed = controller._mcp_set_image_description(
        image_id,
        str(image_path),
        "Updated through MCP",
        "replace",
    )
    saved = FilesystemSidecarRepository().read(image_path)
    result = controller.saveSelectedDescription("replace")

    # Assert
    assert saved_description == "Updated through MCP"
    assert changed is True
    assert controller.descriptionDraft == "Local draft"
    assert controller.descriptionDraftSavedChanged is True
    assert result is False
    assert saved is not None
    assert saved.sidecar.description == "Updated through MCP"


def test_app_controller_mcp_description_rejects_mismatched_image_identity(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _model, _db_path, image_path = tagging_controller

    # Act / Assert
    with pytest.raises(RuntimeError, match="ID and path"):
        controller._mcp_set_image_description(
            987654,
            str(image_path),
            "Wrong target",
            "replace",
        )
    assert FilesystemSidecarRepository().read(image_path) is None


def test_app_controller_mcp_description_round_trip_and_batch_errors(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, image_path = tagging_controller
    assert controller._repo is not None
    image_id = controller._repo.get_images_by_paths([str(image_path)])[0][0]
    set_id = controller.createImageSet("Description set")
    controller._repo.add_images_to_set(set_id, [str(image_path)])
    session = McpSessionService(controller._mcp)

    # Act
    session.set_image_description(image_id, str(image_path), "First paragraph", "replace")
    result = session.set_image_descriptions_batch([
        {"image_id": image_id, "path": str(image_path), "description": "Second paragraph", "mode": "append"},
        {"image_id": image_id + 99, "path": str(image_path), "description": "Wrong", "mode": "replace"},
    ])

    # Assert
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    expected = "First paragraph\n\nSecond paragraph"
    assert session.get_selected_image(include_preview=False).description == expected
    assert session.get_image_set_images(set_id)["images"][0]["description"] == expected
    assert controller.selectedImageDescription == expected
    assert controller._repo.count_images("Second") == 1


def test_app_controller_mcp_tag_exclusions_round_trip_persist_and_refresh(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, path = tagging_controller
    assert controller._repo is not None
    image_id = controller._repo.get_images_by_paths([str(path)])[0][0]
    metadata = {"XMP-dc:Subject": ["Family", "Holiday"]}
    controller._repo.upsert_image(str(path), path.name, 1.0, 5, metadata, "")
    controller._update_exif_table(json.dumps(metadata))
    controller.addSelectedFreeTag("Custom")
    controller.updateSelectedDescriptionDraft("Saved caption")
    assert controller.saveSelectedDescription("replace")
    controller.updateSelectedDescriptionDraft("Unsaved draft")
    set_id = controller.createImageSet("Exclusion set")
    controller._repo.add_images_to_set(set_id, [str(path)])
    session = McpSessionService(controller._mcp)
    original_bytes = path.read_bytes()

    # Act
    individual = session.set_image_embedded_tag_excluded(image_id, str(path), "Family", True)
    unchanged = session.set_image_embedded_tag_excluded(image_id, str(path), "family", True)
    all_tags = session.set_image_all_embedded_tags_excluded(image_id, str(path), True)
    unchanged_all = session.set_image_all_embedded_tags_excluded(image_id, str(path), True)
    payload = session.get_selected_image(include_preview=False).to_dict()
    listed = session.get_image_set_images(set_id)["images"][0]

    # Assert
    assert individual["excluded_embedded_tags"] == ["Family"] and individual["changed"]
    assert unchanged["changed"] is False and unchanged_all["changed"] is False
    assert all_tags["exclude_all_embedded_tags"] is True
    for result in (payload, listed):
        assert result["excluded_embedded_tags"] == ["Family"]
        assert result["exclude_all_embedded_tags"] is True
    assert controller.excludeAllEmbeddedTags
    assert tuple(controller._tagging.derivative_tags_model._rows) == ("Custom",)
    loaded = FilesystemSidecarRepository().read(path)
    assert loaded is not None and loaded.sidecar.excluded_embedded_tags == ("Family",)
    assert loaded.sidecar.exclude_all_embedded_tags
    assert loaded.sidecar.free_tags == ("Custom",)
    assert loaded.sidecar.description == "Saved caption"
    assert controller.descriptionDraft == "Unsaved draft"
    assert path.read_bytes() == original_bytes
    assert controller._repo.get_images_by_paths([str(path)])[0][3] == json.dumps(metadata)

    session.set_image_all_embedded_tags_excluded(image_id, str(path), False)
    assert not controller.excludeAllEmbeddedTags
    assert "Holiday" in controller._tagging.derivative_tags_model._rows
    assert "Family" not in controller._tagging.derivative_tags_model._rows
    restored = session.set_image_embedded_tag_excluded(image_id, str(path), "FAMILY", False)
    assert restored["excluded_embedded_tags"] == []
    assert "Family" in controller._tagging.derivative_tags_model._rows


@pytest.mark.parametrize("all_tags", [False, True])
def test_app_controller_mcp_tag_exclusions_target_explicit_nonselected_image(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    all_tags: bool,
) -> None:
    # Arrange
    controller, _, _, selected = tagging_controller
    assert controller._repo is not None
    target = tmp_path / "target.jpg"
    target.write_bytes(b"image")
    controller._repo.upsert_image(str(target), target.name, 1.0, 5, {}, "")
    image_id = controller._repo.get_images_by_paths([str(target)])[0][0]
    session = McpSessionService(controller._mcp)

    # Act
    if all_tags:
        session.set_image_all_embedded_tags_excluded(image_id, str(target), True)
    else:
        session.set_image_embedded_tag_excluded(image_id, str(target), "Family", True)

    # Assert
    loaded = FilesystemSidecarRepository().read(target)
    assert loaded is not None
    assert loaded.sidecar.exclude_all_embedded_tags is all_tags
    assert loaded.sidecar.excluded_embedded_tags == (() if all_tags else ("Family",))
    assert FilesystemSidecarRepository().read(selected) is None
    payload = session.get_selected_image(include_preview=False).to_dict()
    assert payload["excluded_embedded_tags"] == []
    assert payload["exclude_all_embedded_tags"] is False


@pytest.mark.parametrize("all_tags", [False, True])
@pytest.mark.parametrize("blocked_by", ["locked", "disabled", "identity"])
def test_app_controller_mcp_tag_exclusions_reject_unavailable_or_wrong_identity(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    all_tags: bool,
    blocked_by: str,
) -> None:
    # Arrange
    controller, _, _, path = tagging_controller
    assert controller._repo is not None
    image_id = controller._repo.get_images_by_paths([str(path)])[0][0]
    if blocked_by == "locked":
        controller._is_locked = True
    elif blocked_by == "disabled":
        controller.setTaggingEnabled(False)
    else:
        image_id += 100
    session = McpSessionService(controller._mcp)

    # Act / Assert
    with pytest.raises(RuntimeError):
        if all_tags:
            session.set_image_all_embedded_tags_excluded(image_id, str(path), True)
        else:
            session.set_image_embedded_tag_excluded(image_id, str(path), "Family", True)
    assert FilesystemSidecarRepository().read(path) is None


def test_app_controller_description_exclusion_without_replacement_preserves_draft(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, image_path = tagging_controller
    session = McpSessionService(controller._mcp)
    assert controller._repo is not None
    image_id = controller._repo.get_images_by_paths([str(image_path)])[0][0]
    controller.updateSelectedDescriptionDraft("Unsaved draft")

    # Act
    controller.setSelectedEmbeddedDescriptionExcluded(True)
    saved = FilesystemSidecarRepository().read(image_path)
    payload = session.get_selected_image(include_preview=False).to_dict()
    cleared = session.set_image_description_excluded(image_id, str(image_path), False)

    # Assert
    assert saved is not None and saved.sidecar.exclude_embedded_description
    assert saved.sidecar.description == ""
    assert payload["exclude_embedded_description"] is True
    assert cleared["exclude_embedded_description"] is False
    assert controller.excludeEmbeddedDescription is False
    assert controller.descriptionDraft == "Unsaved draft"
    assert not controller.descriptionDraftSavedChanged


def test_final_derivative_description_preview_uses_saved_text_and_exclusion(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, _, _, _ = tagging_controller
    controller._update_exif_table('{"IFD0:ImageDescription": "Embedded"}')
    controller.updateSelectedDescriptionDraft("Custom")

    # Act / Assert
    assert controller.finalDerivativeDescription == "Embedded"
    controller.saveSelectedDescription("replace")
    assert controller.finalDerivativeDescription == "Embedded\n\nCustom"
    controller.setSelectedEmbeddedDescriptionExcluded(True)
    assert controller.finalDerivativeDescription == "Custom"
    controller.updateSelectedDescriptionDraft("")
    controller.saveSelectedDescription("replace")
    assert controller.finalDerivativeDescription == ""
    controller.setSelectedEmbeddedDescriptionExcluded(False)
    assert controller.finalDerivativeDescription == "Embedded"


@pytest.mark.parametrize("locked", [False, True])
def test_app_controller_mcp_description_disabled_or_locked_rejects_write(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path], locked: bool
) -> None:
    # Arrange
    controller, _, _, image_path = tagging_controller
    if locked:
        controller._is_locked = True
    else:
        controller.setTaggingEnabled(False)
    session = McpSessionService(controller._mcp)

    # Act / Assert
    with pytest.raises(RuntimeError):
        session.set_image_description(1, str(image_path), "Caption", "replace")
    assert FilesystemSidecarRepository().read(image_path) is None


def test_description_qml_save_button_enter_and_shift_enter_preserve_editor(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
) -> None:
    # Arrange
    controller, search_model, _, image_path = tagging_controller
    controller._update_exif_table(json.dumps({
        "IFD0:ImageDescription": 'PRC92-15\r"Desktop Universe"\rGuide Star Catalogue Compression\r',
    }))
    controller.updateSelectedDescriptionDraft("Saved caption")
    controller.saveSelectedDescription("replace")
    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", PreviewImageProvider())
    engine.addImageProvider("raw", RawImageProvider())
    proxy = CheckedFilterProxyModel()
    proxy.setSourceModel(search_model)
    controller.set_filter_proxy(proxy)
    exif_model = ExifListModel()
    folder_model = FolderListModel()
    settings = SettingsModel(image_path.parent / "description-qml-settings.json")
    context = engine.rootContext()
    for name, value in {
        "controller": controller, "searchModel": search_model,
        "filteredSearchModel": proxy, "exifModel": exif_model,
        "folderListModel": folder_model, "settingsModel": settings,
        "thirdPartyLicensesHtml": "", "userManualUrl": "",
    }.items():
        context.setContextProperty(name, value)
    engine.load(QUrl.fromLocalFile(str(_QML_DIR / "Main.qml")))
    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5000)
    root = engine.rootObjects()[0]
    drawer = root.findChild(QObject, "taggingDrawer")
    button = root.findChild(QObject, "saveDescriptionButton")
    editor = root.findChild(QQuickItem, "descriptionDraftEditor")
    embedded_editor = root.findChild(QQuickItem, "embeddedImageDescription")
    exclude_switch = root.findChild(QObject, "excludeEmbeddedDescriptionSwitch")
    assert drawer is not None and button is not None and editor is not None
    assert exclude_switch is not None
    assert embedded_editor is not None
    assert embedded_editor.property("text") == 'PRC92-15\n"Desktop Universe"\nGuide Star Catalogue Compression'
    assert embedded_editor.property("readOnly")
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    exclude_switch.setProperty("checked", True)
    QMetaObject.invokeMethod(exclude_switch, "toggled", Qt.ConnectionType.DirectConnection)
    assert controller.excludeEmbeddedDescription
    assert editor.property("text") == "Saved caption"
    controller.updateSelectedDescriptionDraft("Replacement")

    # Act / Assert
    QMetaObject.invokeMethod(button, "clicked", Qt.ConnectionType.DirectConnection)
    assert controller.selectedImageDescription == "Replacement"
    assert editor.property("text") == "Replacement"
    assert not controller.descriptionDraftActive
    assert not button.property("enabled")
    controller.updateSelectedDescriptionDraft("")
    QMetaObject.invokeMethod(button, "clicked", Qt.ConnectionType.DirectConnection)
    assert controller.selectedImageDescription == ""
    saved = FilesystemSidecarRepository().read(image_path)
    assert saved is not None and saved.sidecar.description == ""

    # Enter saves, while Shift+Enter keeps multiline edits unsaved.
    assert isinstance(root, QQuickWindow)
    root.setWidth(1200)
    root.setHeight(900)
    root.show()
    qtbot.waitExposed(root)
    editor.forceActiveFocus()
    for character in "Keyboard caption":
        QTest.keyClick(root, character)
    QTest.keyClick(root, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert "\n" in controller.descriptionDraft
    assert controller.selectedImageDescription == ""
    QTest.keyClick(root, Qt.Key.Key_Return)
    assert controller.selectedImageDescription == "Keyboard caption"
    assert not controller.descriptionDraftActive
    assert editor.property("text") == "Keyboard caption"

    QTest.keyClick(root, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(root, Qt.Key.Key_Backspace)
    assert controller.descriptionDraftActive
    assert button.property("enabled")
    QTest.keyClick(root, Qt.Key.Key_Return)
    assert controller.selectedImageDescription == ""
    assert not controller.descriptionDraftActive
    saved = FilesystemSidecarRepository().read(image_path)
    assert saved is not None and saved.sidecar.description == ""

    # Long descriptions must remain reachable inside the editable and preview fields.
    long_text = "\n".join(f"Description line {index}" for index in range(80))
    controller._update_exif_table(json.dumps({"IFD0:ImageDescription": long_text}))
    controller.updateSelectedDescriptionDraft(long_text)
    assert controller.saveSelectedDescription("replace")
    controller.updateSelectedDescriptionDraft(long_text)
    for name in (
        "embeddedDescriptionScrollView", "descriptionDraftScrollView",
        "finalDescriptionScrollView",
    ):
        scroll = root.findChild(QQuickItem, name)
        assert scroll is not None
        scroll.ensurePolished()
        flickable = scroll.property("contentItem")
        assert isinstance(flickable, QQuickItem)
        qtbot.waitUntil(
            lambda: float(flickable.property("contentHeight")) > flickable.height(),
            timeout=3000,
        )
        bottom = float(flickable.property("contentHeight")) - flickable.height()
        flickable.setProperty("contentY", bottom)
        assert float(flickable.property("contentY")) == pytest.approx(bottom, abs=1)

    engine.deleteLater()
    qtbot.wait(100)


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
    assert QMetaObject.invokeMethod(
        remove_button, "click", Qt.ConnectionType.DirectConnection
    )
    qtbot.waitUntil(lambda: int(current_tags.property("count")) == 0, timeout=1_000)

    controller.addSelectedFreeTag("Family")
    qtbot.waitUntil(lambda: int(current_tags.property("count")) == 1, timeout=1_000)
    remove_button = find_remove_button(current_tags)
    assert remove_button is not None
    if root.isActive():
        center = remove_button.mapToScene(
            QPointF(float(remove_button.width()) / 2.0, float(remove_button.height()) / 2.0)
        )
        right_edge = remove_button.mapToScene(
            QPointF(float(remove_button.width()) - 3.0, float(remove_button.height()) / 2.0)
        )
        if (
            0 <= center.x() < root.width()
            and 0 <= center.y() < root.height()
            and 0 <= right_edge.x() < root.width()
            and 0 <= right_edge.y() < root.height()
        ):
            remove_mouse_area = next(
                child
                for child in remove_button.childItems()
                if child.objectName() == "removeTagMouseArea"
            )
            QTest.mouseMove(root, QPoint(round(center.x()), round(center.y())))
            qtbot.wait(100)
            center_hovered = bool(remove_mouse_area.property("containsMouse"))
            QTest.mouseMove(root, QPoint(round(right_edge.x()), round(right_edge.y())))
            qtbot.wait(100)
            edge_hovered = bool(remove_mouse_area.property("containsMouse"))
            assert center_hovered is True
            assert edge_hovered is True
    assert QMetaObject.invokeMethod(
        remove_button, "click", Qt.ConnectionType.DirectConnection
    )

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


@pytest.mark.parametrize(("source_text", "mode", "expected"), [
    ("Saved caption", "add", "Target caption\n\nSaved caption"),
    ("Saved caption", "replace", "Saved caption"),
    ("", "replace", ""),
])
def test_copy_description_qml_modes_confirm_replacement_and_clear(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    source_text: str,
    mode: str,
    expected: str,
) -> None:
    # Arrange
    controller, _, _, source = tagging_controller
    assert controller._repo is not None
    target = tmp_path / "target.jpg"
    target.write_bytes(b"image")
    controller._repo.upsert_image(str(target), target.name, 1.0, 5, {}, "")
    TaggingService(controller._repo, FilesystemSidecarRepository()).set_description(
        str(target), "Target caption", "replace",
    )
    set_id = controller.createImageSet("Description destination")
    controller._repo.add_images_to_set(set_id, [str(source), str(target)])
    if source_text:
        controller.updateSelectedDescriptionDraft(source_text)
        assert controller.saveSelectedDescription("replace")
    engine = QQmlApplicationEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(_QML_DIR / "TaggingDrawer.qml")))
    drawer = component.createWithInitialProperties({
        "appController": controller, "appSettings": controller._settings, "copyMode": True,
    })
    assert drawer is not None, [error.toString() for error in component.errors()]
    window = QQuickWindow()
    window.setWidth(1200)
    window.setHeight(800)
    drawer.setProperty("parent", window.contentItem())
    window.show()
    qtbot.waitExposed(window)
    QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: bool(drawer.property("opened")), timeout=3000)
    target_selector = drawer.findChild(QObject, "copyDescriptionTarget")
    button = drawer.findChild(QObject, "copyDescriptionButton")
    replace_mode = drawer.findChild(QObject, "copyDescriptionReplaceMode")
    dialog = drawer.findChild(QObject, "replaceCopiedDescriptionDialog")
    assert target_selector is not None and button is not None
    assert replace_mode is not None and dialog is not None
    target_selector.setProperty("currentIndex", int(target_selector.property("count")) - 1)
    assert target_selector.property("currentValue") == f"set:{set_id}"
    assert bool(button.property("enabled")) == bool(source_text)
    if mode == "replace":
        replace_mode.setProperty("checked", True)
    assert button.property("enabled")

    # Act
    QMetaObject.invokeMethod(button, "clicked", Qt.ConnectionType.DirectConnection)
    if mode == "replace":
        assert dialog.property("visible")
        assert not controller.isTaggingBulk
        assert controller._repo.get_description(str(target)) == "Target caption"
        QMetaObject.invokeMethod(dialog, "reject", Qt.ConnectionType.DirectConnection)
        assert controller._repo.get_description(str(target)) == "Target caption"
        QMetaObject.invokeMethod(button, "clicked", Qt.ConnectionType.DirectConnection)
        QMetaObject.invokeMethod(dialog, "accept", Qt.ConnectionType.DirectConnection)
    qtbot.waitUntil(lambda: not controller.isTaggingBulk, timeout=5000)

    # Assert
    assert controller._repo.get_description(str(target)) == expected
    loaded = FilesystemSidecarRepository().read(target)
    assert loaded is not None and loaded.sidecar.description == expected
    assert controller.selectedImageDescription == source_text
    assert "Copied description to 1 image(s)" in controller.taggingBulkSummary
    drawer.deleteLater()
    window.close()
    window.deleteLater()
    qtbot.wait(100)
    engine.deleteLater()


@pytest.mark.parametrize("scope", ["set", "marked", "destination"])
def test_app_controller_copy_description_scopes_copy_saved_text_only(
    qtbot: QtBot,
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    scope: str,
) -> None:
    # Arrange
    controller, _, _, source = tagging_controller
    target = tmp_path / "target.jpg"
    outside = tmp_path / "outside.jpg"
    assert controller._repo is not None
    for path in (target, outside):
        path.write_bytes(b"image")
        controller._repo.upsert_image(str(path), path.name, 1.0, 5, {}, "")
        controller._repo.mark_image(str(path), True)
    set_id = controller.createImageSet("Description copy set")
    controller._repo.add_images_to_set(set_id, [str(source), str(target)])
    controller.setActionImageSet(set_id)
    controller.selectImageSetMember(str(source))
    controller.updateSelectedDescriptionDraft("Saved source")
    assert controller.saveSelectedDescription("replace")
    controller.updateSelectedDescriptionDraft("Unsaved draft")
    source_revision = FilesystemSidecarRepository.sidecar_path(source).stat().st_mtime_ns
    selected_scope = f"set:{set_id}" if scope == "destination" else scope

    # Act
    controller.copySelectedDescription(selected_scope, "add")
    qtbot.waitUntil(lambda: not controller.isTaggingBulk, timeout=5000)

    # Assert
    assert controller._repo.get_description(str(target)) == "Saved source"
    assert controller._repo.get_description(str(outside)) == ""
    assert not FilesystemSidecarRepository.sidecar_path(outside).exists()
    assert controller.descriptionDraft == "Unsaved draft"
    assert FilesystemSidecarRepository.sidecar_path(source).stat().st_mtime_ns == source_revision
    assert "Copied description to 1 image(s)" in controller.taggingBulkSummary


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


@pytest.mark.parametrize("copy_description", [False, True])
def test_app_controller_copy_metadata_folder_forwards_current_browse_scope(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    copy_description: bool,
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
    if copy_description:
        controller.copySelectedDescription("folder", "replace")
    else:
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
        **({"copy_description": True} if copy_description else {}),
    }
    assert worker.started is True


@pytest.mark.parametrize("copy_description", [False, True])
def test_app_controller_copy_metadata_results_uses_complete_ai_cache(
    tagging_controller: tuple[AppController, SearchListModel, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    copy_description: bool,
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
    if copy_description:
        controller.copySelectedDescription("results", "add")
    else:
        controller.copySelectedTags("results", "add")

    # Assert
    worker = FakeCopyTagsWorker.instances[0]
    assert worker.options == {
        "image_paths": [str(image_path), str(second_path)],
        **({"copy_description": True} if copy_description else {}),
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
