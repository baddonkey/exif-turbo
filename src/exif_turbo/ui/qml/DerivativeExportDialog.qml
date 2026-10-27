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
    width: Math.min(960, parent ? parent.width - 32 : 920)
    height: Math.min(880, parent ? parent.height - 32 : 840)
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

    contentItem: ColumnLayout {
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

        ColumnLayout {
            Layout.fillWidth: true
            Label { text: qsTr("Output directory"); Layout.fillWidth: true; wrapMode: Text.Wrap }
            RowLayout {
                Layout.fillWidth: true
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
        }

        CheckBox {
            id: preserveFoldersCheck
            objectName: "preserveDerivativeFolderStructureCheck"
            Layout.fillWidth: true
            text: qsTr("Create subdirectories (preserve folder structure)")
            contentItem: Label {
                text: preserveFoldersCheck.text
                leftPadding: preserveFoldersCheck.indicator.width + preserveFoldersCheck.spacing
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap
            }
            checked: root.preserveFolderStructure
            onClicked: root.preserveFolderStructure = checked
        }

        ColumnLayout {
            Layout.fillWidth: true
            Label {
                text: qsTr("Export flavours")
                font.pixelSize: 16
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            Flow {
                Layout.fillWidth: true
                Layout.preferredHeight: implicitHeight
                spacing: 4
                Button { text: qsTr("Select Default"); onClicked: root.selectRows("default") }
                Button { text: qsTr("Select All"); onClicked: root.selectRows("all") }
                Button { text: qsTr("Select None"); onClicked: root.selectRows("none") }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label { text: ""; Layout.preferredWidth: 36 }
            Label { text: qsTr("Name"); Layout.fillWidth: true }
            Label { text: qsTr("Metadata"); Layout.preferredWidth: 180; wrapMode: Text.Wrap }
        }

        ListView {
            id: flavourRows
            objectName: "derivativeExportFlavourRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 100
            clip: true
            model: root.rows
            spacing: 1
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true; visible: size < 1 }
            delegate: Rectangle {
                id: exportFlavourRow
                required property var modelData
                width: flavourRows.width
                height: Math.max(74, exportRow.implicitHeight + 20)
                color: modelData.selected
                       ? Qt.rgba(Material.accentColor.r, Material.accentColor.g,
                                 Material.accentColor.b, 0.12)
                       : "transparent"

                RowLayout {
                    id: exportRow
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    anchors.rightMargin: 20
                    spacing: 8
                    CheckBox {
                        checked: exportFlavourRow.modelData.selected
                        onClicked: root.setRow(exportFlavourRow.modelData.id, { selected: checked })
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Label {
                            text: exportFlavourRow.modelData.name + " (" + exportFlavourRow.modelData.format.toUpperCase() + ")"
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        Label {
                            text: root.rowSummary(exportFlavourRow.modelData)
                            font.pixelSize: 11
                            opacity: 0.7
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                    ComboBox {
                        objectName: "derivativeExportMetadataOverride"
                        Layout.preferredWidth: 180
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
        ScrollView {
            id: previewScroll
            Layout.fillWidth: true
            Layout.preferredHeight: 110
            clip: true
            ScrollBar.vertical.policy: ScrollBar.AsNeeded
            ScrollBar.vertical.visible: previewScroll.ScrollBar.vertical.size < 1
            ScrollBar.vertical.active: true
            ScrollBar.horizontal.policy: ScrollBar.AsNeeded
            ScrollBar.horizontal.visible: previewScroll.ScrollBar.horizontal.size < 1
            ScrollBar.horizontal.active: true
            TextArea {
                objectName: "derivativeExportPreview"
                readOnly: true
                wrapMode: TextEdit.NoWrap
                text: root.previewText()
            }
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