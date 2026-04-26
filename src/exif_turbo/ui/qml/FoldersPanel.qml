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

    // ── FolderDialog for adding managed folders ───────────────────────────
    FolderDialog {
        id: addFolderDialog
        title: qsTr("Select Folder to Manage")
        onAccepted: controller.addIndexedFolder(selectedFolder.toString())
    }

    // ── Layout ────────────────────────────────────────────────────────────
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
                anchors.fill: parent
                clip: true
                model: folderListModel
                ScrollBar.vertical: ScrollBar {}

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

                        // Status badge
                        Rectangle {
                            height: 18
                            width: statusLabel.implicitWidth + 12
                            radius: 9
                            color: Qt.alpha(foldersPanel.statusColor(model.status), 0.18)

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
                    }

                    // Rescan button
                    Button {
                        flat: true
                        text: qsTr("Rescan")
                        font.pixelSize: 11
                        implicitHeight: 30
                        implicitWidth: 72
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
                        implicitWidth: 84
                        enabled: model.enabled && model.status !== "scanning"
                        ToolTip.text: qsTr("Force re-extract EXIF for every file in this folder")
                        ToolTip.visible: hovered
                        onClicked: controller.fullRescanFolder(model.folderId)
                    }

                    // Remove button
                    Button {
                        flat: true
                        text: qsTr("Remove")
                        font.pixelSize: 11
                        implicitHeight: 30
                        implicitWidth: 72
                        Material.foreground: Material.Red
                        ToolTip.text: qsTr("Remove this folder and delete its indexed images")
                        ToolTip.visible: hovered
                        onClicked: removeConfirmDialog.open()

                        Dialog {
                            id: removeConfirmDialog
                            title: qsTr("Remove Folder")
                            standardButtons: Dialog.Ok | Dialog.Cancel
                            anchors.centerIn: Overlay.overlay
                            width: 420
                            Label {
                                text: qsTr("Remove \"%1\" and delete all its indexed images from the database?").arg(model.displayName)
                                wrapMode: Text.WordWrap
                                width: 340
                            }
                            onAccepted: controller.removeIndexedFolder(model.folderId)
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
