import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

Item {
    id: foldersPanel
    objectName: "foldersPanel"
    property bool expertMode: false

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

                ButtonGroup {
                    id: modeGroup
                    exclusive: true
                }

                RowLayout {
                    spacing: 0

                    Button {
                        objectName: "basicModeButton"
                        text: qsTr("Basic")
                        checkable: true
                        checked: !foldersPanel.expertMode
                        highlighted: checked
                        implicitHeight: 34
                        font.pixelSize: 11
                        ButtonGroup.group: modeGroup
                        onClicked: foldersPanel.expertMode = false
                    }

                    Button {
                        objectName: "expertModeButton"
                        text: qsTr("Expert")
                        checkable: true
                        checked: foldersPanel.expertMode
                        highlighted: checked
                        implicitHeight: 34
                        font.pixelSize: 11
                        ButtonGroup.group: modeGroup
                        onClicked: foldersPanel.expertMode = true
                    }
                }

                Button {
                    text: qsTr("Add Folder")
                    highlighted: true
                    implicitHeight: 34
                    font.pixelSize: 12
                    enabled: !controller || !controller.folderWorkflowRunning
                    onClicked: addFolderDialog.open()
                }

                Button {
                    objectName: "scanAllButton"
                    text: qsTr("Scan")
                    implicitHeight: 34
                    font.pixelSize: 12
                    enabled: foldersList.count > 0 && controller &&
                             !controller.folderWorkflowRunning && !controller.isBusy &&
                             !controller.isIndexing && !controller.isBuildingPreviews &&
                             !controller.isAiScanning
                    ToolTip.text: qsTr("Scan, refresh tags, build previews, and run AI-Scan for all enabled folders")
                    ToolTip.visible: hovered
                    onClicked: { if (controller) controller.rescanAllFolders() }
                }

                Button {
                    objectName: "fullRescanAllButton"
                    text: qsTr("Full Scan")
                    implicitHeight: 34
                    font.pixelSize: 12
                    enabled: foldersList.count > 0 && controller &&
                             !controller.folderWorkflowRunning && !controller.isBusy &&
                             !controller.isIndexing && !controller.isBuildingPreviews &&
                             !controller.isAiScanning
                    ToolTip.text: qsTr("Fully rescan, refresh tags, rebuild previews, and rebuild AI data for all enabled folders")
                    ToolTip.visible: hovered
                    onClicked: { if (controller) controller.fullRescanAllFolders() }
                }
            }
        }

        // Empty state + folder list
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

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
                readonly property bool aiScanningThisFolder: controller &&
                    controller.isAiScanning && controller.aiScanFolderId === model.folderId
                readonly property color rowStatusColor: aiScanningThisFolder
                    ? Material.accentColor : foldersPanel.statusColor(model.status)

                // Status indicator bar on the left
                Rectangle {
                    x: 0; y: 6; width: 3; height: parent.height - 12; radius: 2
                    color: folderDelegate.rowStatusColor
                }

                RowLayout {
                    anchors { fill: parent; leftMargin: 16; rightMargin: 12; topMargin: 8; bottomMargin: 8 }
                    spacing: 10

                    // Enabled toggle
                    Switch {
                        id: enabledSwitch
                        objectName: "folderEnabledSwitch"
                        checked: model.enabled
                        implicitHeight: 40
                        enabled: !controller || (!controller.folderWorkflowRunning &&
                                 !controller.isBusy && !controller.isIndexing &&
                                 !controller.isBuildingPreviews && !controller.isAiScanning)
                        ToolTip.text: checked ? qsTr("Folder is included in search results") : qsTr("Folder is excluded from search results")
                        ToolTip.visible: hovered
                        onToggled: { if (controller) controller.setFolderEnabled(model.folderId, checked) }
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
                            implicitHeight: 18
                            implicitWidth: statusContent.implicitWidth + 20
                            radius: 9
                            color: Qt.alpha(folderDelegate.rowStatusColor, 0.18)
                            Layout.alignment: Qt.AlignRight

                            Row {
                                id: statusContent
                                anchors.centerIn: parent
                                spacing: 4

                                BusyIndicator {
                                    width: 12
                                    height: 12
                                    running: folderDelegate.aiScanningThisFolder
                                    visible: running
                                }

                                Label {
                                    id: statusLabel
                                    text: folderDelegate.aiScanningThisFolder
                                        ? (controller.aiScanIsFullRescan
                                                         ? qsTr("AI Full Scan")
                                           : qsTr("AI-Scan"))
                                        : model.status.toUpperCase()
                                    font.pixelSize: 9
                                    font.weight: Font.DemiBold
                                    color: folderDelegate.rowStatusColor
                                }
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
                        objectName: "basicScanButton"
                        flat: true
                        visible: !foldersPanel.expertMode
                        text: qsTr("Scan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.status !== "scanning" &&
                                 controller && !controller.folderWorkflowRunning &&
                                 !controller.isBusy && !controller.isIndexing &&
                                 !controller.isBuildingPreviews && !controller.isAiScanning
                        ToolTip.text: qsTr("Rescan, refresh tags, build previews, and run AI-Scan")
                        ToolTip.visible: hovered
                        onClicked: { if (controller) controller.scanFolder(model.folderId) }
                    }

                    Button {
                        objectName: "basicFullScanButton"
                        flat: true
                        visible: !foldersPanel.expertMode
                        text: qsTr("Full Scan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.status !== "scanning" &&
                                 controller && !controller.folderWorkflowRunning &&
                                 !controller.isBusy && !controller.isIndexing &&
                                 !controller.isBuildingPreviews && !controller.isAiScanning
                        ToolTip.text: qsTr("Full rescan, refresh tags, clear and rebuild previews, and run AI Full Rescan")
                        ToolTip.visible: hovered
                        onClicked: { if (controller) controller.fullScanFolder(model.folderId) }
                    }

                    Button {
                        objectName: "expertRescanButton"
                        flat: true
                        visible: foldersPanel.expertMode
                        text: qsTr("Scan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.status !== "scanning" &&
                                 (!controller || !controller.folderWorkflowRunning)
                        ToolTip.text: qsTr("Re-index this folder (incremental)")
                        ToolTip.visible: hovered
                        onClicked: { if (controller) controller.rescanFolder(model.folderId) }
                    }

                    // Full Scan button
                    Button {
                        objectName: "expertFullRescanButton"
                        flat: true
                        visible: foldersPanel.expertMode
                        text: qsTr("Full Scan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.status !== "scanning" &&
                                 (!controller || !controller.folderWorkflowRunning)
                        ToolTip.text: qsTr("Force re-extract EXIF for every file in this folder")
                        ToolTip.visible: hovered
                        onClicked: { if (controller) controller.fullRescanFolder(model.folderId) }
                    }

                    Button {
                        objectName: "expertRefreshTagsButton"
                        flat: true
                        visible: foldersPanel.expertMode
                        text: qsTr("Refresh Tags")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.imageCount > 0 &&
                                 model.status !== "scanning" &&
                                 (!controller || (!controller.isBusy &&
                                  !controller.folderWorkflowRunning))
                        ToolTip.text: qsTr("Re-read sidecar tag files for indexed images in this folder")
                        ToolTip.visible: hovered
                        onClicked: {
                            if (controller)
                                controller.refreshSidecarsForFolder(model.folderId)
                        }
                    }

                    // Build Previews button (folder-scoped preview-cache build)
                    Button {
                        objectName: "expertBuildPreviewsButton"
                        flat: true
                        visible: foldersPanel.expertMode
                        text: (controller && controller.isBuildingPreviews && controller.previewBuildFolderId === model.folderId)
                              ? qsTr("Cancel Previews")
                              : qsTr("Build Previews")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.imageCount > 0 &&
                                 (!controller || !controller.folderWorkflowRunning) &&
                                 (!controller || !controller.isBuildingPreviews || controller.previewBuildFolderId === model.folderId)
                        ToolTip.text: (controller && controller.isBuildingPreviews && controller.previewBuildFolderId === model.folderId)
                                      ? qsTr("Cancel the running preview build")
                                      : qsTr("Render preview-cache JPEGs for this folder")
                        ToolTip.visible: hovered
                        onClicked: {
                            if (!controller)
                                return
                            if (controller.isBuildingPreviews && controller.previewBuildFolderId === model.folderId)
                                controller.cancelPreviewBuild()
                            else
                                controller.buildPreviewsForFolder(model.folderId)
                        }
                    }

                    // AI-Scan button — CLIP vector embedding for this folder
                    Button {
                        objectName: "expertAiScanButton"
                        flat: true
                        visible: foldersPanel.expertMode && controller && controller.aiEnabled
                        text: (controller && controller.isAiScanning
                               && controller.aiScanFolderId === model.folderId
                               && !controller.aiScanIsFullRescan)
                              ? qsTr("Cancel AI-Scan")
                              : qsTr("AI-Scan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.imageCount > 0 &&
                                 (!controller || !controller.folderWorkflowRunning) &&
                                 (!controller || !controller.isAiScanning
                                  || (controller.aiScanFolderId === model.folderId
                                      && !controller.aiScanIsFullRescan))
                        ToolTip.text: (controller && controller.isAiScanning
                                       && controller.aiScanFolderId === model.folderId
                                       && !controller.aiScanIsFullRescan)
                                      ? qsTr("Cancel the running AI-Scan")
                                      : qsTr("Build missing CLIP vector embeddings for this folder (enables AI search)")
                        ToolTip.visible: hovered
                        onClicked: {
                            if (!controller)
                                return
                            if (controller.isAiScanning
                                    && controller.aiScanFolderId === model.folderId
                                    && !controller.aiScanIsFullRescan)
                                controller.cancelAiScan()
                            else
                                controller.aiScanFolder(model.folderId)
                        }
                    }

                    Button {
                        objectName: "expertAiFullRescanButton"
                        flat: true
                        visible: foldersPanel.expertMode && controller && controller.aiEnabled
                        text: (controller && controller.isAiScanning
                               && controller.aiScanFolderId === model.folderId
                               && controller.aiScanIsFullRescan)
                              ? qsTr("Cancel AI Full Scan")
                              : qsTr("AI Full Scan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        enabled: model.enabled && model.imageCount > 0 &&
                                 (!controller || !controller.folderWorkflowRunning) &&
                                 (!controller || !controller.isAiScanning
                                  || (controller.aiScanFolderId === model.folderId
                                      && controller.aiScanIsFullRescan))
                        ToolTip.text: (controller && controller.isAiScanning
                                       && controller.aiScanFolderId === model.folderId
                                       && controller.aiScanIsFullRescan)
                                      ? qsTr("Cancel the running AI full scan")
                                      : qsTr("Rebuild every CLIP vector embedding for this folder from scratch")
                        ToolTip.visible: hovered
                        onClicked: {
                            if (!controller)
                                return
                            if (controller.isAiScanning
                                    && controller.aiScanFolderId === model.folderId
                                    && controller.aiScanIsFullRescan)
                                controller.cancelAiScan()
                            else
                                controller.aiFullRescanFolder(model.folderId)
                        }
                    }

                    // Clear Previews button — kept in layout (transparent when nothing cached)
                    // so the Remove button stays aligned across rows.
                    Button {
                        objectName: "expertClearPreviewsButton"
                        flat: true
                        visible: foldersPanel.expertMode
                        text: qsTr("Clear Previews")
                        font.pixelSize: 11
                        implicitHeight: 30
                        opacity: model.previewCachedCount > 0 ? 1.0 : 0.0
                        enabled: model.previewCachedCount > 0 &&
                                 (!controller || !controller.folderWorkflowRunning) &&
                                 (!controller || !controller.isBuildingPreviews
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
                        objectName: "removeFolderButton"
                        flat: true
                        text: qsTr("Remove")
                        font.pixelSize: 11
                        implicitHeight: 30
                        Material.foreground: Material.Red
                        enabled: !controller || (!controller.folderWorkflowRunning &&
                                 !controller.isBusy && !controller.isIndexing &&
                                 !controller.isBuildingPreviews && !controller.isAiScanning)
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

        // ── Bottom pane: activity / progress ─────────────────────────────
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

                // Reusable progress column for each folder workflow stage
                component ProgressColumn: Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 1
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
                    property string progressPrefix: ""
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
                            elide: Text.ElideMiddle
                        }

                        ProgressBar {
                            Layout.fillWidth: true
                            from: 0
                            to: total > 0 ? total : 1
                            value: active ? current : 0
                            indeterminate: active && total === 0
                            opacity: active ? 1.0 : 0.35
                        }

                        Label {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.fillWidth: true
                            text: active
                                ? (progressPrefix ? progressPrefix + ": " : "")
                                + (total > 0
                                   ? current + " / " + total
                                   : (current > 0 ? current + " " + qsTr("done\u2026") : qsTr("Preparing\u2026")))
                                  : qsTr("Idle")
                            font.pixelSize: 11
                            opacity: 0.7
                            horizontalAlignment: Text.AlignHCenter
                            elide: Text.ElideMiddle
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
                    title: qsTr("Refresh Tags")
                    active: controller ? controller.isRefreshingTags : false
                    current: controller ? controller.refreshTagsCurrent : 0
                    total: controller ? controller.refreshTagsTotal : 0
                    currentFile: controller ? controller.refreshTagsCurrentFile : ""
                    progressPrefix: controller ? controller.refreshTagsFolderName : ""
                    cancelText: qsTr("Cancel")
                    canceling: false
                    onCancelRequested: controller.cancelRefreshTags()
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

                ProgressColumn {
                    title: qsTr("AI-Scan")
                    active: controller ? controller.isAiScanning : false
                    current: controller ? controller.aiScanCurrent : 0
                    total: controller ? controller.aiScanTotal : 0
                    currentFile: controller ? controller.aiScanCurrentFile : ""
                    cancelText: qsTr("Cancel")
                    canceling: false
                    onCancelRequested: controller.cancelAiScan()
                }
            }
        }
    }
}
