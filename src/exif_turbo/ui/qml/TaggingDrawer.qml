import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Drawer {
    id: drawer
    objectName: "taggingDrawer"
    edge: Qt.RightEdge
    width: Math.min(800, parent ? parent.width : 800)
    height: parent ? parent.height : 700
    modal: false
    dim: false
    closePolicy: Popup.CloseOnEscape
    padding: 0

    required property var appController
    required property var appSettings
    property string selectedFilename: ""
    property bool browseMode: false
    property bool setMode: false
    property string setName: ""
    property int currentSetId: -1
    property string chosenCopyTarget: ""
    property string chosenDescriptionCopyTarget: ""
    property bool refreshingCopyTargets: false
    property bool showFreeTagSuggestions: false
    property bool syncingDescription: false
    readonly property bool hasSelection: appController && appController.hasTaggingSelection
    readonly property bool locallyBusy: appController && appController.isTaggingBulk

    onBrowseModeChanged: {
        chosenCopyTarget = ""
        chosenDescriptionCopyTarget = ""
        copyTarget.currentIndex = 0
        copyDescriptionTarget.currentIndex = 0
        refreshCopyTargets()
    }
    onSetModeChanged: {
        chosenCopyTarget = ""
        chosenDescriptionCopyTarget = ""
        copyTarget.currentIndex = -1
        copyDescriptionTarget.currentIndex = -1
        refreshCopyTargets()
    }
    onCurrentSetIdChanged: refreshCopyTargets()
    onSetNameChanged: refreshCopyTargets()
    Component.onCompleted: refreshCopyTargets()

    function refreshCopyTargets() {
        if (!appController)
            return
        var selectedValue = chosenCopyTarget || copyTarget.currentValue
        var descriptionSelectedValue = chosenDescriptionCopyTarget || copyDescriptionTarget.currentValue
        var targets
        if (setMode) {
            targets = [
                { text: qsTr("Marked images (%1)").arg(appController.actionMarkedCount), value: "marked" },
                { text: setName + " (" + appController.actionImageCount + ")", value: "set" }
            ]
        } else {
            targets = [
                { text: qsTr("Marked images (%1)").arg(appController.checkedCount), value: "marked" },
                browseMode
                    ? { text: qsTr("Current folder (%1)").arg(appController.totalResults), value: "folder" }
                    : { text: qsTr("Current search results (%1)").arg(appController.totalResults), value: "results" }
            ]
        }
        try {
            var imageSets = JSON.parse(appController.imageSetsJson)
            for (var imageSet of imageSets) {
                if (setMode && imageSet.id === currentSetId)
                    continue
                targets.push({
                    text: imageSet.name + " (" + imageSet.member_count + ")",
                    value: "set:" + imageSet.id
                })
            }
        } catch (error) {
        }
        refreshingCopyTargets = true
        copyTarget.model = targets
        var selectedIndex = selectedValue ? -1 : (setMode ? 1 : 0)
        for (var index = 0; index < targets.length; index++) {
            if (targets[index].value === selectedValue) {
                selectedIndex = index
                break
            }
        }
        copyTarget.currentIndex = selectedIndex
        chosenCopyTarget = selectedIndex >= 0 ? targets[selectedIndex].value : selectedValue
        copyDescriptionTarget.model = targets
        var descriptionSelectedIndex = descriptionSelectedValue ? -1 : (setMode ? 1 : 0)
        for (var descriptionIndex = 0; descriptionIndex < targets.length; descriptionIndex++) {
            if (targets[descriptionIndex].value === descriptionSelectedValue) {
                descriptionSelectedIndex = descriptionIndex
                break
            }
        }
        copyDescriptionTarget.currentIndex = descriptionSelectedIndex
        chosenDescriptionCopyTarget = descriptionSelectedIndex >= 0
            ? targets[descriptionSelectedIndex].value : descriptionSelectedValue
        refreshingCopyTargets = false
    }

    Dialog {
        id: replaceDescriptionDialog
        objectName: "replaceCopiedDescriptionDialog"
        property string targetScope: ""
        title: qsTr("Replace descriptions on target images?")
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        anchors.centerIn: parent
        onAccepted: drawer.appController.copySelectedDescription(targetScope, "replace")

        Label {
            width: Math.min(340, replaceDescriptionDialog.availableWidth)
            text: qsTr("The saved custom description will replace each target's custom description. An empty source clears it. This cannot be undone.")
            wrapMode: Text.WordWrap
        }
    }

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
        refreshCopyTargets()
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

    function syncDescriptionDraftField() {
        if (!drawer.appController)
            return
        drawer.syncingDescription = true
        try {
            descriptionDraftEditor.text = drawer.appController.descriptionDraftMatchesSelection
                ? drawer.appController.descriptionDraft
                : drawer.appController.selectedImageDescription
        } finally {
            drawer.syncingDescription = false
        }
    }

    Connections {
        target: appController
        function onCurrentResultRowChanged() {
            if (drawer.opened && drawer.showFreeTagSuggestions)
                appController.searchFreeTags(freeTagField.text)
        }
        function onTaggingSelectionChanged() {
            if (drawer.opened && drawer.showFreeTagSuggestions)
                appController.searchFreeTags(freeTagField.text)
        }
            function onActionScopeChanged() { drawer.refreshCopyTargets() }
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

        RowLayout {
            objectName: "taggingColumns"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            spacing: 0

            ScrollView {
                objectName: "taggingScrollView"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                contentWidth: availableWidth
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    objectName: "customTaggingColumn"
                    width: parent.width
                    spacing: 0

                    Connections {
                        target: drawer.appController
                        function onTaggingStateChanged() {
                            drawer.syncDescriptionDraftField()
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
                        objectName: "customTagsGroup"
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

                    ColumnLayout {
                        objectName: "descriptionEditor"
                        visible: drawer.hasSelection
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 8

                        Label {
                            text: qsTr("Custom description")
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }
                        ScrollView {
                            objectName: "descriptionDraftScrollView"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(
                                Math.max(descriptionDraftEditor.implicitHeight, 72), 160
                            )
                            clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical.policy: ScrollBar.AsNeeded

                            TextArea {
                                id: descriptionDraftEditor
                                objectName: "descriptionDraftEditor"
                                enabled: drawer.hasSelection && drawer.appController
                                    && !drawer.locallyBusy
                                    && drawer.appController.descriptionDraftCanEdit
                                    && drawer.appController.freeTaggingAvailable
                                placeholderText: qsTr("Custom description")
                                textFormat: TextEdit.PlainText
                                selectByMouse: true
                                wrapMode: TextEdit.Wrap
                                onTextChanged: {
                                    if (!drawer.syncingDescription && activeFocus && enabled)
                                        drawer.appController.updateSelectedDescriptionDraft(text)
                                }
                                Keys.onPressed: function(event) {
                                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                                            && !(event.modifiers & Qt.ShiftModifier)) {
                                        event.accepted = true
                                        if (saveDescriptionButton.enabled)
                                            drawer.appController.saveSelectedDescription("replace")
                                    }
                                }
                                Component.onCompleted: drawer.syncDescriptionDraftField()
                            }
                        }
                        Label {
                            visible: drawer.appController
                                && drawer.appController.descriptionDraftActive
                                && !drawer.appController.descriptionDraftMatchesSelection
                            text: qsTr("A draft is being kept for %1. Return to that image or discard the draft.")
                                .arg(drawer.appController ? drawer.appController.descriptionDraftFilename : "")
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                            color: Material.color(Material.Orange)
                        }
                        Label {
                            visible: drawer.appController
                                && drawer.appController.descriptionDraftSavedChanged
                            text: qsTr("The saved description changed while you were editing. Discard this draft before continuing.")
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                            color: Material.color(Material.Orange)
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Button {
                                id: saveDescriptionButton
                                objectName: "saveDescriptionButton"
                                text: qsTr("Save")
                                enabled: drawer.appController && drawer.appController.freeTaggingAvailable
                                    && !drawer.locallyBusy
                                    && drawer.appController.descriptionDraftActive
                                    && drawer.appController.descriptionDraftMatchesSelection
                                    && !drawer.appController.descriptionDraftSavedChanged
                                onClicked: drawer.appController.saveSelectedDescription("replace")
                            }
                            Button {
                                objectName: "discardDescriptionDraftButton"
                                text: qsTr("Discard draft")
                                visible: drawer.appController && drawer.appController.descriptionDraftActive
                                onClicked: drawer.appController.discardSelectedDescriptionDraft()
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
                        objectName: "copyTagsGroup"
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
                                model: []
                                onCurrentValueChanged: {
                                    if (!drawer.refreshingCopyTargets && currentIndex >= 0)
                                        drawer.chosenCopyTarget = currentValue || ""
                                }
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
                                         && copyTarget.currentIndex >= 0
                                onClicked: {
                                    if (copyReplaceMode.checked) {
                                        replaceTagsDialog.targetScope = copyTarget.currentValue
                                        replaceTagsDialog.open()
                                    } else {
                                        appController.copySelectedTags(copyTarget.currentValue, "add")
                                    }
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        objectName: "copyDescriptionGroup"
                        visible: drawer.appController && drawer.appController.freeTaggingAvailable
                        Layout.fillWidth: true
                        spacing: 0

                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Material.dividerColor }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.margins: 14
                            spacing: 8

                            Label {
                                text: qsTr("Copy description to other images")
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("Copies the saved custom description only. Drafts, embedded descriptions, and ignore settings are not copied. The current image is excluded.")
                                wrapMode: Text.WordWrap
                                font.pixelSize: 10
                                opacity: 0.55
                            }
                            ComboBox {
                                id: copyDescriptionTarget
                                objectName: "copyDescriptionTarget"
                                Layout.fillWidth: true
                                currentIndex: 0
                                textRole: "text"
                                valueRole: "value"
                                model: []
                                onCurrentValueChanged: {
                                    if (!drawer.refreshingCopyTargets && currentIndex >= 0)
                                        drawer.chosenDescriptionCopyTarget = currentValue || ""
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 14
                                ButtonGroup { id: copyDescriptionModeGroup }
                                RadioButton {
                                    id: copyDescriptionAddMode
                                    objectName: "copyDescriptionAddMode"
                                    text: qsTr("Add")
                                    checked: true
                                    ButtonGroup.group: copyDescriptionModeGroup
                                    ToolTip.text: qsTr("Append the source description as a new paragraph")
                                    ToolTip.visible: hovered
                                }
                                RadioButton {
                                    id: copyDescriptionReplaceMode
                                    objectName: "copyDescriptionReplaceMode"
                                    text: qsTr("Replace")
                                    ButtonGroup.group: copyDescriptionModeGroup
                                    ToolTip.text: qsTr("Replace or clear target custom descriptions")
                                    ToolTip.visible: hovered
                                }
                            }
                            Button {
                                objectName: "copyDescriptionButton"
                                Layout.fillWidth: true
                                text: qsTr("Copy Description")
                                highlighted: true
                                enabled: drawer.hasSelection && !drawer.locallyBusy
                                    && copyDescriptionTarget.currentIndex >= 0
                                    && (copyDescriptionReplaceMode.checked
                                        || (drawer.appController
                                            && drawer.appController.selectedImageDescription.length > 0))
                                onClicked: {
                                    if (copyDescriptionReplaceMode.checked) {
                                        replaceDescriptionDialog.targetScope = copyDescriptionTarget.currentValue
                                        replaceDescriptionDialog.open()
                                    } else {
                                        drawer.appController.copySelectedDescription(
                                            copyDescriptionTarget.currentValue, "add")
                                    }
                                }
                            }
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        Layout.leftMargin: 14
                        Layout.rightMargin: 14
                        Layout.bottomMargin: 10
                        visible: !!drawer.appController && drawer.appController.taggingBulkSummary !== ""
                        text: drawer.appController ? drawer.appController.taggingBulkSummary : ""
                        wrapMode: Text.WordWrap
                        font.pixelSize: 10
                        opacity: 0.7
                    }

                    ColumnLayout {
                        visible: drawer.locallyBusy
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 7
                        ProgressBar {
                            Layout.fillWidth: true
                            from: 0
                            to: drawer.appController ? Math.max(1, drawer.appController.taggingBulkTotal) : 1
                            value: drawer.appController ? drawer.appController.taggingBulkCurrent : 0
                            indeterminate: to <= 1
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: drawer.appController && drawer.appController.isCopyingDescription
                                    ? qsTr("Copying descriptions") : qsTr("Copying tags")
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
                        text: drawer.appController ? drawer.appController.selectedTaggingError : ""
                        color: Material.color(Material.Red)
                        wrapMode: Text.WordWrap
                        font.pixelSize: 11
                    }
                }
            }

            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                color: Material.dividerColor
            }

            ScrollView {
                objectName: "existingTaggingScrollView"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                contentWidth: availableWidth
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    objectName: "existingTaggingColumn"
                    width: parent.width
                    spacing: 0

                    ColumnLayout {
                        objectName: "existingImageTagsGroup"
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
                                    || (!!drawer.appController && drawer.appController.excludeAllEmbeddedTags)
                                width: embeddedTags.width
                                height: 34
                                highlighted: effectivelyExcluded
                                enabled: !!drawer.appController && !drawer.appController.excludeAllEmbeddedTags
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

                    ColumnLayout {
                        objectName: "existingEmbeddedDescriptionGroup"
                        visible: drawer.hasSelection
                        Layout.fillWidth: true
                        Layout.margins: 14
                        spacing: 8

                        Label {
                            text: qsTr("Existing embedded description")
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }
                        Label {
                            visible: drawer.appController
                                && drawer.appController.embeddedImageDescription.length === 0
                            text: qsTr("No embedded description.")
                            opacity: 0.55
                            font.pixelSize: 11
                        }
                        ScrollView {
                            objectName: "embeddedDescriptionScrollView"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(Math.max(embeddedDescriptionText.implicitHeight, 48), 120)
                            visible: embeddedDescriptionText.text.length > 0
                            clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical.policy: ScrollBar.AsNeeded

                            TextArea {
                                id: embeddedDescriptionText
                                objectName: "embeddedImageDescription"
                                text: drawer.appController ? drawer.appController.embeddedImageDescription : ""
                                textFormat: TextEdit.PlainText
                                readOnly: true
                                wrapMode: TextEdit.Wrap
                                selectByMouse: true
                                font.strikeout: drawer.appController
                                    && drawer.appController.excludeEmbeddedDescription
                            }
                        }
                        Switch {
                            objectName: "excludeEmbeddedDescriptionSwitch"
                            Layout.fillWidth: true
                            text: qsTr("Ignore embedded description")
                            checked: drawer.appController
                                ? drawer.appController.excludeEmbeddedDescription : false
                            enabled: drawer.hasSelection && !drawer.locallyBusy
                                && drawer.appController && drawer.appController.freeTaggingAvailable
                            onToggled: drawer.appController.setSelectedEmbeddedDescriptionExcluded(checked)
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Remove embedded descriptions from exported copies, even without a replacement. Originals stay unchanged.")
                            wrapMode: Text.WordWrap
                            font.pixelSize: 11
                            opacity: 0.65
                        }
                    }

                }
            }
        }

        RowLayout {
            objectName: "finalDerivativesFooter"
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            Layout.minimumHeight: 140
            Layout.maximumHeight: 140
            spacing: 1

            Rectangle {
                objectName: "derivativeTagsFooter"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
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

            Rectangle {
                objectName: "derivativeDescriptionFooter"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                color: Qt.rgba(Material.accentColor.r, Material.accentColor.g,
                               Material.accentColor.b, 0.07)

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 4
                    Label {
                        text: qsTr("Final derivative description")
                        color: Material.accent
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                    Label {
                        visible: !drawer.hasSelection
                        text: qsTr("No image selected")
                        opacity: 0.55
                        font.pixelSize: 11
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: drawer.hasSelection && (!drawer.appController
                            || drawer.appController.finalDerivativeDescription.length === 0)
                        text: qsTr("No description would be written to a derivative.")
                        wrapMode: Text.WordWrap
                        opacity: 0.55
                        font.pixelSize: 11
                    }
                    ScrollView {
                        objectName: "finalDescriptionScrollView"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: drawer.hasSelection && drawer.appController
                            && drawer.appController.finalDerivativeDescription.length > 0
                        clip: true
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        ScrollBar.vertical.policy: ScrollBar.AsNeeded
                        TextArea {
                            objectName: "finalDerivativeDescription"
                            text: drawer.appController ? drawer.appController.finalDerivativeDescription : ""
                            textFormat: TextEdit.PlainText
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            font.pixelSize: 11
                }
            }
        }
    }
        }
    }
}