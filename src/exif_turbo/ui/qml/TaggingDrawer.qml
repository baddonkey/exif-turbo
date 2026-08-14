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
    property bool showFreeTagSuggestions: false
    readonly property bool hasSelection: appController && appController.currentResultRow >= 0
    readonly property bool locallyBusy: appController && (
        appController.isTgmUpdating
        || appController.isGeneratingTagProposals)

    function openAndFocus() {
        open()
        if (appController && appController.freeTaggingAvailable)
            Qt.callLater(function() {
                if (appController.taggingAvailable)
                    tgmSearchField.forceActiveFocus()
                else
                    freeTagField.forceActiveFocus()
            })
    }

    onOpened: {
        proposalGenerationTimer.restart()
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
            if (drawer.opened) {
                proposalGenerationTimer.restart()
                if (drawer.showFreeTagSuggestions)
                    appController.searchFreeTags(freeTagField.text)
            }
        }
    }

    Timer {
        id: proposalGenerationTimer
        interval: 100
        repeat: false
        onTriggered: {
            if (!drawer.opened || !drawer.hasSelection || !appController.taggingProposalAvailable)
                return
            if (appController.isGeneratingTagProposals) {
                restart()
                return
            }
            appController.generateSelectedTagProposals()
        }
    }

    function applyCurrentSearchResult() {
        if (!appController || tgmResults.count === 0)
            return
        var item = tgmResults.itemAtIndex(Math.max(0, tgmResults.currentIndex))
        if (!item)
            item = tgmResults.itemAtIndex(0)
        if (!item)
            return
        appController.addSelectedTgmConcept(item.conceptReference)
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
                        delegate: Label {
                            required property string label
                            width: embeddedTags.width
                            height: 28
                            text: label
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                            font.pixelSize: 12
                            opacity: 0.75
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
                    visible: appController && appController.taggingEnabled && !appController.tgmInstalled
                    Layout.fillWidth: true
                    Layout.margins: 18
                    spacing: 10
                    Label { text: qsTr("Install TGM to search and apply controlled terms. Custom tags remain available below."); wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Button {
                        text: qsTr("Install TGM")
                        highlighted: true
                        enabled: !appController.isTgmUpdating
                        onClicked: appController.installOrUpdateTgm()
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
                        delegate: RowLayout {
                            required property string label
                            width: currentFreeTags.width
                            height: 36
                            spacing: 7
                            Label {
                                Layout.fillWidth: true
                                text: label
                                elide: Text.ElideRight
                                font.pixelSize: 12
                            }
                            ToolButton {
                                text: "\u2212"
                                implicitWidth: 30
                                implicitHeight: 30
                                onClicked: appController.removeSelectedFreeTag(label)
                                ToolTip.text: qsTr("Remove custom tag from selected image")
                                ToolTip.visible: hovered
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
                    visible: appController && appController.taggingAvailable
                    Layout.fillWidth: true
                    spacing: 0

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
                                enabled: drawer.hasSelection
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
                                enabled: drawer.hasSelection && tgmResults.count > 0
                                onClicked: drawer.applyCurrentSearchResult()
                                ToolTip.text: qsTr("Add to current image")
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
                                    onClicked: appController.removeSelectedTgmConcept(conceptId)
                                    ToolTip.text: qsTr("Remove from selected image")
                                    ToolTip.visible: hovered
                                }
                            }
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
                            text: qsTr("Generate for current image")
                            enabled: drawer.hasSelection && appController.taggingProposalAvailable
                                && !appController.isGeneratingTagProposals
                            onClicked: appController.generateSelectedTagProposals()
                        }
                        ListView {
                            id: proposalsList
                            objectName: "pendingProposalsList"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(contentHeight, 190)
                            interactive: contentHeight > height
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            model: appController ? appController.pendingProposalsModel : null
                            ScrollBar.vertical: ScrollBar {
                                id: proposalsScrollBar
                                objectName: "tagProposalsScrollBar"
                                policy: ScrollBar.AsNeeded
                                active: proposalsList.contentHeight > proposalsList.height
                            }
                            delegate: RowLayout {
                                required property string conceptId
                                required property string label
                                required property string category
                                required property real score
                                required property string provider
                                required property string providerFingerprint
                                width: proposalsList.width
                                    - (proposalsScrollBar.visible ? proposalsScrollBar.width : 0)
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
                            : appController.proposalGenerationTotal)
                        value: appController.isTgmUpdating ? appController.tgmUpdateCurrent
                            : appController.proposalGenerationCurrent
                        indeterminate: to <= 1
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: appController.isTgmUpdating ? qsTr("Updating TGM")
                                : qsTr("Generating proposals")
                            font.pixelSize: 11
                        }
                        Button {
                            text: qsTr("Cancel")
                            onClicked: {
                                if (appController.isTgmUpdating) appController.cancelTgmOperation()
                                else appController.cancelTagProposalGeneration()
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