pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Controls.Material 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    objectName: "setsPage"

    required property var appController
    property color accentColor: Material.accent
    property var sets: []
    property var members: []
    property int selectedSetId: -1
    property int deletingSetId: -1
    property int renamingSetId: -1
    property real setListPaneWidth: 280
    property int memberOffset: 0
    property bool memberHasMore: false
    readonly property var selectedSet: {
        for (var i = 0; i < sets.length; i++) {
            if (sets[i].id === selectedSetId)
                return sets[i]
        }
        return null
    }

    function reloadSets() {
        if (!appController)
            return
        try {
            sets = JSON.parse(appController.imageSetsJson)
        } catch (error) {
            sets = []
        }
        var selectionExists = false
        for (var i = 0; i < sets.length; i++) {
            if (sets[i].id === selectedSetId)
                selectionExists = true
        }
        if (!selectionExists)
            selectedSetId = sets.length > 0 ? sets[0].id : -1
        else
            reloadMembers()
    }

    function reloadMembers() {
        members = []
        memberOffset = 0
        memberHasMore = false
        loadMembers()
    }

    function loadMembers() {
        if (!appController || selectedSetId < 1)
            return
        try {
            var page = JSON.parse(
                appController.imageSetMembersJson(selectedSetId, 200, memberOffset)
            )
            members = members.concat(page)
            memberOffset += page.length
            memberHasMore = page.length === 200
        } catch (error) {
            members = []
            memberHasMore = false
        }
    }

    function applyFilter(mode, confirmed) {
        if (appController.reapplyImageSetFilter(selectedSetId, mode, confirmed))
            reloadSets()
    }

    function beginRenameSet(setId, currentName) {
        selectedSetId = setId
        renamingSetId = setId
        renameSetNameField.text = currentName
        renameSetDialog.open()
    }

    function beginCreateSet() {
        createSetNameField.clear()
        createSetDialog.open()
    }

    function confirmDeleteSet(setId) {
        deletingSetId = setId
        deleteSetDialog.open()
    }

    onVisibleChanged: {
        if (visible)
            reloadSets()
    }
    onSelectedSetIdChanged: {
        reloadMembers()
        if (visible && appController)
            appController.setActionImageSet(selectedSetId)
    }

    Connections {
        target: root.appController
        function onImageSetsChanged() { root.reloadSets() }
        function onImageSetMembersChanged() { root.reloadMembers() }
        function onImageSetEmptyReplaceConfirmationRequired() {
            emptyReplaceDialog.open()
        }
    }

    SplitView {
        id: setsSplitView
        objectName: "setsSplitView"
        anchors.fill: parent
        orientation: Qt.Horizontal
        handle: Rectangle {
            implicitWidth: 7
            color: SplitHandle.pressed
                   ? root.accentColor
                   : Qt.darker(Material.background, 1.2)
        }
        onResizingChanged: {
            if (!resizing && setListPane.width > 0)
                root.setListPaneWidth = setListPane.width
        }

        ColumnLayout {
            id: setListPane
            objectName: "setListPane"
            SplitView.preferredWidth: root.setListPaneWidth
            SplitView.minimumWidth: 220
            SplitView.maximumWidth: Math.max(300, root.width * 0.6)
            SplitView.fillHeight: true
            spacing: 0

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.07)
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 12
                    Label {
                        text: qsTr("SETS")
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        opacity: 0.75
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        text: root.sets.length.toString()
                        font.pixelSize: 11
                        opacity: 0.6
                    }
                    ToolButton {
                        objectName: "createImageSetButton"
                        text: "+"
                        implicitWidth: 40
                        implicitHeight: 38
                        font.pixelSize: 26
                        font.weight: Font.DemiBold
                        padding: 0
                        enabled: !root.appController.imageSetOperationRunning
                        onClicked: root.beginCreateSet()
                        ToolTip.text: qsTr("Create set")
                        ToolTip.visible: hovered
                        ToolTip.delay: 400
                    }
                }
            }

            ListView {
                id: setList
                objectName: "setList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: root.sets
                delegate: ItemDelegate {
                    id: setDelegate
                    required property var modelData
                    width: setList.width
                    highlighted: modelData.id === root.selectedSetId
                    onClicked: root.selectedSetId = modelData.id
                    contentItem: RowLayout {
                        spacing: 8
                        Label {
                            Layout.fillWidth: true
                            text: setDelegate.modelData.name
                            elide: Text.ElideRight
                            font.pixelSize: 13
                        }
                        Label {
                            text: setDelegate.modelData.member_count.toString()
                            opacity: 0.6
                            font.pixelSize: 11
                        }
                        ToolButton {
                            objectName: "setRowRenameButton"
                            text: qsTr("Rename")
                            enabled: !root.appController.imageSetOperationRunning
                            onClicked: root.beginRenameSet(
                                setDelegate.modelData.id,
                                setDelegate.modelData.name
                            )
                        }
                        ToolButton {
                            objectName: "setRowDeleteButton"
                            text: qsTr("Delete")
                            enabled: !root.appController.imageSetOperationRunning
                            onClicked: root.confirmDeleteSet(setDelegate.modelData.id)
                        }
                    }
                }
                Label {
                    anchors.centerIn: parent
                    visible: root.sets.length === 0
                    text: qsTr("No sets yet")
                    opacity: 0.55
                }
            }
        }

        ColumnLayout {
            id: setDetailPane
            SplitView.minimumWidth: 360
            SplitView.fillWidth: true
            SplitView.fillHeight: true
            spacing: 0

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 52
                color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.07)
                Label {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    verticalAlignment: Text.AlignVCenter
                    text: root.selectedSet ? root.selectedSet.name : qsTr("Select or create a set")
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    opacity: root.selectedSet ? 1.0 : 0.65
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 40
                color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.04)
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    Label {
                        text: root.selectedSet
                              ? qsTr("%1 images").arg(root.selectedSet.member_count)
                              : qsTr("Select or create a set")
                        font.pixelSize: 12
                        opacity: 0.75
                    }
                    Item { Layout.fillWidth: true }
                }
            }

            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.topMargin: 8
                Layout.bottomMargin: 8
                Layout.preferredHeight: implicitHeight
                spacing: 24

                Column {
                    id: addActionGroup
                    objectName: "addSetActionGroup"
                    width: Math.min(parent.width, 300 + addMembersButton.implicitWidth + 8)
                    spacing: 4
                    Label {
                        width: parent.width
                        text: qsTr("Add")
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        ComboBox {
                            id: targetScope
                            width: Math.min(300, parent.width)
                            enabled: root.selectedSet !== null
                                     && !root.appController.imageSetOperationRunning
                            model: [
                                { text: qsTr("Selected image"), value: "selected" },
                                { text: qsTr("Marked images"), value: "marked" },
                                { text: qsTr("Current results"), value: "results" },
                                { text: qsTr("Browse folder"), value: "folder" }
                            ]
                            textRole: "text"
                            valueRole: "value"
                        }
                        Button {
                            id: addMembersButton
                            text: qsTr("Add")
                            enabled: root.selectedSet !== null
                                     && !root.appController.imageSetOperationRunning
                            onClicked: root.appController.changeImageSetMembers(
                                root.selectedSetId, targetScope.currentValue, true
                            )
                        }
                    }
                }

                Column {
                    id: filterActionGroup
                    objectName: "filterSetActionGroup"
                    width: Math.min(parent.width,
                        editFilterButton.implicitWidth + saveFilterButton.implicitWidth
                        + clearFilterButton.implicitWidth + 16)
                    spacing: 4
                    Label {
                        width: parent.width
                        text: qsTr("Filter")
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                        background: Item {
                            objectName: "filterActionSeparator"
                            visible: filterActionGroup.x > 0
                                     && filterActionGroup.y === addActionGroup.y
                            Rectangle {
                                x: -14.5
                                y: filterActionButtons.y + editFilterButton.y
                                   + (editFilterButton.height - height) / 2
                                width: 5
                                height: 5
                                rotation: 45
                                color: Material.foreground
                                opacity: 0.4
                            }
                        }
                    }
                    Flow {
                        id: filterActionButtons
                        width: parent.width
                        spacing: 8
                        Button {
                            id: editFilterButton
                            objectName: "editSetFilterButton"
                            text: qsTr("Edit filter")
                            enabled: root.selectedSet !== null
                                     && !root.appController.imageSetOperationRunning
                            onClicked: filterDialog.open()
                        }
                        Button {
                            id: saveFilterButton
                            text: qsTr("Save current Search")
                            enabled: root.selectedSet !== null
                                     && !root.appController.imageSetOperationRunning
                            onClicked: root.appController.saveCurrentSearchAsImageSetFilter(root.selectedSetId)
                        }
                        Button {
                            id: clearFilterButton
                            enabled: root.selectedSet !== null && !!root.selectedSet.apply_filter
                                     && !root.appController.imageSetOperationRunning
                            text: qsTr("Clear filter")
                            onClicked: root.appController.clearImageSetFilter(root.selectedSetId)
                        }
                    }
                }

                Column {
                    id: reapplyActionGroup
                    objectName: "reapplySetFilterGroup"
                    width: Math.min(parent.width,
                        addMatchesButton.implicitWidth + replaceMatchesButton.implicitWidth + 8)
                    spacing: 4
                    enabled: root.selectedSet !== null && !!root.selectedSet.apply_filter
                             && !root.appController.imageSetOperationRunning
                    Label {
                        width: parent.width
                        text: qsTr("Reapply saved filter")
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                        background: Item {
                            objectName: "reapplyActionSeparator"
                            visible: reapplyActionGroup.x > 0
                                     && reapplyActionGroup.y === filterActionGroup.y
                            Rectangle {
                                x: -14.5
                                y: reapplyActionButtons.y + addMatchesButton.y
                                   + (addMatchesButton.height - height) / 2
                                width: 5
                                height: 5
                                rotation: 45
                                color: Material.foreground
                                opacity: 0.4
                            }
                        }
                    }
                    Flow {
                        id: reapplyActionButtons
                        width: parent.width
                        spacing: 8
                        Button {
                            id: addMatchesButton
                            objectName: "addSetFilterMatchesButton"
                            text: qsTr("Add matches")
                            onClicked: root.applyFilter("add", false)
                        }
                        Button {
                            id: replaceMatchesButton
                            objectName: "replaceSetFilterMatchesButton"
                            text: qsTr("Replace members")
                            onClicked: root.applyFilter("replace", false)
                        }
                    }
                }
            }

            RowLayout {
                objectName: "imageSetOperationProgressRow"
                Layout.fillWidth: true
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.bottomMargin: 6
                visible: root.appController.imageSetOperationRunning
                ProgressBar {
                    objectName: "imageSetOperationProgressBar"
                    Layout.fillWidth: true
                    from: 0
                    to: root.appController.imageSetOperationProgressTotal
                    value: root.appController.imageSetOperationProgress
                    indeterminate: to <= 0
                }
                Label {
                    text: root.appController.imageSetOperationProgressTotal > 0
                          ? qsTr("%1 / %2").arg(root.appController.imageSetOperationProgress)
                                .arg(root.appController.imageSetOperationProgressTotal)
                          : qsTr("Preparing")
                    font.pixelSize: 11
                    opacity: 0.7
                }
                ToolButton {
                    objectName: "cancelImageSetOperationButton"
                    text: qsTr("Cancel")
                    onClicked: root.appController.cancelImageSetOperation()
                }
            }

            ListView {
                id: memberList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: root.members
                delegate: Item {
                    id: memberDelegate
                    required property var modelData
                    width: memberList.width
                    height: 68
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 10
                        Rectangle {
                            Layout.preferredWidth: 52
                            Layout.preferredHeight: 52
                            color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.08)
                            Image {
                                anchors.fill: parent
                                source: root.appController.imageSetMemberThumbnailSource(
                                    memberDelegate.modelData.id
                                )
                                fillMode: Image.PreserveAspectCrop
                                smooth: true
                                visible: source.toString().length > 0
                            }
                            Label {
                                anchors.centerIn: parent
                                text: qsTr("IMG")
                                font.pixelSize: 9
                                opacity: 0.45
                                visible: !parent.children[0].visible
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label {
                                Layout.fillWidth: true
                                text: memberDelegate.modelData.filename
                                elide: Text.ElideRight
                                font.pixelSize: 12
                            }
                            Label {
                                Layout.fillWidth: true
                                text: memberDelegate.modelData.path
                                elide: Text.ElideMiddle
                                opacity: 0.55
                                font.pixelSize: 10
                            }
                        }
                        Button {
                            text: qsTr("Remove")
                            enabled: !root.appController.imageSetOperationRunning
                            onClicked: root.appController.removeImageSetMember(
                                root.selectedSetId, memberDelegate.modelData.path
                            )
                        }
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: Material.dividerColor
                    }
                }
                Label {
                    anchors.centerIn: parent
                    visible: root.selectedSet !== null && root.members.length === 0
                    text: qsTr("This set is empty")
                    opacity: 0.55
                }
            }

            Button {
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: 8
                visible: root.memberHasMore
                text: qsTr("Load more")
                onClicked: root.loadMembers()
            }

            Label {
                Layout.fillWidth: true
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.bottomMargin: 8
                visible: text.length > 0
                text: root.appController ? root.appController.imageSetStatus : ""
                wrapMode: Text.Wrap
                font.pixelSize: 11
                opacity: 0.7
            }
        }
    }

    Dialog {
        id: createSetDialog
        objectName: "createSetDialog"
        modal: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(420, root.width - 32)
        title: qsTr("Create set")
        standardButtons: Dialog.NoButton

        ColumnLayout {
            anchors.fill: parent
            spacing: 12
            TextField {
                id: createSetNameField
                objectName: "createSetNameField"
                Layout.fillWidth: true
                placeholderText: qsTr("Set name")
                onAccepted: createSetButton.clicked()
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button {
                    text: qsTr("Cancel")
                    onClicked: createSetDialog.reject()
                }
                Button {
                    id: createSetButton
                    objectName: "confirmCreateSetButton"
                    text: qsTr("Create")
                    highlighted: true
                    enabled: createSetNameField.text.trim().length > 0
                    onClicked: {
                        var createdId = root.appController.createImageSet(createSetNameField.text)
                        if (createdId > 0) {
                            root.selectedSetId = createdId
                            createSetDialog.accept()
                        }
                    }
                }
            }
        }

        onOpened: createSetNameField.forceActiveFocus()
    }

    Dialog {
        id: renameSetDialog
        objectName: "renameSetDialog"
        modal: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(420, root.width - 32)
        title: qsTr("Rename set")
        standardButtons: Dialog.NoButton

        ColumnLayout {
            anchors.fill: parent
            spacing: 12
            TextField {
                id: renameSetNameField
                objectName: "renameSetNameField"
                Layout.fillWidth: true
                placeholderText: qsTr("Set name")
                onAccepted: renameSetButton.clicked()
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button {
                    text: qsTr("Cancel")
                    onClicked: renameSetDialog.reject()
                }
                Button {
                    id: renameSetButton
                    objectName: "confirmRenameSetButton"
                    text: qsTr("Rename")
                    highlighted: true
                    enabled: renameSetNameField.text.trim().length > 0
                             && !root.appController.imageSetOperationRunning
                    onClicked: {
                        if (root.appController.renameImageSet(
                                    root.renamingSetId, renameSetNameField.text))
                            renameSetDialog.accept()
                    }
                }
            }
        }

        onOpened: {
            renameSetNameField.forceActiveFocus()
            renameSetNameField.selectAll()
        }
        onClosed: root.renamingSetId = -1
    }

    Dialog {
        id: deleteSetDialog
        objectName: "deleteSetDialog"
        modal: true
        title: qsTr("Delete set?")
        standardButtons: Dialog.Yes | Dialog.Cancel
        Label {
            text: qsTr("The set and its membership will be deleted. Image files and tags will not change.")
            wrapMode: Text.Wrap
        }
        onAccepted: {
            if (root.deletingSetId > 0)
                root.appController.deleteImageSet(root.deletingSetId)
            root.deletingSetId = -1
        }
        onRejected: root.deletingSetId = -1
    }

    Dialog {
        id: emptyReplaceDialog
        objectName: "emptyReplaceDialog"
        modal: true
        title: qsTr("Replace with no matches?")
        standardButtons: Dialog.Yes | Dialog.Cancel
        Label {
            text: qsTr("This filter matches no images. Replacing will empty the set.")
            wrapMode: Text.Wrap
        }
        onAccepted: root.applyFilter("replace", true)
    }

    ImageSetFilterDialog {
        id: filterDialog
        appController: root.appController
        setId: root.selectedSetId
        initialFilter: root.selectedSet ? root.selectedSet.apply_filter : null
        onSaved: root.reloadSets()
    }
}