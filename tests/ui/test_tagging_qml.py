from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
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


def test_tagging_qml_contract_contains_required_controls_and_slots() -> None:
    # Arrange
    drawer_source = (_QML_DIR / "TaggingDrawer.qml").read_text(encoding="utf-8")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            _QML_DIR / "Main.qml",
            _QML_DIR / "TaggingDrawer.qml",
            _QML_DIR / "TaggingSettings.qml",
        )
    )
    required_bindings = {
        'objectName: "taggingWorkbenchButton"',
        'objectName: "taggingDrawer"',
        'sequence: "Ctrl+T"',
        "searchTgm(",
        "addSelectedTgmConcept(",
        "removeSelectedTgmConcept(",
        "acceptSelectedProposal(",
        "rejectSelectedProposal(",
        "generateSelectedTagProposals(",
        "installOrUpdateTgm(",
        "rebuildTgmVectors(",
        "cancelTgmOperation(",
        "cancelTagProposalGeneration(",
        "setTaggingEnabled(",
        "setProposalThreshold(",
        "setAutoAcceptEnabled(",
        "setAutoAcceptThreshold(",
    }

    # Act
    missing = sorted(binding for binding in required_bindings if binding not in source)

    # Assert
    assert missing == []
    assert 'objectName: "addTgmTermButton"' in source
    assert 'text: qsTr("Tags on current image")' in drawer_source
    assert "Marked images" not in drawer_source
    assert "markedMode" not in drawer_source
    assert "applyConceptToMarked" not in drawer_source
    assert "removeConceptFromMarked" not in drawer_source
    assert "generateMarkedTagProposals" not in drawer_source
    assert "autoAcceptMarkedTagProposals" not in drawer_source
    assert "generateDerivativesForMarked" not in drawer_source
    assert "function onCurrentResultRowChanged()" in drawer_source
    assert "onOpened: proposalGenerationTimer.restart()" in drawer_source
    assert "proposalGenerationTimer.restart()" in drawer_source
    assert "appController.generateSelectedTagProposals()" in drawer_source
    assert 'objectName: "tagProposalsScrollBar"' in drawer_source
    assert "active: proposalsList.contentHeight > proposalsList.height" in drawer_source


def test_main_qml_with_tagging_workbench_loads(
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
    root = engine.rootObjects()[0]

    # Assert
    assert root.findChild(QQuickItem, "taggingWorkbenchButton") is not None
    assert root.findChild(QObject, "taggingDrawer") is not None
    assert root.findChild(QQuickItem, "taggingEnabledSwitch") is not None
    assert root.findChild(QQuickItem, "tagProposalsScrollBar") is not None

    controller.close()
    engine.deleteLater()
    qtbot.wait(100)