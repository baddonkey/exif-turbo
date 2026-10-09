import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Drawer {
    id: drawer
    objectName: "taggingDrawer"
    edge: Qt.RightEdge
    width: Math.min(420, parent ? parent.width : 420)
    height: parent ? parent.height : 700
    modal: false
    dim: false
    closePolicy: Popup.CloseOnEscape
    padding: 0

    required property var appController
    required property var appSettings
    property string selectedFilename: ""
    property bool browseMode: false
    property bool showFreeTagSuggestions: false
    readonly property bool hasSelection: appController && appController.currentResultRow >= 0
    readonly property bool locallyBusy: appController && appController.isTaggingBulk

    onBrowseModeChanged: copyTarget.currentIndex = 0

    Dialog {
        id: replaceTagsDialog
        objectName: "replaceTagsDialog"
        property string targetScope: ""
        title: qsTr("Replace tags on target images?")
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        anchors.centerIn: parent
        onAccepted: appController.copySelectedTags(targetScope, "replace")

        Label {
            width: Math.min(340, replaceTagsDialog.availableWidth)
            text: qsTr("All custom tags on each target image will be replaced. This cannot be undone.")
            wrapMode: Text.WordWrap
        }
    }

    function openTaggingPanel() {
        open()
        if (appController && appController.freeTaggingAvailable)
            appController.searchFreeTags("")
    }

    onClosed: showFreeTagSuggestions = false

    function addFreeTag(label) {
        var normalized = label.trim()
        if (!normalized || !drawer.hasSelection)
            return
        appController.addSelectedFreeTag(normalized)
        freeTagField.clear()
        showFreeTagSuggestions = false
    }

    Connections {
        target: appController
        function onCurrentResultRowChanged() {
            if (drawer.opened && drawer.showFreeTagSuggestions)
                appController.searchFreeTags(freeTagField.text)
        }
    }

    background: Rectangle {
        color: Material.background
        border.color: Material.dividerColor
        border.width: 1
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            color: Qt.rgba(Material.accentColor.r, Material.accentColor.g, Material.accentColor.b, 0.09)

            RowLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 6 }
                spacing: 8

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Label {
                        text: qsTr("TAGGING")
                        color: Material.accent
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: drawer.hasSelection && drawer.selectedFilename
                            ? drawer.selectedFilename
                            : qsTr("No image selected")
                        elide: Text.ElideMiddle
                        font.pixelSize: 11
                        opacity: 0.65
                    }
                }

                ToolButton {
                    objectName: "taggingDrawerCloseButton"
                    text: "\u2715"
                    implicitWidth: 36; implicitHeight: 36
                    onClicked: drawer.close()
                    ToolTip.text: qsTr("Close tagging")
                    ToolTip.visible: hovered
                }
            }
        }

        ScrollView {
            objectName: "taggingScrollView"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: parent.width
                spacing: 0

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.margins: 14
                    spacing: 6
                    visible: drawer.hasSelection

                    Label {
                        text: qsTr("Existing image tags")
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    Switch {
                        objectName: "excludeAllEmbeddedTagsSwitch"
                        Layout.fillWidth: true
                        visible: embeddedTags.count > 0
                        text: qsTr("Ignore all existing tags")
                        checked: appController ? appController.excludeAllEmbeddedTags : false
                        onToggled: appController.setExcludeAllSelectedEmbeddedTags(checked)
                    }
                    Label {
                        visible: embeddedTags.count === 0
                        text: qsTr("No embedded tags found.")
                        font.pixelSize: 11
                        opacity: 0.55
                    }
                    ListView {
                        id: embeddedTags
                        objectName: "embeddedTags"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(contentHeight, 120)
                        visible: count > 0
                        clip: true
                        interactive: contentHeight > height
                        model: appController ? appController.embeddedTagsModel : null
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: ItemDelegate {
                            required property string label
                            required property bool excluded
                            readonly property bool effectivelyExcluded: excluded
                                || appController.excludeAllEmbeddedTags
                            width: embeddedTags.width
                            height: 34
                            highlighted: effectivelyExcluded
                            enabled: !appController.excludeAllEmbeddedTags
                            onClicked: appController.setSelectedEmbeddedTagExcluded(
                                label, !excluded
                            )
                            contentItem: Label {
                                text: label
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12
                                font.strikeout: effectivelyExcluded
                                opacity: effectivelyExcluded ? 0.55 : 0.85
                            }
                        }
                    }
                }

                Rectangle {
                    visible: drawer.hasSelection
                    Layout.fillWidth: true
                    height: 1
                    color: Material.dividerColor
                }

                ColumnLayout {
                    visible: appController && !appController.taggingEnabled
                    Layout.fillWidth: true
                    Layout.margins: 18
                    spacing: 10
                    Label { text: qsTr("Tagging is disabled for this database."); wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Button {
                        text: qsTr("Enable Tagging")
                        highlighted: true
                        onClicked: appController.setTaggingEnabled(true)
                    }
                }

                ColumnLayout {
                    visible: appController && appController.freeTaggingAvailable
                    Layout.fillWidth: true
                    Layout.margins: 14
                    spacing: 8

                    Label {
                        text: qsTr("Custom tags")
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        TextField {
                            id: freeTagField
                            objectName: "freeTagField"
                            Layout.fillWidth: true
                            placeholderText: qsTr("Add or find a custom tag")
                            enabled: drawer.hasSelection
                            onTextEdited: {
                                drawer.showFreeTagSuggestions = true
                                freeTagSearchTimer.restart()
                            }
                            onActiveFocusChanged: {
                                drawer.showFreeTagSuggestions = activeFocus
                                if (activeFocus)
                                    appController.searchFreeTags(text)
                            }
                            Keys.onReturnPressed: drawer.addFreeTag(text)
                        }
                        Button {
                            objectName: "addFreeTagButton"
                            text: qsTr("Add")
                            enabled: drawer.hasSelection && freeTagField.text.trim().length > 0
                            onClicked: drawer.addFreeTag(freeTagField.text)
                        }
                    }

                    Timer {
                        id: freeTagSearchTimer
                        interval: 200
                        repeat: false
                        onTriggered: appController.searchFreeTags(freeTagField.text)
                    }

                    Label {
                        visible: drawer.showFreeTagSuggestions && freeTagSuggestions.count > 0
                        text: qsTr("Remembered tags")
                        font.pixelSize: 10
                        opacity: 0.6
                    }
                    ListView {
                        id: freeTagSuggestions
                        objectName: "freeTagSuggestions"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(contentHeight, 120)
                        visible: drawer.showFreeTagSuggestions && count > 0
                        clip: true
                        model: appController ? appController.freeTagSuggestionsModel : null
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: ItemDelegate {
                            required property string label
                            width: freeTagSuggestions.width
                            height: 34
                            text: label
                            onPressed: drawer.addFreeTag(label)
                        }
                    }

                    Label {
                        visible: drawer.hasSelection && currentFreeTags.count === 0
                        text: qsTr("This image has no custom tags yet.")
                        opacity: 0.55
                        font.pixelSize: 11
                    }
                    ListView {
                        id: currentFreeTags
                        objectName: "currentFreeTags"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(contentHeight, 132)
                        visible: drawer.hasSelection && count > 0
                        clip: true
                        model: appController ? appController.freeTagsModel : null
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Item {
                            required property string label
                            width: currentFreeTags.width
                            height: 36
                            Label {
                                anchors.left: parent.left
                                anchors.right: removeFreeTagButton.left
                                anchors.rightMargin: 7
                                anchors.verticalCenter: parent.verticalCenter
                                text: label
                                elide: Text.ElideRight
                                font.pixelSize: 12
                            }
                            ToolButton {
                                id: removeFreeTagButton
                                objectName: "removeFreeTagButton"
                                anchors.right: parent.right
                                anchors.rightMargin: 20
                                anchors.verticalCenter: parent.verticalCenter
                                width: 36
                                height: 36
                                text: "\u2212"
                                hoverEnabled: true
                                onClicked: appController.removeSelectedFreeTag(label)
                                Accessible.name: qsTr("Remove custom tag from selected image")
                                contentItem: Label {
                                    text: "\u2212"
                                    font.pixelSize: 18
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle {
                                    radius: 4
                                    color: removeTagMouseArea.containsMouse
                                        ? Qt.rgba(Material.foreground.r, Material.foreground.g,
                                                  Material.foreground.b, 0.12)
                                        : "transparent"
                                }
                                MouseArea {
                                    id: removeTagMouseArea
                                    objectName: "removeTagMouseArea"
                                    anchors.fill: parent
                                    z: 1
                                    hoverEnabled: true
                                    acceptedButtons: Qt.LeftButton
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: appController.removeSelectedFreeTag(label)
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    visible: appController && appController.freeTaggingAvailable
                    Layout.fillWidth: true
                    height: 1
                    color: Material.dividerColor
                }

                ColumnLayout {
                    visible: appController && appController.freeTaggingAvailable
                    Layout.fillWidth: true
                    spacing: 0

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 8

                        Label {
                            text: qsTr("Copy tags to other images")
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Copies accepted and custom tags. The current image is excluded.")
                            wrapMode: Text.WordWrap
                            font.pixelSize: 10
                            opacity: 0.55
                        }
                        ComboBox {
                            id: copyTarget
                            objectName: "copyTagsTarget"
                            Layout.fillWidth: true
                            currentIndex: 0
                            textRole: "text"
                            valueRole: "value"
                            model: drawer.browseMode
                                ? [
                                    { text: qsTr("Marked images (%1)").arg(appController.checkedCount), value: "marked" },
                                    { text: qsTr("Current folder (%1)").arg(appController.totalResults), value: "folder" }
                                ]
                                : [
                                    { text: qsTr("Marked images (%1)").arg(appController.checkedCount), value: "marked" },
                                    { text: qsTr("Current search results (%1)").arg(appController.totalResults), value: "results" }
                                ]
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14
                            ButtonGroup { id: copyModeGroup }
                            RadioButton {
                                id: copyAddMode
                                objectName: "copyTagsAddMode"
                                text: qsTr("Add")
                                checked: true
                                ButtonGroup.group: copyModeGroup
                                ToolTip.text: qsTr("Keep target tags and add missing source tags")
                                ToolTip.visible: hovered
                            }
                            RadioButton {
                                id: copyReplaceMode
                                objectName: "copyTagsReplaceMode"
                                text: qsTr("Replace")
                                ButtonGroup.group: copyModeGroup
                                ToolTip.text: qsTr("Remove target tags before copying source tags")
                                ToolTip.visible: hovered
                            }
                            Item { Layout.fillWidth: true }
                        }
                        Button {
                            objectName: "copyTagsButton"
                            Layout.fillWidth: true
                            text: qsTr("Copy Tags")
                            highlighted: true
                            enabled: drawer.hasSelection && !drawer.locallyBusy
                            onClicked: {
                                if (copyReplaceMode.checked) {
                                    replaceTagsDialog.targetScope = copyTarget.currentValue
                                    replaceTagsDialog.open()
                                } else {
                                    appController.copySelectedTags(copyTarget.currentValue, "add")
                                }
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: appController.taggingBulkSummary !== ""
                            text: appController.taggingBulkSummary
                            wrapMode: Text.WordWrap
                            font.pixelSize: 10
                            opacity: 0.7
                        }
                    }
                }

                ColumnLayout {
                    visible: drawer.locallyBusy
                    Layout.fillWidth: true
                    Layout.margins: 14
                    spacing: 7
                    ProgressBar {
                        Layout.fillWidth: true
                        from: 0
                        to: Math.max(1, appController.taggingBulkTotal)
                        value: appController.taggingBulkCurrent
                        indeterminate: to <= 1
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Copying tags")
                            font.pixelSize: 11
                        }
                        Button {
                            text: qsTr("Cancel")
                            onClicked: appController.cancelBulkTagging()
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 14; Layout.rightMargin: 14; Layout.bottomMargin: 10
                    visible: appController && appController.selectedTaggingError !== ""
                    text: appController.selectedTaggingError
                    color: Material.color(Material.Red)
                    wrapMode: Text.WordWrap
                    font.pixelSize: 11
                }
            }
        }

        Rectangle {
            objectName: "derivativeTagsFooter"
            Layout.fillWidth: true
            Layout.preferredHeight: 132
            color: Qt.rgba(Material.accentColor.r, Material.accentColor.g,
                           Material.accentColor.b, 0.07)

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                anchors.topMargin: 9
                anchors.bottomMargin: 9
                spacing: 3

                Label {
                    text: qsTr("Final derivative tags")
                    color: Material.accent
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
                Label {
                    text: qsTr("XMP Subject / IPTC Keywords")
                    font.pixelSize: 9
                    opacity: 0.55
                }
                Label {
                    Layout.fillWidth: true
                    visible: !drawer.hasSelection
                    text: qsTr("No image selected")
                    font.pixelSize: 11
                    opacity: 0.55
                }
                Label {
                    Layout.fillWidth: true
                    visible: drawer.hasSelection && finalDerivativeTags.count === 0
                    text: qsTr("No tags would be written to a derivative.")
                    font.pixelSize: 11
                    opacity: 0.55
                }
                ListView {
                    id: finalDerivativeTags
                    objectName: "finalDerivativeTags"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: drawer.hasSelection && count > 0
                    clip: true
                    model: appController ? appController.derivativeTagsModel : null
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: Label {
                        required property string label
                        width: finalDerivativeTags.width
                        height: 22
                        text: label
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                        font.pixelSize: 11
                    }
                }
            }
        }
    }
}