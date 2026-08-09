import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

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
    readonly property bool hasSelection: appController && appController.currentResultRow >= 0
    readonly property int markedCount: appController ? appController.markedTagImageCount : 0
    readonly property int taggedMarkedCount: appController ? appController.markedTaggedImageCount : 0
    readonly property bool markedMode: taggingScope.currentIndex === 1
    onMarkedCountChanged: {
        if (markedCount === 0)
            taggingScope.currentIndex = 0
    }
    readonly property bool locallyBusy: appController && (
        appController.isTgmUpdating
        || appController.isGeneratingTagProposals
        || appController.isTaggingBulk
        || appController.isExportingDerivatives)

    function openAndFocus() {
        open()
        if (appController && appController.taggingAvailable)
            Qt.callLater(function() { tgmSearchField.forceActiveFocus() })
    }

    function applyCurrentSearchResult() {
        if (!appController || tgmResults.count === 0)
            return
        var item = tgmResults.itemAtIndex(Math.max(0, tgmResults.currentIndex))
        if (!item)
            item = tgmResults.itemAtIndex(0)
        if (!item)
            return
        if (markedMode)
            appController.applyConceptToMarked(item.conceptReference)
        else
            appController.addSelectedTgmConcept(item.conceptReference)
    }

    FolderDialog {
        id: derivativeFolderDialog
        title: qsTr("Choose derivative output folder")
        onAccepted: {
            derivativeConfirmDialog.outputUrl = selectedFolder.toString()
            derivativeConfirmDialog.open()
        }
    }

    Dialog {
        id: derivativeConfirmDialog
        property string outputUrl: ""
        title: qsTr("Generate Tagged Derivatives")
        modal: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(440, drawer.width - 24)
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: drawer.appController.generateDerivativesForMarked(outputUrl)

        Label {
            width: parent.width
            wrapMode: Text.WordWrap
            text: qsTr("Images selected for export: %1. Marked images without accepted tags: %2. Source formats and relative folders are preserved. Originals remain unchanged.")
                .arg(drawer.taggedMarkedCount)
                .arg(drawer.markedCount - drawer.taggedMarkedCount)
        }
    }

    Dialog {
        id: autoAcceptConfirmDialog
        title: qsTr("Auto-accept Tag Proposals")
        modal: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(420, drawer.width - 24)
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: drawer.appController.autoAcceptMarkedTagProposals()

        Label {
            width: parent.width
            wrapMode: Text.WordWrap
            text: qsTr("Generate and accept proposals scoring at least %1% for %2 marked image(s)?")
                .arg(Math.round(drawer.appSettings.autoAcceptThreshold * 100))
                .arg(drawer.markedCount)
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
                    visible: appController && appController.taggingEnabled && !appController.tgmInstalled
                    Layout.fillWidth: true
                    Layout.margins: 18
                    spacing: 10
                    Label { text: qsTr("Install TGM to search and apply controlled terms."); wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Button {
                        text: qsTr("Install TGM")
                        highlighted: true
                        enabled: !appController.isTgmUpdating
                        onClicked: appController.installOrUpdateTgm()
                    }
                }

                ColumnLayout {
                    visible: appController && appController.taggingAvailable
                    Layout.fillWidth: true
                    spacing: 0

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 6

                        Label {
                            text: qsTr("Tag")
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }
                        TabBar {
                            id: taggingScope
                            objectName: "taggingScope"
                            Layout.fillWidth: true
                            currentIndex: 0
                            TabButton {
                                objectName: "tagCurrentImageButton"
                                text: qsTr("Current image")
                            }
                            TabButton {
                                objectName: "tagMarkedImagesButton"
                                text: qsTr("Marked images (%1)").arg(drawer.markedCount)
                                enabled: drawer.markedCount > 0
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: drawer.markedMode
                                ? qsTr("Changes apply to every marked image.")
                                : qsTr("Changes apply only to %1.").arg(drawer.selectedFilename || qsTr("the current image"))
                            wrapMode: Text.WordWrap
                            font.pixelSize: 11
                            opacity: 0.65
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 8

                        Label { text: qsTr("Add a TGM term"); font.pixelSize: 13; font.weight: Font.DemiBold }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            TextField {
                                id: tgmSearchField
                                objectName: "tgmSearchField"
                                Layout.fillWidth: true
                                placeholderText: qsTr("Search terms and aliases")
                                enabled: !appController.isTaggingBulk
                                onTextChanged: tgmSearchTimer.restart()
                                Keys.onReturnPressed: drawer.applyCurrentSearchResult()
                                Keys.onDownPressed: {
                                    if (tgmResults.count > 0) {
                                        tgmResults.currentIndex = Math.min(tgmResults.count - 1, tgmResults.currentIndex + 1)
                                        tgmResults.forceActiveFocus()
                                    }
                                }
                            }
                            Button {
                                objectName: "addTgmTermButton"
                                text: qsTr("Add")
                                enabled: (drawer.markedMode ? drawer.markedCount > 0 : drawer.hasSelection)
                                    && tgmResults.count > 0 && !appController.isTaggingBulk
                                onClicked: drawer.applyCurrentSearchResult()
                                ToolTip.text: drawer.markedMode
                                    ? qsTr("Add to all marked images")
                                    : qsTr("Add to current image")
                                ToolTip.visible: hovered
                            }
                        }

                        Timer {
                            id: tgmSearchTimer
                            interval: 250
                            repeat: false
                            onTriggered: appController.searchTgm(tgmSearchField.text.trim())
                        }

                        ListView {
                            id: tgmResults
                            objectName: "tgmSearchResults"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(contentHeight, 180)
                            Layout.maximumHeight: 180
                            visible: count > 0
                            clip: true
                            model: appController ? appController.tgmSearchModel : null
                            currentIndex: count > 0 ? 0 : -1
                            keyNavigationWraps: true
                            Keys.onReturnPressed: drawer.applyCurrentSearchResult()
                            ScrollBar.vertical: ScrollBar {}

                            delegate: ItemDelegate {
                                required property string conceptId
                                required property string label
                                required property var categories
                                required property var aliases
                                property string conceptReference: conceptId
                                width: tgmResults.width
                                height: 48
                                highlighted: ListView.isCurrentItem
                                onClicked: {
                                    tgmResults.currentIndex = index
                                }
                                contentItem: ColumnLayout {
                                    spacing: 1
                                    Label { Layout.fillWidth: true; text: label; elide: Text.ElideRight; font.pixelSize: 12 }
                                    Label {
                                        Layout.fillWidth: true
                                        text: [categories.join(" / "), aliases.length ? aliases.join(", ") : ""].filter(Boolean).join("  |  ")
                                        elide: Text.ElideRight
                                        font.pixelSize: 10
                                        opacity: 0.55
                                    }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor }

                    ColumnLayout {
                        visible: !drawer.markedMode
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 7
                        Label { text: qsTr("Tags on current image"); font.pixelSize: 13; font.weight: Font.DemiBold }
                        Label {
                            visible: !drawer.hasSelection
                            text: qsTr("Select an image to review its tags.")
                            opacity: 0.55
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                        Label {
                            visible: drawer.hasSelection && acceptedTagsList.count === 0
                            text: qsTr("This image has no accepted tags yet.")
                            opacity: 0.55
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                        ListView {
                            id: acceptedTagsList
                            objectName: "acceptedTagsList"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(contentHeight, 168)
                            visible: drawer.hasSelection
                            interactive: contentHeight > height
                            clip: true
                            model: appController ? appController.acceptedTagsModel : null
                            delegate: RowLayout {
                                required property string conceptId
                                required property string label
                                required property string category
                                required property string method
                                required property string providerModel
                                width: acceptedTagsList.width
                                height: 36
                                spacing: 7
                                Label { Layout.fillWidth: true; text: label; elide: Text.ElideRight; font.pixelSize: 12 }
                                Label { text: category; font.pixelSize: 9; opacity: 0.5 }
                                Label { text: providerModel || method; font.pixelSize: 9; opacity: 0.5; elide: Text.ElideRight; Layout.maximumWidth: 90 }
                                ToolButton {
                                    text: "\u2212"
                                    implicitWidth: 30; implicitHeight: 30
                                    enabled: !appController.isTaggingBulk
                                    onClicked: appController.removeSelectedTgmConcept(conceptId)
                                    ToolTip.text: qsTr("Remove from selected image")
                                    ToolTip.visible: hovered
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor }

                    ColumnLayout {
                        visible: drawer.markedMode
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 7
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("Tags on marked images")
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Label { text: qsTr("%1 marked").arg(drawer.markedCount); font.pixelSize: 11; opacity: 0.6 }
                        }
                        Label { visible: drawer.markedCount === 0; text: qsTr("Mark images to use bulk tagging."); opacity: 0.55; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        ListView {
                            id: markedTagsList
                            objectName: "markedTagsList"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(contentHeight, 150)
                            visible: drawer.markedCount > 0
                            interactive: contentHeight > height
                            clip: true
                            model: appController ? appController.markedTagsModel : null
                            delegate: RowLayout {
                                required property string conceptId
                                required property string label
                                required property var categories
                                required property int count
                                required property string membership
                                width: markedTagsList.width
                                height: 36
                                spacing: 7
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    Label { Layout.fillWidth: true; text: label; elide: Text.ElideRight; font.pixelSize: 12 }
                                    Label { Layout.fillWidth: true; text: categories.join(" / "); elide: Text.ElideRight; font.pixelSize: 9; opacity: 0.5 }
                                }
                                Label {
                                    text: membership === "all"
                                        ? qsTr("All marked images")
                                        : qsTr("%1 of %2 marked images").arg(count).arg(drawer.markedCount)
                                    font.pixelSize: 10
                                    opacity: membership === "all" ? 0.8 : 0.55
                                }
                                ToolButton {
                                    text: "\u2212"
                                    implicitWidth: 30; implicitHeight: 30
                                    enabled: !appController.isTaggingBulk
                                    onClicked: appController.removeConceptFromMarked(conceptId)
                                    ToolTip.text: qsTr("Remove from marked images")
                                    ToolTip.visible: hovered
                                }
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: appController && appController.taggingBulkSummary !== ""
                            text: qsTr("Last action: %1").arg(appController.taggingBulkSummary)
                            wrapMode: Text.WordWrap
                            font.pixelSize: 11
                            opacity: 0.7
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 8
                        Label { text: qsTr("Tag proposals"); font.pixelSize: 13; font.weight: Font.DemiBold }
                        Label {
                            visible: !appController.taggingProposalAvailable
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            opacity: 0.6
                            text: !appController.aiEnabled
                                ? qsTr("Enable AI features to generate proposals.")
                                : qsTr("Build TGM vectors to generate proposals.")
                        }
                        Button {
                            visible: !appController.taggingProposalAvailable && appController.aiEnabled
                            text: qsTr("Build TGM Vectors")
                            enabled: !appController.isTgmUpdating
                            onClicked: appController.rebuildTgmVectors()
                        }
                        Button {
                            text: drawer.markedMode
                                ? qsTr("Generate for marked images")
                                : qsTr("Generate for current image")
                            enabled: (drawer.markedMode ? drawer.markedCount > 0 : drawer.hasSelection)
                                && appController.taggingProposalAvailable
                                && !appController.isGeneratingTagProposals
                            onClicked: drawer.markedMode
                                ? appController.generateMarkedTagProposals()
                                : appController.generateSelectedTagProposals()
                        }
                        ListView {
                            id: proposalsList
                            objectName: "pendingProposalsList"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(contentHeight, 190)
                            clip: true
                            model: appController ? appController.pendingProposalsModel : null
                            delegate: RowLayout {
                                required property string conceptId
                                required property string label
                                required property string category
                                required property real score
                                required property string provider
                                required property string providerFingerprint
                                width: proposalsList.width
                                height: 44
                                spacing: 6
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    Label { Layout.fillWidth: true; text: label; elide: Text.ElideRight; font.pixelSize: 12 }
                                    Label { Layout.fillWidth: true; text: category + "  |  " + provider; elide: Text.ElideRight; font.pixelSize: 9; opacity: 0.5 }
                                }
                                Label { text: Math.round(score * 100) + "%"; font.pixelSize: 11; font.weight: Font.DemiBold }
                                ToolButton {
                                    text: "\u2713"
                                    enabled: !appController.isGeneratingTagProposals
                                    onClicked: appController.acceptSelectedProposal(conceptId, providerFingerprint)
                                    ToolTip.text: qsTr("Accept proposal")
                                    ToolTip.visible: hovered
                                }
                                ToolButton {
                                    text: "\u2715"
                                    enabled: !appController.isGeneratingTagProposals
                                    onClicked: appController.rejectSelectedProposal(conceptId, providerFingerprint)
                                    ToolTip.text: qsTr("Reject proposal")
                                    ToolTip.visible: hovered
                                }
                            }
                        }
                        Button {
                            text: qsTr("Auto-accept Marked")
                            visible: drawer.markedMode && (appSettings ? appSettings.autoAcceptEnabled : false)
                            enabled: drawer.markedCount > 0 && appController.taggingProposalAvailable && !appController.isGeneratingTagProposals
                            onClicked: autoAcceptConfirmDialog.open()
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor }

                    ColumnLayout {
                        visible: drawer.markedMode
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 8
                        Label { text: qsTr("Tagged derivatives"); font.pixelSize: 13; font.weight: Font.DemiBold }
                        Label {
                            Layout.fillWidth: true
                            visible: drawer.markedCount > 0
                            text: qsTr("Exportable marked images: %1 of %2")
                                .arg(drawer.taggedMarkedCount)
                                .arg(drawer.markedCount)
                            wrapMode: Text.WordWrap
                            font.pixelSize: 11
                            opacity: 0.6
                        }
                        Button {
                            text: qsTr("Choose Output Folder")
                            enabled: drawer.taggedMarkedCount > 0 && !appController.isExportingDerivatives
                            onClicked: derivativeFolderDialog.open()
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: appController && appController.derivativeResultSummary !== ""
                            text: appController.derivativeResultSummary
                            wrapMode: Text.WordWrap
                            font.pixelSize: 11
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
                        to: Math.max(1, appController.isTgmUpdating ? appController.tgmUpdateTotal
                            : appController.isGeneratingTagProposals ? appController.proposalGenerationTotal
                            : appController.isTaggingBulk ? appController.taggingBulkTotal
                            : appController.derivativeTotal)
                        value: appController.isTgmUpdating ? appController.tgmUpdateCurrent
                            : appController.isGeneratingTagProposals ? appController.proposalGenerationCurrent
                            : appController.isTaggingBulk ? appController.taggingBulkCurrent
                            : appController.derivativeCurrent
                        indeterminate: to <= 1
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: appController.isTgmUpdating ? qsTr("Updating TGM")
                                : appController.isGeneratingTagProposals ? qsTr("Generating proposals")
                                : appController.isTaggingBulk ? qsTr("Updating marked images")
                                : qsTr("Generating derivatives")
                            font.pixelSize: 11
                        }
                        Button {
                            text: qsTr("Cancel")
                            onClicked: {
                                if (appController.isTgmUpdating) appController.cancelTgmOperation()
                                else if (appController.isGeneratingTagProposals) appController.cancelTagProposalGeneration()
                                else if (appController.isTaggingBulk) appController.cancelBulkTagging()
                                else appController.cancelDerivativeExport()
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 14; Layout.rightMargin: 14; Layout.bottomMargin: 10
                    visible: appController && (appController.selectedTaggingError || appController.tgmUpdateError || appController.proposalGenerationError)
                    text: appController.selectedTaggingError || appController.tgmUpdateError || appController.proposalGenerationError
                    color: Material.color(Material.Red)
                    wrapMode: Text.WordWrap
                    font.pixelSize: 11
                }
            }
        }
    }
}