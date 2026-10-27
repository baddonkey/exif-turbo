pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts

Dialog {
    id: root
    objectName: "derivativeExportDialog"
    title: qsTr("Export Derivatives")
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(760, parent ? parent.width - 32 : 720)
    height: Math.min(720, parent ? parent.height - 32 : 680)
    padding: 18

    property var appSettings
    property string scope: "results"
    property string outputDirectoryText: ""
    property string outputDirectoryUrl: ""
    property string sampleSourcePath: ""
    property bool preserveFolderStructure: true
    property var rows: []
    readonly property int selectedCount: rows.filter(function(row) { return row.selected }).length
    readonly property bool canExport: outputDirectoryText.trim() !== ""
                                       && selectedCount > 0
                                       && !hasSelectedNameConflicts()

    signal exportRequested(string scope, string outputUrl, string flavoursJson, bool preserveFolderStructure)

    function openForScope(nextScope) {
        scope = nextScope
        outputDirectoryText = ""
        outputDirectoryUrl = ""
        preserveFolderStructure = true
        rows = []
        if (appSettings) {
            try {
                var saved = JSON.parse(appSettings.derivativeExportFlavoursJson)
                rows = saved.map(function(flavour) {
                    return Object.assign({}, flavour, {
                        selected: flavour.selected_by_default,
                        effective_metadata_mode: flavour.format === "original"
                                                 ? "original" : flavour.metadata_mode
                    })
                })
            } catch (error) {
                rows = []
            }
        }
        open()
    }

    function setRow(id, changes) {
        var next = rows.slice()
        for (var index = 0; index < next.length; index++) {
            if (next[index].id !== id)
                continue
            var updated = Object.assign({}, next[index])
            for (var key in changes)
                updated[key] = changes[key]
            next[index] = updated
            rows = next
            return
        }
    }

    function selectRows(mode) {
        rows = rows.map(function(row) {
            var selected = mode === "all"
                          || (mode === "default" && row.selected_by_default)
            return Object.assign({}, row, { selected: selected })
        })
    }

    function localPathToUrl(path) {
        var normalized = path.replace(/\\/g, "/")
        if (/^[A-Za-z]:\//.test(normalized))
            return "file:///" + normalized
        if (normalized.charAt(0) === "/")
            return "file://" + normalized
        return ""
    }

    function localPathFromUrl(url) {
        var value = decodeURIComponent(url.replace(/^file:\/\/\/?/, ""))
        if (Qt.platform.os === "windows") {
            if (/^[A-Za-z]:\//.test(value))
                return value.replace(/\//g, "\\")
            if (!value.startsWith("/"))
                return "\\\\" + value.replace(/\//g, "\\")
        }
        return "/" + value.replace(/^\//, "")
    }

    function setOutputFolderUrl(url) {
        outputDirectoryUrl = url
        outputDirectoryText = localPathFromUrl(url)
    }

    function currentOutputUrl() {
        return outputDirectoryUrl || localPathToUrl(outputDirectoryText.trim())
    }

    function extensionFor(row) {
        if (row.format === "original") {
            var filename = sampleSourcePath.replace(/\\/g, "/").split("/").pop()
            var dot = filename.lastIndexOf(".")
            return dot >= 0 ? filename.substring(dot) : ""
        }
        return { jpeg: ".jpg", png: ".png", tiff: ".tif" }[row.format] || ""
    }

    function sampleStem() {
        var filename = sampleSourcePath.replace(/\\/g, "/").split("/").pop()
        var dot = filename.lastIndexOf(".")
        return dot >= 0 ? filename.substring(0, dot) : (filename || "DSC_1234")
    }

    function rowSummary(row) {
        if (row.format === "original")
            return qsTr("original file, unchanged")
        var size = row.resize_mode === "original_pixels"
                   ? qsTr("original size")
                   : qsTr("%1 px").arg(row.pixel_limit)
        var encoding = row.format === "jpeg" ? qsTr("Q%1").arg(row.jpeg_quality)
                      : row.format === "png" ? qsTr("Level %1").arg(row.png_compression)
                      : row.tiff_compression.toUpperCase()
        return qsTr("%1, %2, metadata: %3")
               .arg(size).arg(encoding).arg(row.effective_metadata_mode)
    }

    function previewText() {
        var lines = []
        rows.forEach(function(row) {
            if (!row.selected)
                return
            var stem = sampleStem() + row.suffix
            lines.push(stem + extensionFor(row) + "    (" + rowSummary(row) + ")")
        })
        return lines.length ? lines.join("\n") : qsTr("No flavours selected")
    }

    function hasSelectedNameConflicts() {
        var outputNames = {}
        for (var index = 0; index < rows.length; index++) {
            var row = rows[index]
            if (!row.selected)
                continue
            var outputName = String(
                sampleStem() + row.suffix + extensionFor(row)
            ).toLowerCase()
            if (outputNames[outputName])
                return true
            outputNames[outputName] = true
        }
        return false
    }

    function selectedFlavoursJson() {
        return JSON.stringify(rows.filter(function(row) { return row.selected }).map(function(row) {
            var flavour = Object.assign({}, row)
            flavour.metadata_mode = row.effective_metadata_mode
            delete flavour.selected
            delete flavour.effective_metadata_mode
            return flavour
        }))
    }

    FolderDialog {
        id: outputFolderDialog
        objectName: "derivativeOutputFolderDialog"
        title: qsTr("Choose Output Directory")
        currentFolder: root.outputDirectoryUrl || "file:///"
        onAccepted: {
            root.setOutputFolderUrl(outputFolderDialog.selectedFolder.toString())
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Label {
                text: qsTr("Export Derivatives")
                font.pixelSize: 22
                font.weight: Font.DemiBold
            }
            Label {
                text: qsTr("Generate derivative images using the selected export flavours.")
                opacity: 0.7
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Label { text: qsTr("Output directory"); Layout.preferredWidth: 128 }
            TextField {
                objectName: "derivativeOutputDirectoryField"
                Layout.fillWidth: true
                placeholderText: qsTr("Choose an output directory")
                text: root.outputDirectoryText
                onTextEdited: {
                    root.outputDirectoryText = text
                    root.outputDirectoryUrl = ""
                }
            }
            Button {
                text: qsTr("Browse…")
                onClicked: outputFolderDialog.open()
            }
        }

        CheckBox {
            objectName: "preserveDerivativeFolderStructureCheck"
            text: qsTr("Create subdirectories (preserve folder structure)")
            checked: root.preserveFolderStructure
            onClicked: root.preserveFolderStructure = checked
        }

        RowLayout {
            Layout.fillWidth: true
            Label {
                text: qsTr("Export flavours")
                font.pixelSize: 16
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            Button { text: qsTr("Select Default"); onClicked: root.selectRows("default") }
            Button { text: qsTr("Select All"); onClicked: root.selectRows("all") }
            Button { text: qsTr("Select None"); onClicked: root.selectRows("none") }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label { text: ""; Layout.preferredWidth: 36 }
            Label { text: qsTr("Name"); Layout.fillWidth: true }
            Label { text: qsTr("Format"); Layout.preferredWidth: 62 }
            Label { text: qsTr("Size / Quality"); Layout.preferredWidth: 150 }
            Label { text: qsTr("Metadata"); Layout.preferredWidth: 125 }
        }

        ListView {
            id: flavourRows
            objectName: "derivativeExportFlavourRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.rows
            spacing: 1
            delegate: Rectangle {
                id: exportFlavourRow
                required property var modelData
                width: flavourRows.width
                height: 58
                color: modelData.selected
                       ? Qt.rgba(Material.accentColor.r, Material.accentColor.g,
                                 Material.accentColor.b, 0.12)
                       : "transparent"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    anchors.rightMargin: 6
                    spacing: 8
                    CheckBox {
                        checked: exportFlavourRow.modelData.selected
                        onClicked: root.setRow(exportFlavourRow.modelData.id, { selected: checked })
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Label { text: exportFlavourRow.modelData.name; elide: Text.ElideRight; Layout.fillWidth: true }
                        Label {
                            text: root.rowSummary(exportFlavourRow.modelData)
                            font.pixelSize: 11
                            opacity: 0.7
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                    Label { text: exportFlavourRow.modelData.format.toUpperCase(); Layout.preferredWidth: 62 }
                    Label {
                        text: exportFlavourRow.modelData.format === "original" ? "—" : root.rowSummary(exportFlavourRow.modelData).split(", metadata:")[0]
                        Layout.preferredWidth: 150
                        elide: Text.ElideRight
                    }
                    ComboBox {
                        objectName: "derivativeExportMetadataOverride"
                        Layout.preferredWidth: 125
                        model: [qsTr("None"), qsTr("Original"), qsTr("Custom")]
                        currentIndex: ["none", "original", "custom"].indexOf(exportFlavourRow.modelData.effective_metadata_mode)
                        enabled: exportFlavourRow.modelData.format !== "original"
                        onActivated: root.setRow(exportFlavourRow.modelData.id, {
                            effective_metadata_mode: ["none", "original", "custom"][currentIndex]
                        })
                    }
                }
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 1
                    color: Material.dividerColor
                }
            }
        }

        Label {
            text: qsTr("Preview")
            font.pixelSize: 16
            font.weight: Font.DemiBold
        }
        TextArea {
            objectName: "derivativeExportPreview"
            Layout.fillWidth: true
            Layout.preferredHeight: 78
            readOnly: true
            wrapMode: TextEdit.NoWrap
            text: root.previewText()
        }
        Label {
            visible: root.hasSelectedNameConflicts()
            text: qsTr("Selected flavours produce duplicate filenames.")
            color: Material.theme === Material.Dark ? "#ef9a9a" : "#c62828"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    footer: DialogButtonBox {
        alignment: Qt.AlignRight
        Button {
            text: qsTr("Cancel")
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            onClicked: root.reject()
        }
        Button {
            objectName: "derivativeExportStartButton"
            text: qsTr("Export")
            enabled: root.canExport && root.currentOutputUrl() !== ""
            highlighted: true
            DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            onClicked: {
                root.exportRequested(root.scope, root.currentOutputUrl(),
                                     root.selectedFlavoursJson(),
                                     root.preserveFolderStructure)
                root.accept()
            }
        }
    }
}