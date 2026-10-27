pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Item {
    id: root
    objectName: "derivativeExportPage"

    property var appSettings
    property var flavours: []
    property string selectedFlavourId: ""
    readonly property var selectedFlavour: {
        for (var index = 0; index < flavours.length; index++) {
            if (flavours[index].id === selectedFlavourId)
                return flavours[index]
        }
        return null
    }

    function reloadFlavours() {
        if (!appSettings)
            return
        try {
            flavours = JSON.parse(appSettings.derivativeExportFlavoursJson)
        } catch (error) {
            flavours = []
        }
        if (!selectedFlavour || !flavours.some(function(item) {
                return item.id === selectedFlavourId
            })) {
            selectedFlavourId = flavours.length ? flavours[0].id : ""
        }
    }

    function saveFlavours(nextFlavours) {
        flavours = nextFlavours
        if (appSettings)
            appSettings.setDerivativeExportFlavours(JSON.stringify(nextFlavours))
    }

    function updateFlavour(flavourId, changes) {
        var next = flavours.slice()
        for (var index = 0; index < next.length; index++) {
            if (next[index].id !== flavourId)
                continue
            var updated = Object.assign({}, next[index])
            for (var key in changes)
                updated[key] = changes[key]
            next[index] = updated
            saveFlavours(next)
            return
        }
    }

    function updateSelected(changes) {
        if (selectedFlavour)
            updateFlavour(selectedFlavour.id, changes)
    }

    function formatIndex(value) {
        return ["original", "jpeg", "png", "tiff"].indexOf(value)
    }

    function metadataIndex(value) {
        return ["none", "original", "custom"].indexOf(value)
    }

    function resizeIndex(value) {
        return ["original_pixels", "longest_edge", "width", "height"].indexOf(value)
    }

    function addFlavour() {
        var id = "custom-" + Date.now() + "-" + Math.floor(Math.random() * 1000000)
        var next = flavours.slice()
        next.push({
            id: id,
            name: qsTr("New flavour"),
            format: "jpeg",
            suffix: "_new",
            selected_by_default: false,
            metadata_mode: "custom",
            resize_mode: "original_pixels",
            pixel_limit: null,
            no_upscale: true,
            dpi: null,
            jpeg_quality: 85,
            png_compression: 6,
            tiff_compression: "lzw"
        })
        selectedFlavourId = id
        saveFlavours(next)
    }

    function addDefaultFlavours() {
        if (!appSettings)
            return
        var defaults = JSON.parse(appSettings.defaultDerivativeExportFlavoursJson)
        var next = flavours.slice()
        for (var index = 0; index < defaults.length; index++) {
            var exists = next.some(function(item) {
                return item.id === defaults[index].id
            })
            if (!exists)
                next.push(defaults[index])
        }
        saveFlavours(next)
    }

    function duplicateSelected() {
        if (!selectedFlavour)
            return
        var copy = Object.assign({}, selectedFlavour)
        copy.id = "custom-" + Date.now() + "-" + Math.floor(Math.random() * 1000000)
        var baseName = selectedFlavour.name + qsTr(" Copy")
        var candidateName = baseName
        var attempt = 2
        while (flavours.some(function(item) { return item.name === candidateName })) {
            candidateName = baseName + " " + attempt
            attempt++
        }
        copy.name = candidateName
        var baseSuffix = selectedFlavour.suffix.substring(0, 35) + "_copy"
        var candidateSuffix = baseSuffix
        attempt = 2
        while (flavours.some(function(item) { return item.suffix === candidateSuffix })) {
            var suffixTail = "_" + attempt
            candidateSuffix = baseSuffix.substring(0, 40 - suffixTail.length) + suffixTail
            attempt++
        }
        copy.suffix = candidateSuffix
        var next = flavours.slice()
        next.splice(flavours.indexOf(selectedFlavour), 0, copy)
        selectedFlavourId = copy.id
        saveFlavours(next)
    }

    function moveSelected(offset) {
        if (!selectedFlavour)
            return
        var from = flavours.indexOf(selectedFlavour)
        var to = from + offset
        if (to < 0 || to >= flavours.length)
            return
        var next = flavours.slice()
        var item = next.splice(from, 1)[0]
        next.splice(to, 0, item)
        saveFlavours(next)
    }

    function deleteSelected() {
        if (!selectedFlavour)
            return
        var next = flavours.filter(function(item) {
            return item.id !== selectedFlavourId
        })
        selectedFlavourId = next.length ? next[Math.min(flavours.indexOf(selectedFlavour), next.length - 1)].id : ""
        saveFlavours(next)
    }

    Component.onCompleted: reloadFlavours()

    Connections {
        target: root.appSettings
        function onDerivativeExportSettingsChanged() { root.reloadFlavours() }
    }

    Dialog {
        id: deleteDialog
        objectName: "deleteDerivativeFlavourDialog"
        title: qsTr("Delete flavour")
        modal: true
        standardButtons: Dialog.Cancel | Dialog.Yes
        anchors.centerIn: Overlay.overlay
        Label {
            text: qsTr("Delete this export flavour?")
            wrapMode: Text.WordWrap
        }
        onAccepted: root.deleteSelected()
    }

    ScrollView {
        id: pageScroll
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ScrollBar.vertical.policy: ScrollBar.AsNeeded
        ScrollBar.vertical.visible: pageScroll.ScrollBar.vertical.size < 1
        ScrollBar.vertical.active: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            width: pageScroll.availableWidth
            height: Math.max(implicitHeight, pageScroll.availableHeight)
            spacing: 12

            ColumnLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.topMargin: 18
                spacing: 3

                Label {
                    text: qsTr("Derivative Export")
                    font.pixelSize: 24
                    font.weight: Font.DemiBold
                }
                Label {
                    text: qsTr("Define export flavours for generating derivative images.")
                    opacity: 0.7
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            GridLayout {
                id: editorGrid
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.bottomMargin: 20
                columns: root.width >= 1100 ? 2 : 1
                columnSpacing: 16
                rowSpacing: 12

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 360
                    Layout.preferredHeight: editorGrid.columns === 2 ? 360 : 460
                    color: "transparent"
                    border.color: Material.dividerColor
                    radius: 4

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 8

                        Flow {
                            Layout.fillWidth: true
                            Layout.preferredHeight: implicitHeight
                            spacing: 4
                            Button { text: qsTr("Add"); onClicked: root.addFlavour() }
                            Button {
                                objectName: "duplicateDerivativeFlavourButton"
                                text: qsTr("Duplicate")
                                enabled: root.selectedFlavour !== null
                                onClicked: root.duplicateSelected()
                            }
                            Button {
                                text: qsTr("Delete")
                                enabled: root.selectedFlavour !== null
                                onClicked: deleteDialog.open()
                            }
                            ToolButton {
                                text: qsTr("Move up")
                                enabled: root.selectedFlavour !== null
                                         && root.flavours.indexOf(root.selectedFlavour) > 0
                                onClicked: root.moveSelected(-1)
                                ToolTip.text: qsTr("Move up")
                                ToolTip.visible: hovered
                            }
                            ToolButton {
                                text: qsTr("Move down")
                                enabled: root.selectedFlavour !== null
                                         && root.flavours.indexOf(root.selectedFlavour) < root.flavours.length - 1
                                onClicked: root.moveSelected(1)
                                ToolTip.text: qsTr("Move down")
                                ToolTip.visible: hovered
                            }
                            Button {
                                text: qsTr("Add Default Flavours…")
                                onClicked: root.addDefaultFlavours()
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Label { text: qsTr("Name"); Layout.fillWidth: true }
                            Label { text: qsTr("Format"); Layout.preferredWidth: 78 }
                        }

                        ListView {
                            id: flavourList
                            objectName: "derivativeFlavourList"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: root.flavours
                            spacing: 1
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true; visible: size < 1 }

                            delegate: Rectangle {
                                id: flavourDelegate
                                required property var modelData
                                required property int index
                                width: flavourList.width
                                height: Math.max(58, presetRow.implicitHeight + 16)
                                color: flavourDelegate.modelData.id === root.selectedFlavourId
                                       ? Qt.rgba(root.Material.accentColor.r,
                                                 root.Material.accentColor.g,
                                                 root.Material.accentColor.b, 0.24)
                                    : (flavourDelegate.index % 2 ? Qt.rgba(1, 1, 1, 0.025) : "transparent")

                                MouseArea {
                                    anchors.fill: parent
                                    z: 0
                                    onClicked: root.selectedFlavourId = flavourDelegate.modelData.id
                                }
                                RowLayout {
                                    id: presetRow
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 20
                                    spacing: 8
                                    z: 1
                                    CheckBox {
                                        checked: flavourDelegate.modelData.selected_by_default
                                        onClicked: root.updateFlavour(flavourDelegate.modelData.id,
                                                                      { selected_by_default: checked })
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Label {
                                            text: flavourDelegate.modelData.name
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                        Label {
                                              text: flavourDelegate.modelData.resize_mode === "original_pixels"
                                                  ? qsTr("Original size · Metadata: %1").arg(flavourDelegate.modelData.metadata_mode)
                                                  : qsTr("%1 px · Metadata: %2").arg(flavourDelegate.modelData.pixel_limit).arg(flavourDelegate.modelData.metadata_mode)
                                            font.pixelSize: 11
                                            opacity: 0.65
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                    }
                                    Label {
                                        text: flavourDelegate.modelData.format.toUpperCase()
                                        Layout.preferredWidth: 78
                                        opacity: 0.8
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    objectName: "derivativeSettingsPanel"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 360
                    Layout.preferredHeight: editorGrid.columns === 2 ? 360 : 640
                    color: "transparent"
                    border.color: Material.dividerColor
                    radius: 4

                    ScrollView {
                        id: settingsScroll
                        objectName: "derivativeSettingsScroll"
                        anchors.fill: parent
                        anchors.margins: 14
                        clip: true
                        rightPadding: effectiveScrollBarWidth + 8
                        contentWidth: availableWidth
                        contentHeight: settingsColumn.implicitHeight
                        ScrollBar.vertical.policy: ScrollBar.AsNeeded
                        ScrollBar.vertical.visible: settingsScroll.ScrollBar.vertical.size < 1
                        ScrollBar.vertical.active: true
                        ScrollBar.vertical.objectName: "derivativeSettingsScrollbar"
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        ColumnLayout {
                            id: settingsColumn
                            width: settingsScroll.availableWidth
                            spacing: 12

                            Label {
                                text: qsTr("Flavour Settings")
                                font.pixelSize: 16
                                font.weight: Font.DemiBold
                            }

                            GridLayout {
                                columns: settingsScroll.availableWidth >= 460 ? 2 : 1
                                columnSpacing: 12
                                rowSpacing: 10
                                Layout.fillWidth: true

                                Label { text: qsTr("Name:"); Layout.fillWidth: true; wrapMode: Text.Wrap }
                                TextField {
                                    objectName: "derivativeFlavourNameField"
                                    Layout.fillWidth: true
                                    enabled: root.selectedFlavour !== null
                                    text: root.selectedFlavour ? root.selectedFlavour.name : ""
                                    onEditingFinished: root.updateSelected({ name: text.trim() })
                                }

                                Label { text: qsTr("Output filename suffix:"); Layout.fillWidth: true; Layout.maximumWidth: 200; wrapMode: Text.Wrap }
                                TextField {
                                    objectName: "derivativeFlavourSuffixField"
                                    Layout.fillWidth: true
                                    enabled: root.selectedFlavour !== null
                                    text: root.selectedFlavour ? root.selectedFlavour.suffix : ""
                                    onEditingFinished: root.updateSelected({ suffix: text })
                                }

                                Label { text: qsTr("Format:") }
                                ComboBox {
                                    objectName: "derivativeFlavourFormatCombo"
                                    Layout.fillWidth: true
                                    enabled: root.selectedFlavour !== null
                                    model: [qsTr("Original (as is)"), "JPEG", "PNG", "TIFF"]
                                    currentIndex: root.selectedFlavour
                                                  ? root.formatIndex(root.selectedFlavour.format) : 0
                                    onActivated: root.updateSelected({
                                        format: ["original", "jpeg", "png", "tiff"][currentIndex],
                                        metadata_mode: currentIndex === 0 ? "original"
                                                                         : (root.selectedFlavour.metadata_mode === "original" ? "original" : "custom"),
                                        resize_mode: currentIndex === 0 ? "original_pixels" : root.selectedFlavour.resize_mode,
                                        pixel_limit: currentIndex === 0 ? null : root.selectedFlavour.pixel_limit,
                                        dpi: currentIndex === 0 ? null : root.selectedFlavour.dpi
                                    })
                                }

                                Label { text: qsTr("Selected by default in export dialog"); Layout.fillWidth: true; Layout.maximumWidth: 200; wrapMode: Text.Wrap }
                                CheckBox {
                                    objectName: "derivativeFlavourDefaultCheck"
                                    enabled: root.selectedFlavour !== null
                                    checked: root.selectedFlavour ? root.selectedFlavour.selected_by_default : false
                                    onClicked: root.updateSelected({ selected_by_default: checked })
                                }
                            }

                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Material.dividerColor }

                            Label {
                                text: root.selectedFlavour && root.selectedFlavour.format === "original"
                                      ? qsTr("Original Export Options") : qsTr("Conversion Options")
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }

                            Label {
                                visible: root.selectedFlavour && root.selectedFlavour.format === "original"
                                text: qsTr("The original file is copied byte-for-byte. Its metadata, format, resolution and profile are unchanged.")
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                                opacity: 0.75
                            }

                            GridLayout {
                                visible: root.selectedFlavour && root.selectedFlavour.format !== "original"
                                columns: settingsScroll.availableWidth >= 460 ? 2 : 1
                                columnSpacing: 12
                                rowSpacing: 10
                                Layout.fillWidth: true

                                Label { text: qsTr("Resize:") }
                                ComboBox {
                                    objectName: "derivativeFlavourResizeCombo"
                                    Layout.fillWidth: true
                                    model: [qsTr("Original pixels"), qsTr("Limit longest edge"), qsTr("Limit width"), qsTr("Limit height")]
                                    currentIndex: root.selectedFlavour
                                                  ? root.resizeIndex(root.selectedFlavour.resize_mode) : 0
                                    onActivated: {
                                        var modes = ["original_pixels", "longest_edge", "width", "height"]
                                        var changes = { resize_mode: modes[currentIndex] }
                                        if (currentIndex === 0)
                                            changes.pixel_limit = null
                                        else if (!root.selectedFlavour.pixel_limit)
                                            changes.pixel_limit = 2048
                                        root.updateSelected(changes)
                                    }
                                }

                                Label { text: qsTr("Pixel limit:"); visible: root.selectedFlavour && root.selectedFlavour.resize_mode !== "original_pixels" }
                                SpinBox {
                                    objectName: "derivativeFlavourPixelLimit"
                                    visible: root.selectedFlavour && root.selectedFlavour.resize_mode !== "original_pixels"
                                    from: 1
                                    to: 100000
                                    editable: true
                                    value: root.selectedFlavour && root.selectedFlavour.pixel_limit
                                           ? root.selectedFlavour.pixel_limit : 2048
                                    onValueModified: root.updateSelected({ pixel_limit: value })
                                }

                                Label { text: qsTr("Do not upscale") }
                                CheckBox {
                                    checked: root.selectedFlavour ? root.selectedFlavour.no_upscale : true
                                    onClicked: root.updateSelected({ no_upscale: checked })
                                }

                                Label { text: qsTr("JPEG quality:"); visible: root.selectedFlavour && root.selectedFlavour.format === "jpeg" }
                                SpinBox {
                                    visible: root.selectedFlavour && root.selectedFlavour.format === "jpeg"
                                    from: 1; to: 100
                                    value: root.selectedFlavour ? root.selectedFlavour.jpeg_quality : 85
                                    onValueModified: root.updateSelected({ jpeg_quality: value })
                                }

                                Label { text: qsTr("PNG compression:"); visible: root.selectedFlavour && root.selectedFlavour.format === "png" }
                                SpinBox {
                                    visible: root.selectedFlavour && root.selectedFlavour.format === "png"
                                    from: 0; to: 9
                                    value: root.selectedFlavour ? root.selectedFlavour.png_compression : 6
                                    onValueModified: root.updateSelected({ png_compression: value })
                                }

                                Label { text: qsTr("TIFF compression:"); visible: root.selectedFlavour && root.selectedFlavour.format === "tiff" }
                                ComboBox {
                                    visible: root.selectedFlavour && root.selectedFlavour.format === "tiff"
                                    model: [qsTr("None"), "LZW", "ZIP (Deflate)"]
                                    currentIndex: root.selectedFlavour
                                                  ? ["none", "lzw", "zip"].indexOf(root.selectedFlavour.tiff_compression) : 1
                                    onActivated: root.updateSelected({
                                        tiff_compression: ["none", "lzw", "zip"][currentIndex]
                                    })
                                }
                            }

                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Material.dividerColor }

                            Label { text: qsTr("Metadata"); font.pixelSize: 14; font.weight: Font.DemiBold }
                            ComboBox {
                                objectName: "derivativeFlavourMetadataCombo"
                                Layout.fillWidth: true
                                enabled: root.selectedFlavour && root.selectedFlavour.format !== "original"
                                model: [qsTr("None"), qsTr("Original"), qsTr("Custom")]
                                currentIndex: root.selectedFlavour
                                              ? root.metadataIndex(root.selectedFlavour.metadata_mode) : 1
                                onActivated: root.updateSelected({
                                    metadata_mode: ["none", "original", "custom"][currentIndex]
                                })
                            }

                            Label {
                                visible: root.selectedFlavour && root.selectedFlavour.format === "original"
                                text: qsTr("For the original export, metadata is always preserved and cannot be changed.")
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                                opacity: 0.7
                            }

                            GridLayout {
                                columns: settingsScroll.availableWidth >= 460 ? 2 : 1
                                columnSpacing: 12
                                Layout.fillWidth: true
                                Label {
                                    text: qsTr("Output resolution (DPI):")
                                    visible: root.selectedFlavour && root.selectedFlavour.format !== "original"
                                }
                                SpinBox {
                                    objectName: "derivativeFlavourDpi"
                                    visible: root.selectedFlavour && root.selectedFlavour.format !== "original"
                                    from: 0; to: 9600
                                    editable: true
                                    enabled: root.selectedFlavour
                                             && root.selectedFlavour.format !== "original"
                                             && root.selectedFlavour.metadata_mode !== "none"
                                    value: root.selectedFlavour && root.selectedFlavour.dpi
                                           ? root.selectedFlavour.dpi : 0
                                    textFromValue: function(value) {
                                        return value === 0 ? qsTr("Source") : value + " DPI"
                                    }
                                    valueFromText: function(text) {
                                        var parsed = parseInt(text)
                                        return isNaN(parsed) ? 0 : parsed
                                    }
                                    onValueModified: root.updateSelected({ dpi: value === 0 ? null : value })
                                }
                            }

                            Label {
                                visible: root.appSettings && root.appSettings.derivativeExportSaveError !== ""
                                text: root.appSettings ? root.appSettings.derivativeExportSaveError : ""
                                color: Material.theme === Material.Dark ? "#ef9a9a" : "#c62828"
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
        }
    }
}