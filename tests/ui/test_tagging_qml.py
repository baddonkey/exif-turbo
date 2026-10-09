from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.checked_filter_proxy_model import CheckedFilterProxyModel
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.folder_list_model import FolderListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.models.settings_model import SettingsModel
from exif_turbo.ui.providers.preview_image_provider import PreviewImageProvider
from exif_turbo.ui.providers.raw_image_provider import RawImageProvider
from exif_turbo.ui.view_models.app_controller import AppController


_QML_DIR = Path(__file__).resolve().parents[2] / "src" / "exif_turbo" / "ui" / "qml"


def test_tagging_qml_contract_keeps_custom_tagging_and_removes_vocabulary_suggestions() -> None:
    # Arrange
    drawer_source = (_QML_DIR / "TaggingDrawer.qml").read_text(encoding="utf-8")
    settings_source = (_QML_DIR / "CustomTaggingSettings.qml").read_text(encoding="utf-8")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            _QML_DIR / "Main.qml",
            _QML_DIR / "TaggingDrawer.qml",
            _QML_DIR / "CustomTaggingSettings.qml",
        )
    )
    required_bindings = {
        'objectName: "taggingWorkbenchButton"',
        'objectName: "taggingDrawer"',
        'sequence: "Ctrl+T"',
        "addSelectedFreeTag(",
        "removeSelectedFreeTag(",
        "searchFreeTags(",
        "setTaggingEnabled(",
        "generateDerivativesForCurrentResults(",
        "generateDerivativesForMarked(",
        "cancelDerivativeExport(",
        "copySelectedTags(",
        "cancelBulkTagging(",
    }

    # Act
    missing = sorted(binding for binding in required_bindings if binding not in source)

    # Assert
    assert missing == []
    assert 'objectName: "taggingEnabledSwitch"' in settings_source
    assert 'text: qsTr("Custom Tagging")' in settings_source
    assert "Wikidata" not in source
    assert "TGM" not in source
    assert "proposal" not in source.lower()
    assert 'objectName: "addFreeTagButton"' in source
    assert 'objectName: "freeTagSuggestions"' in source
    assert 'objectName: "currentFreeTags"' in source
    remove_button_declaration = drawer_source.split(
        'objectName: "removeFreeTagButton"', 1
    )[1].split("\n                            }", 1)[0]
    assert 'Accessible.name: qsTr("Remove custom tag from selected image")' in remove_button_declaration
    assert "ToolTip" not in remove_button_declaration
    assert 'text: "\\u2212"' in remove_button_declaration
    assert "horizontalAlignment: Text.AlignHCenter" in remove_button_declaration
    assert "verticalAlignment: Text.AlignVCenter" in remove_button_declaration
    assert 'objectName: "embeddedTags"' in source
    assert 'objectName: "excludeAllEmbeddedTagsSwitch"' in drawer_source
    assert "setExcludeAllSelectedEmbeddedTags(checked)" in drawer_source
    assert "setSelectedEmbeddedTagExcluded(" in drawer_source
    assert "label, !excluded" in drawer_source
    assert "font.strikeout: effectivelyExcluded" in drawer_source
    assert 'objectName: "derivativeTagsFooter"' in source
    assert 'objectName: "finalDerivativeTags"' in source
    assert source.index('objectName: "derivativeTagsFooter"') > source.index(
        'objectName: "taggingScrollView"'
    )
    assert 'text: qsTr("Existing image tags")' in source
    assert "appController.embeddedTagsModel" in source
    assert "appController.derivativeTagsModel" in source
    assert 'text: qsTr("Custom tags")' in drawer_source
    assert 'objectName: "copyTagsTarget"' in drawer_source
    assert "onBrowseModeChanged: copyTarget.currentIndex = 0" in drawer_source
    assert 'objectName: "copyTagsAddMode"' in drawer_source
    assert 'objectName: "copyTagsReplaceMode"' in drawer_source
    assert drawer_source.count("RadioButton {") >= 2
    assert 'objectName: "copyTagsButton"' in drawer_source
    assert 'objectName: "replaceTagsDialog"' in drawer_source
    assert 'value: "results"' in drawer_source
    assert 'value: "folder"' in drawer_source
    assert 'value: "marked"' in drawer_source
    assert "Marked images" in drawer_source
    assert drawer_source.index('objectName: "copyTagsTarget"') > drawer_source.index(
        'objectName: "currentFreeTags"'
    )
    assert "markedMode" not in drawer_source
    assert "applyConceptToMarked" not in drawer_source
    assert "removeConceptFromMarked" not in drawer_source
    assert "generateMarkedTagProposals" not in drawer_source
    assert "autoAcceptMarkedTagProposals" not in drawer_source
    assert 'objectName: "autoAcceptSwitch"' not in source
    assert 'objectName: "autoAcceptThresholdSpinBox"' not in source
    assert "generateDerivativesForMarked" not in drawer_source
    assert "function onCurrentResultRowChanged()" in drawer_source
    assert "property bool showFreeTagSuggestions: false" in drawer_source
    assert "onTextEdited: {" in drawer_source
    assert "drawer.showFreeTagSuggestions = true" in drawer_source
    assert "drawer.showFreeTagSuggestions = activeFocus" in drawer_source
    assert "showFreeTagSuggestions = false" in drawer_source
    assert "visible: drawer.showFreeTagSuggestions && count > 0" in drawer_source
    assert "onPressed: drawer.addFreeTag(label)" in drawer_source
    assert "required property string label" in drawer_source
    assert "Generate Tagged Derivatives for Current &Results..." in source
    assert "Generate Tagged Derivatives for &Marked Images" in source
    assert "FolderDialog {" in source
    assert 'property string scope: "results"' in source
    assert 'objectName: "tagProposalsScrollBar"' not in drawer_source


def test_main_qml_tagging_drawer_pushes_content_aside(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    # Arrange
    search_model = SearchListModel(cache_dir=tmp_path / "thumbs")
    settings_model = SettingsModel(tmp_path / "settings.json")
    controller = AppController(
        tmp_path / "tagging.db",
        search_model,
        ExifListModel(),
        FolderListModel(),
        settings_model,
    )
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

    # Act
    engine.load(QUrl.fromLocalFile(str(_QML_DIR / "Main.qml")))
    qtbot.waitUntil(lambda: bool(engine.rootObjects()), timeout=5_000)
    root: QQuickWindow = engine.rootObjects()[0]  # type: ignore[assignment]
    root.setWidth(1200)
    root.setHeight(800)
    root.show()
    qtbot.waitExposed(root, timeout=3_000)

    drawer = root.findChild(QObject, "taggingDrawer")
    search_viewport = root.findChild(QQuickItem, "searchContentViewport")
    browse_viewport = root.findChild(QQuickItem, "browseContentViewport")
    tab_bar = root.findChild(QQuickItem, "mainTabBar")
    assert drawer is not None
    assert search_viewport is not None
    assert browse_viewport is not None
    assert tab_bar is not None

    def assert_viewports_track_drawer() -> None:
        drawer_left = root.width() - float(drawer.property("width")) * float(
            drawer.property("position")
        )
        for viewport in (search_viewport, browse_viewport):
            viewport_right = viewport.x() + viewport.width()
            assert abs(viewport_right - drawer_left) < 1.5

    # Assert
    for tab_index in (0, 1):
        tab_bar.setProperty("currentIndex", tab_index)
        qtbot.waitUntil(lambda: float(drawer.property("position")) < 0.001, timeout=3_000)
        assert_viewports_track_drawer()

        QMetaObject.invokeMethod(drawer, "openTaggingPanel", Qt.ConnectionType.DirectConnection)
        qtbot.waitUntil(
            lambda: 0.1 < float(drawer.property("position")) < 0.9,
            timeout=3_000,
        )
        assert_viewports_track_drawer()
        qtbot.waitUntil(lambda: float(drawer.property("position")) > 0.999, timeout=3_000)
        assert_viewports_track_drawer()

        QMetaObject.invokeMethod(drawer, "close", Qt.ConnectionType.DirectConnection)
        qtbot.waitUntil(lambda: float(drawer.property("position")) < 0.001, timeout=3_000)
        assert_viewports_track_drawer()

    assert root.findChild(QQuickItem, "taggingWorkbenchButton") is not None
    assert root.findChild(QQuickItem, "taggingEnabledSwitch") is not None
    assert root.findChild(QQuickItem, "tagProposalsScrollBar") is None
    assert root.findChild(QQuickItem, "freeTagField") is not None
    assert root.findChild(QQuickItem, "addFreeTagButton") is not None
    assert root.findChild(QQuickItem, "freeTagSuggestions") is not None
    assert root.findChild(QQuickItem, "currentFreeTags") is not None
    copy_target = root.findChild(QQuickItem, "copyTagsTarget")
    assert copy_target is not None
    assert copy_target.property("currentValue") == "marked"

    controller.close()
    engine.deleteLater()
    qtbot.wait(100)