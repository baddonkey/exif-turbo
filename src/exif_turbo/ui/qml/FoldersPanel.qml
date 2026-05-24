import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

Item {
    id: foldersPanel

    // ── Status colour map ─────────────────────────────────────────────────
    function statusColor(status) {
        switch (status) {
            case "indexed":   return "#4caf50"
            case "scanning":  return Material.accentColor
            case "queued":    return Qt.rgba(Material.accentColor.r, Material.accentColor.g, Material.accentColor.b, 0.55)
            case "disabled":  return Material.foreground
            case "missing":   return "#ff9800"
            case "error":     return "#f44336"
            default:          return "#9e9e9e"  // "new"
        }
    }

    // ── Panel-level pending-action state (set before opening a confirm dialog) ──
    // Storing these at panel level prevents crashes caused by the ListView
    // recycling a delegate while a Dialog nested inside it is still alive.
    property int    _pendingFolderId:     -1
    property string _pendingFolderName:   ""
    property int    _pendingPreviewCount: 0

    // ── FolderDialog for adding managed folders ───────────────────────────
    FolderDialog {
        id: addFolderDialog
        title: qsTr("Select Folder to Manage")
        onAccepted: controller.addIndexedFolder(selectedFolder.toString())
    }

    // ── Confirm dialogs — declared OUTSIDE the ListView delegate ──────────
    // Keeping them here means they are never destroyed when a delegate is
    // recycled during scroll, which previously caused a segfault.
    Dialog {
        id: clearPreviewsConfirmDialog
        title: qsTr("Clear Preview Cache")
        standardButtons: Dialog.Ok | Dialog.Cancel
        anchors.centerIn: Overlay.overlay
        width: 420
        Label {
            text: qsTr("Delete %1 cached preview(s) for \"%2\"?\nThumbnails are unaffected.")
                    .arg(foldersPanel._pendingPreviewCount)
                    .arg(foldersPanel._pendingFolderName)
            wrapMode: Text.WordWrap
            width: 340
        }
        onAccepted: controller.clearPreviewsForFolder(foldersPanel._pendingFolderId)
    }

    Dialog {
        id: removeConfirmDialog
        title: qsTr("Remove Folder")
        standardButtons: Dialog.Ok | Dialog.Cancel
        anchors.centerIn: Overlay.overlay
        width: 420
        Label {
            text: qsTr("Remove \"%1\" and delete all its indexed images from the database?")
                    .arg(foldersPanel._pendingFolderName)
            wrapMode: Text.WordWrap
            width: 340
        }
        onAccepted: controller.removeIndexedFolder(foldersPanel._pendingFolderId)
    }

    // ── Layout ────────────────────────────────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── Top pane: folder list ─────────────────────────────────────────
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

        // Header row
        Rectangle {
            Layout.fillWidth: true
            height: 48
            color: Qt.rgba(Material.accentColor.r, Material.accentColor.g, Material.accentColor.b, 0.09)

            RowLayout {
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                spacing: 8

                Label {
                    text: qsTr("Managed Folders")
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }

                Button {
                    text: qsTr("Add Folder")
                    highlighted: true
                    implicitHeight: 34
                    font.pixelSize: 12
                    onClicked: addFolderDialog.open()
                }

                Button {
                    text: qsTr("Rescan All")
                    implicitHeight: 34
                    font.pixelSize: 12
                    enabled: foldersList.count > 0
                    ToolTip.text: qsTr("Incrementally re-index all enabled folders")
                    ToolTip.visible: hovered
                    onClicked: controller.rescanAllFolders()
                }

                Button {
                    text: qsTr("Full Rescan All")
                    implicitHeight: 34
                    font.pixelSize: 12
                    enabled: foldersList.count > 0
                    ToolTip.text: qsTr("Force re-extract EXIF for every file in all enabled folders")
                    ToolTip.visible: hovered
                    onClicked: controller.fullRescanAllFolders()
                }
            }
        }

        // Empty state + folder list
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // WheelHandler on the stationary wrapper Item — attaching it on
            // the ListView itself reparents it into the scrolling contentItem,
            // which slides out from under the cursor after scrolling down.
            WheelHandler {
                target: null
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                onWheel: (event) => {
                    var pixels = event.pixelDelta.y !== 0
                                 ? event.pixelDelta.y
                                 : (event.angleDelta.y / 120.0) * 60
                    var maxY = Math.max(0, foldersList.contentHeight - foldersList.height)
                    foldersList.contentY = Math.max(0, Math.min(maxY, foldersList.contentY - pixels))
                    event.accepted = true
                }
            }

            Label {
                anchors.centerIn: parent
                visible: foldersList.count === 0
                text: qsTr("No folders managed yet.\nClick \"Add Folder\" to start tracking a folder.")
                horizontalAlignment: Text.AlignHCenter
                opacity: 0.35
                font.pixelSize: 13
            }

            // Folder list
            ListView {
                id: foldersList
                objectName: "foldersList"
                anchors.fill: parent
                clip: true
                model: folderListModel
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {
                    objectName: "foldersScrollBar"
                    policy: ScrollBar.AlwaysOn
                }

            delegate: Rectangle {
                id: folderDelegate
                width: foldersList.width
                height: 76
                color: index % 2 === 0 ? Material.background : Qt.darker(Material.background, 1.03)

                // Status indicator bar on the left
                Rectangle {
                    x: 0; y: 6; width: 3; height: parent.height - 12; radius: 2
                    color: foldersPanel.statusColor(model.status)
                }

                RowLayout {
                    anchors { fill: parent; leftMargin: 16; rightMargin: 12; topMargin: 8; bottomMargin: 8 }
                    spacing: 10

                    // Enabled toggle
                    Switch {
                        id: enabledSwitch
                        checked: model.enabled
                        implicitHeight: 40
                        ToolTip.text: checked ? qsTr("Folder is included in search results") : qsTr("Folder is excluded from search results")
                        ToolTip.visible: hovered
                        onToggled: controller.setFolderEnabled(model.folderId, checked)
                    }

                    // Name + path
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Label {
                            Layout.fillWidth: true
                            text: model.displayName
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                            opacity: model.enabled ? 1.0 : 0.5
                        }

                        Label {
                            Layout.fillWidth: true
                            text: model.path
                            font.pixelSize: 10
                            font.family: "Courier New"
                            opacity: 0.45
                            elide: Text.ElideMiddle
                        }
                    }

                    // Status + image count column
                    ColumnLayout {
                        spacing: 3
                        Layout.alignment: Qt.AlignVCenter
                        Layout.preferredWidth: 150
                        Layout.minimumWidth: 150

                        // Status badge
                        Rectangle {
                            height: 18
                            width: statusLabel.implicitWidth + 12
                            radius: 9
                            color: Qt.alpha(foldersPanel.statusColor(model.status), 0.18)
                            Layout.alignment: Qt.AlignRight

                            Label {
                                id: statusLabel
                                anchors.centerIn: parent
                                text: model.status.toUpperCase()
                                font.pixelSize: 9
                                font.weight: Font.DemiBold
                                color: foldersPanel.statusColor(model.status)
                            }
                        }

                        // Image count badge — only when indexed
                        Rectangle {
                            visible: model.imageCount > 0
                            height: 16
                            width: cntLabel.implicitWidth + 10
                            radius: 8
                            color: Qt.rgba(Material.accentColor.r, Material.accentColor.g, Material.accentColor.b, 0.12)
                            Layout.alignment: Qt.AlignRight

                            Label {
                                id: cntLabel
                                anchors.centerIn: parent
                                text: model.imageCount + " " + qsTr("images")
                                font.pixelSize: 9
                                color: Material.foreground
                                opacity: 0.7
                            }
                        }

                        // Preview-cache badge
                        Rectangle {
                            visible: model.previewCachedCount > 0
                            height: 16
                            width: prevLabel.implicitWidth + 14
                            radius: 8
                            color: (model.previewTotalCount > 0 && model.previewCachedCount >= model.previewTotalCount)
                                   ? Qt.rgba(0.30, 0.69, 0.31, 0.22)   // green-ish when full
                                   : Qt.rgba(1.00, 0.60, 0.00, 0.22)   // amber when partial
                            Layout.alignment: Qt.AlignRight
                            ToolTip.text: (model.previewTotalCount > 0 && model.previewCachedCount >= model.previewTotalCount)
                                          ? qsTr("All %1 previews are cached").arg(model.previewTotalCount)
                                          : qsTr("%1 of %2 previews cached").arg(model.previewCachedCount).arg(model.previewTotalCount)
                            ToolTip.visible: previewBadgeMA.containsMouse

                            MouseArea {
                                id: previewBadgeMA
                                anchors.fill: parent
                                hoverEnabled: true
                                acceptedButtons: Qt.NoButton
                            }

                            Label {
                                id: prevLabel
                                anchors.centerIn: parent
                                text: "\u2713 " + model.previewCachedCount
                                      + (model.previewTotalCount > 0
                                         ? "/" + model.previewTotalCount
                                         : "")
                                      + " " + qsTr("previews")
                                font.pixelSize: 9
                                color: Material.foreground
                                opacity: 0.85
                            }
                        }
                    }

                    // Rescan button
                    Button {
                        flat: true
                        text: qsTr("Rescan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.status !== "scanning"
                        ToolTip.text: qsTr("Re-index this folder (incremental)")
                        ToolTip.visible: hovered
                        onClicked: controller.rescanFolder(model.folderId)
                    }

                    // Full Rescan button
                    Button {
                        flat: true
                        text: qsTr("Full Rescan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.status !== "scanning"
                        ToolTip.text: qsTr("Force re-extract EXIF for every file in this folder")
                        ToolTip.visible: hovered
                        onClicked: controller.fullRescanFolder(model.folderId)
                    }

                    // Build Previews button (folder-scoped preview-cache build)
                    Button {
                        flat: true
                        text: (controller && controller.isBuildingPreviews && controller.previewBuildFolderId === model.folderId)
                              ? qsTr("Cancel Previews")
                              : qsTr("Build Previews")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.imageCount > 0 &&
                                 (!controller || !controller.isBuildingPreviews || controller.previewBuildFolderId === model.folderId)
                        ToolTip.text: (controller && controller.isBuildingPreviews && controller.previewBuildFolderId === model.folderId)
                                      ? qsTr("Cancel the running preview build")
                                      : qsTr("Render preview-cache JPEGs for this folder")
                        ToolTip.visible: hovered
                        onClicked: {
                            if (controller.isBuildingPreviews && controller.previewBuildFolderId === model.folderId)
                                controller.cancelPreviewBuild()
                            else
                                controller.buildPreviewsForFolder(model.folderId)
                        }
                    }

                    // Clear Previews button — kept in layout (transparent when nothing cached)
                    // so the Remove button stays aligned across rows.
                    Button {
                        flat: true
                        text: qsTr("Clear Previews")
                        font.pixelSize: 11
                        implicitHeight: 30
                        opacity: model.previewCachedCount > 0 ? 1.0 : 0.0
                        enabled: model.previewCachedCount > 0 &&
                                 (!controller.isBuildingPreviews
                                  || controller.previewBuildFolderId !== model.folderId)
                        ToolTip.text: qsTr("Delete all cached previews for this folder")
                        ToolTip.visible: hovered
                        onClicked: {
                            foldersPanel._pendingFolderId = model.folderId
                            foldersPanel._pendingFolderName = model.displayName
                            foldersPanel._pendingPreviewCount = model.previewCachedCount
                            clearPreviewsConfirmDialog.open()
                        }
                    }

                    // Remove button
                    Button {
                        flat: true
                        text: qsTr("Remove")
                        font.pixelSize: 11
                        implicitHeight: 30
                        Material.foreground: Material.Red
                        ToolTip.text: qsTr("Remove this folder and delete its indexed images")
                        ToolTip.visible: hovered
                        onClicked: {
                            foldersPanel._pendingFolderId = model.folderId
                            foldersPanel._pendingFolderName = model.displayName
                            removeConfirmDialog.open()
                        }
                    }
                }

                // Bottom divider
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width; height: 1
                    color: Material.dividerColor
                    opacity: 0.5
                }
            }
        }
    }
            }
        }

        // ── Bottom pane: activity / progress (3 equal columns) ────────────
        Item {
            Layout.fillWidth: true
            implicitHeight: 200

            // Top divider so the pane reads as a separate region
            Rectangle {
                anchors { top: parent.top; left: parent.left; right: parent.right }
                height: 1
                color: Material.dividerColor
                opacity: 0.5
            }

            RowLayout {
                anchors { fill: parent; margins: 12; topMargin: 16 }
                spacing: 12

                // Reusable progress column inlined three times
                component ProgressColumn: Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 1   // equal 1/3 distribution
                    radius: 6
                    color: active
                        ? Qt.rgba(Material.accentColor.r, Material.accentColor.g, Material.accentColor.b, 0.08)
                        : Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.04)
                    border.width: 1
                    border.color: active
                        ? Qt.rgba(Material.accentColor.r, Material.accentColor.g, Material.accentColor.b, 0.35)
                        : Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.10)

                    property string title: ""
                    property bool   active: false
                    property int    current: 0
                    property int    total: 0
                    property string currentFile: ""
                    property string cancelText: ""
                    property bool   canceling: false
                    signal cancelRequested()

                    ColumnLayout {
                        anchors { fill: parent; margins: 12 }
                        spacing: 8

                        Label {
                            Layout.fillWidth: true
                            text: title
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                            opacity: active ? 1.0 : 0.5
                            horizontalAlignment: Text.AlignHCenter
                        }

                        ProgressBar {
                            Layout.fillWidth: true
                            from: 0
                            to: total > 0 ? total : 1
                            value: current
                            indeterminate: active && total === 0
                            opacity: active ? 1.0 : 0.35
                        }

                        Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: active
                                  ? (total > 0
                                     ? current + " / " + total
                                     : (current > 0 ? current + " " + qsTr("done\u2026") : qsTr("Preparing\u2026")))
                                  : qsTr("Idle")
                            font.pixelSize: 11
                            opacity: 0.7
                        }

                        Label {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: active ? currentFile : ""
                            font.pixelSize: 10
                            opacity: 0.5
                            elide: Text.ElideMiddle
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignTop
                            wrapMode: Text.WrapAnywhere
                        }

                        Button {
                            Layout.alignment: Qt.AlignHCenter
                            text: canceling ? qsTr("Canceling\u2026") : cancelText
                            visible: active
                            enabled: active && !canceling
                            highlighted: true
                            Material.accent: Material.Red
                            implicitHeight: 30
                            font.pixelSize: 11
                            onClicked: parent.parent.cancelRequested()
                        }
                    }
                }

                ProgressColumn {
                    title: controller && controller.isIndexing && controller.indexQueueTotal > 1
                           ? qsTr("Indexing (%1/%2)").arg(controller.indexQueuePosition).arg(controller.indexQueueTotal)
                           : qsTr("Indexing")
                    active: controller ? controller.isIndexing : false
                    current: controller ? controller.indexCurrent : 0
                    total: controller ? controller.indexTotal : 0
                    currentFile: controller ? controller.indexCurrentFile : ""
                    cancelText: qsTr("Cancel")
                    canceling: controller ? controller.isCanceling : false
                    onCancelRequested: controller.cancelIndex()
                }

                ProgressColumn {
                    title: qsTr("Thumbnails")
                    active: controller ? controller.isBuildingThumbs : false
                    current: controller ? controller.thumbCurrent : 0
                    total: controller ? controller.thumbTotal : 0
                    currentFile: controller ? controller.thumbCurrentFile : ""
                    cancelText: qsTr("Cancel")
                    canceling: controller ? controller.isCanceling : false
                    onCancelRequested: controller.cancelThumbnails()
                }

                ProgressColumn {
                    title: qsTr("Previews")
                    active: controller ? controller.isBuildingPreviews : false
                    current: controller ? controller.previewCurrent : 0
                    total: controller ? controller.previewTotal : 0
                    currentFile: controller ? controller.previewCurrentFile : ""
                    cancelText: qsTr("Cancel")
                    canceling: false  // preview cancel always allowed
                    onCancelRequested: controller.cancelPreviewBuild()
                }
            }
        }
    }
}
