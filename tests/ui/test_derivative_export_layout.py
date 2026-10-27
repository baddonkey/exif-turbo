from __future__ import annotations

import gettext
import json
from io import BytesIO
from pathlib import Path

import pytest
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from PySide6.QtCore import QObject, QPointF, QUrl, QTranslator, QMetaObject, Qt
from PySide6.QtQml import QQmlApplicationEngine
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.settings_model import SettingsModel


class GermanTranslator(QTranslator):
    def __init__(self) -> None:
        super().__init__()
        source = (
            Path(__file__).resolve().parents[2]
            / "src/exif_turbo/i18n/locales/de/LC_MESSAGES/exif_turbo.po"
        )
        with source.open("rb") as catalog_file:
            catalog = read_po(catalog_file, locale="de")
        compiled = BytesIO()
        write_mo(compiled, catalog)
        compiled.seek(0)
        self.catalog = gettext.GNUTranslations(compiled)

    def translate(
        self, context: str, sourceText: str, disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        return self.catalog.gettext(sourceText)


@pytest.mark.parametrize("width,height", [(1200, 900), (800, 700), (1200, 1100), (1028, 749)])
def test_derivative_layout_german_resize_uses_space_and_scrolls(
    qtbot: QtBot, qapp: object, qml_engine: QQmlApplicationEngine,
    tmp_path: Path, width: int, height: int,
) -> None:
    # Arrange
    translator = GermanTranslator()
    settings = SettingsModel(tmp_path / "settings.json")
    qml_engine.rootContext().setContextProperty("layoutSettings", settings)
    source = b'''import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
ApplicationWindow {
    width: 1200; height: 900; visible: true
    DerivativeExportPage { id: page; anchors.fill: parent; appSettings: layoutSettings }
    DerivativeExportDialog { id: dialog; appSettings: layoutSettings; Material.elevation: 0 }
    function showExport() {
        page.visible = false
        dialog.openForScope("results")
        dialog.outputDirectoryText = "C:/Exports"
        dialog.sampleSourcePath = "DSC_1234.jpg"
    }
}'''
    base = Path(__file__).resolve().parents[2] / "src/exif_turbo/ui/qml/LayoutCheck.qml"
    try:
        qml_engine.loadData(source, QUrl.fromLocalFile(str(base)))
        qtbot.waitUntil(lambda: bool(qml_engine.rootObjects()), timeout=5_000)
        qapp.installTranslator(translator)
        qml_engine.retranslate()
        window = qml_engine.rootObjects()[0]
        window.setProperty("width", width)
        window.setProperty("height", height)
        page = window.findChild(QObject, "derivativeExportPage")
        assert page is not None
        flavours = json.loads(settings.property("derivativeExportFlavoursJson"))
        web_jpeg = next(flavour for flavour in flavours if flavour["name"] == "Web JPEG")
        page.setProperty("selectedFlavourId", web_jpeg["id"])
        panel = window.findChild(QObject, "derivativeSettingsPanel")
        scroll = window.findChild(QObject, "derivativeSettingsScroll")
        assert panel is not None and scroll is not None

        # Act / Assert
        qtbot.waitUntil(lambda: panel.property("height") >= 360)
        if page.property("width") >= 1100:
            qtbot.waitUntil(
                lambda: panel.property("height") > page.property("height") - 150
            )
        qtbot.waitUntil(lambda: scroll.property("contentHeight") > 0)
        name_field = window.findChild(QObject, "derivativeFlavourNameField")
        assert name_field is not None
        qtbot.waitUntil(lambda: name_field.property("text") == "Web JPEG")
        for label in page.findChildren(QObject):
            if label.property("truncated") is not None:
                assert not label.property("truncated"), label.property("text")
        scrollbar = window.findChild(QObject, "derivativeSettingsScrollbar")
        assert scrollbar is not None
        if scroll.property("contentHeight") > scroll.property("availableHeight"):
            qtbot.waitUntil(lambda: bool(scrollbar.property("visible")))
        else:
            qtbot.waitUntil(lambda: not scrollbar.property("visible"))
        for control_name in (
            "derivativeFlavourNameField", "derivativeFlavourSuffixField",
            "derivativeFlavourFormatCombo", "derivativeFlavourResizeCombo",
            "derivativeFlavourMetadataCombo", "derivativeFlavourDpi",
        ):
            control = window.findChild(QObject, control_name)
            assert control is not None
            qtbot.waitUntil(
                lambda: not scrollbar.property("visible") or control.mapToItem(
                    scrollbar, QPointF(control.property("width"), 0)
                ).x() <= -8,
                timeout=2_000,
            )
            right_edge = control.mapToItem(
                scrollbar, QPointF(control.property("width"), 0)
            ).x()
            assert not scrollbar.property("visible") or right_edge <= -8, (
                control_name, right_edge
            )
        window.grabWindow().save(str(tmp_path / "settings-de.png"))
        assert QMetaObject.invokeMethod(window, "showExport", Qt.DirectConnection)
        rows = window.findChild(QObject, "derivativeExportFlavourRows")
        assert rows is not None
        dialog = window.findChild(QObject, "derivativeExportDialog")
        assert dialog is not None
        qtbot.waitUntil(lambda: bool(dialog.property("opened")))
        qtbot.waitUntil(lambda: rows.property("count") == 6)
        qtbot.waitUntil(lambda: rows.property("contentHeight") > 0)
        assert rows.property("height") >= 100
        for label in dialog.findChildren(QObject):
            if label.property("truncated") is not None:
                assert not label.property("truncated"), label.property("text")
        window.grabWindow().save(str(tmp_path / "dialog-de.png"))
    finally:
        qapp.removeTranslator(translator)