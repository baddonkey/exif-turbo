import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: root
    width: 1200
    height: 800
    title: "Exif-Turbo 1.0"

    Material.theme: Material.Light
    Material.accent: Material.Blue
    Material.primary: Material.Blue

    Component.onCompleted: {
        showMaximized()
        controller.search("")
    }

    // ── Keyboard shortcuts ────────────────────────────────────────────────
    Shortcut {
        sequence: StandardKey.Find
        onActivated: {
            findBarVisible = !findBarVisible
            if (findBarVisible) {
                findField.forceActiveFocus()
                findField.selectAll()
            }
        }
    }
    Shortcut {
        sequence: StandardKey.FindNext
        onActivated: controller.findNext(findField.text)
    }
    Shortcut {
        sequence: StandardKey.FindPrevious
        onActivated: controller.findPrev(findField.text)
    }

    property bool findBarVisible: false

    // ── Dialogs ───────────────────────────────────────────────────────────
    FolderDialog {
        id: folderDialog
        title: "Select folder to index"
        onAccepted: controller.startIndexing(selectedFolder.toString())
    }

    FileDialog {
        id: saveDialog
        title: "Save CSV"
        fileMode: FileDialog.SaveFile
        nameFilters: ["CSV Files (*.csv)"]
        defaultSuffix: "csv"
        onAccepted: controller.exportCsv(selectedFile.toString())
    }

    // ── Header toolbar ────────────────────────────────────────────────────
    header: ToolBar {
        Material.background: "#1565c0"
        height: 56

        RowLayout {
            anchors {
                left: parent.left
                right: parent.right
                verticalCenter: parent.verticalCenter
                margins: 10
            }
            spacing: 8

            TextField {
                id: searchField
                Layout.fillWidth: true
                placeholderText: "Full-text search  (e.g. camera:Canon lens:50mm)"
                font.pointSize: 12
                Material.accent: Material.White
                color: "#1f2a44"
                background: Rectangle {
                    radius: 8
                    color: "#ffffff"
                    border.color: "#d6dde8"
                }
                leftPadding: 12
                rightPadding: 12
                Keys.onReturnPressed: controller.search(text)
            }

            Button {
                icon.source: "../../assets/lense.svg"
                icon.width: 22
                icon.height: 22
                flat: false
                Material.background: "#1976d2"
                Material.foreground: "#ffffff"
                onClicked: controller.search(searchField.text)
                ToolTip.text: "Search"
                ToolTip.visible: hovered
                implicitHeight: 44
                implicitWidth: 64
            }

            Button {
                text: "Index Folders"
                visible: !controller.isIndexing
                Material.background: "#1976d2"
                Material.foreground: "#ffffff"
                implicitHeight: 44
                onClicked: folderDialog.open()
            }

            Button {
                text: "Cancel Index"
                visible: controller.isIndexing
                Material.background: "#e53935"
                Material.foreground: "#ffffff"
                implicitHeight: 44
                onClicked: controller.cancelIndex()
            }

            Button {
                text: "Build Thumbs"
                visible: !controller.isBuildingThumbs
                Material.background: "#1976d2"
                Material.foreground: "#ffffff"
                implicitHeight: 44
                onClicked: controller.buildThumbnails()
            }

            Button {
                text: "Cancel Thumbs"
                visible: controller.isBuildingThumbs
                Material.background: "#e53935"
                Material.foreground: "#ffffff"
                implicitHeight: 44
                onClicked: controller.cancelThumbnails()
            }

            Button {
                text: "Export CSV"
                Material.background: "#1976d2"
                Material.foreground: "#ffffff"
                implicitHeight: 44
                onClicked: saveDialog.open()
            }
        }
    }

    // ── Main content ──────────────────────────────────────────────────────
    SplitView {
        id: mainSplit
        anchors.fill: parent
        orientation: Qt.Vertical
        handle: Rectangle {
            implicitHeight: 6
            color: SplitHandle.pressed ? "#b0bec5" : "#e6ecf5"
        }

        // Top row: results list + image preview
        SplitView {
            id: topSplit
            orientation: Qt.Horizontal
            SplitView.fillHeight: true
            SplitView.minimumHeight: 180
            handle: Rectangle {
                implicitWidth: 6
                color: SplitHandle.pressed ? "#b0bec5" : "#e6ecf5"
            }

            // ── Results list ──────────────────────────────────────────────
            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 280
                color: "#ffffff"
                border.color: "#d6dde8"
                radius: 6
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Column headers
                    Rectangle {
                        Layout.fillWidth: true
                        height: 36
                        color: "#f0f4fa"
                        radius: 6

                        RowLayout {
                            anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                            spacing: 0

                            Label {
                                text: "Preview"
                                Layout.preferredWidth: 158
                                font.pointSize: 10
                                color: "#5a6b86"
                                font.weight: Font.Medium
                            }
                            Label {
                                text: "File"
                                Layout.preferredWidth: 210
                                font.pointSize: 10
                                color: "#5a6b86"
                                font.weight: Font.Medium
                            }
                            Label {
                                text: "Path"
                                Layout.fillWidth: true
                                font.pointSize: 10
                                color: "#5a6b86"
                                font.weight: Font.Medium
                            }
                        }
                    }

                    ListView {
                        id: resultsList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: searchModel
                        currentIndex: -1
                        ScrollBar.vertical: ScrollBar {}

                        delegate: Rectangle {
                            id: delegateRoot
                            width: resultsList.width
                            height: 154
                            color: ListView.isCurrentItem ? "#dbeafe"
                                 : (index % 2 === 0 ? "#ffffff" : "#f8faff")

                            RowLayout {
                                anchors { fill: parent; margins: 5 }
                                spacing: 8

                                Image {
                                    Layout.preferredWidth: 144
                                    Layout.preferredHeight: 144
                                    source: model.thumbnailSource
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    asynchronous: true
                                }

                                Label {
                                    text: model.filename
                                    Layout.preferredWidth: 200
                                    Layout.fillHeight: true
                                    verticalAlignment: Text.AlignVCenter
                                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                                    font.pointSize: 11
                                    color: "#1f2a44"
                                }

                                Label {
                                    text: model.path
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    verticalAlignment: Text.AlignVCenter
                                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                                    font.pointSize: 10
                                    color: "#5a6b86"
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton
                                onClicked: {
                                    resultsList.currentIndex = index
                                    controller.selectResult(index)
                                }
                                // path column starts at ~5+144+8+200+8 = 365px
                                onDoubleClicked: (mouse) => {
                                    if (mouse.x > 365) {
                                        controller.openFolder(model.path)
                                    } else {
                                        controller.openImage(model.path)
                                    }
                                }
                            }
                        }

                        onAtYEndChanged: {
                            if (atYEnd && count > 0) {
                                controller.loadMore()
                            }
                        }
                    }
                }
            }

            // ── Preview pane ──────────────────────────────────────────────
            Rectangle {
                SplitView.preferredWidth: 380
                SplitView.minimumWidth: 180
                color: "#ffffff"
                border.color: "#d6dde8"
                radius: 6
                clip: true

                Image {
                    anchors { fill: parent; margins: 8 }
                    source: controller.selectedImageSource
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    asynchronous: true
                    cache: false
                }
            }
        }

        // Bottom row: details text + EXIF table
        SplitView {
            id: bottomSplit
            orientation: Qt.Horizontal
            SplitView.preferredHeight: 280
            SplitView.minimumHeight: 90
            handle: Rectangle {
                implicitWidth: 6
                color: SplitHandle.pressed ? "#b0bec5" : "#e6ecf5"
            }

            // ── Details text ──────────────────────────────────────────────
            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 200
                color: "#ffffff"
                border.color: "#d6dde8"
                radius: 6
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 4

                    // Find bar (shown with Ctrl+F)
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.findBarVisible
                        spacing: 6

                        Label {
                            text: "Find"
                            font.pointSize: 11
                            color: "#4b5b78"
                        }

                        TextField {
                            id: findField
                            Layout.fillWidth: true
                            placeholderText: "Find in details"
                            font.pointSize: 11
                            Keys.onReturnPressed: controller.findNext(text)
                        }

                        Button {
                            text: "▲"
                            flat: true
                            implicitHeight: 36
                            implicitWidth: 36
                            font.pointSize: 10
                            onClicked: controller.findPrev(findField.text)
                            ToolTip.text: "Previous match"
                            ToolTip.visible: hovered
                        }

                        Button {
                            text: "▼"
                            flat: true
                            implicitHeight: 36
                            implicitWidth: 36
                            font.pointSize: 10
                            onClicked: controller.findNext(findField.text)
                            ToolTip.text: "Next match"
                            ToolTip.visible: hovered
                        }
                    }

                    // Details content
                    ScrollView {
                        id: detailsScrollView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        TextArea {
                            id: detailsArea
                            readOnly: true
                            textFormat: TextEdit.RichText
                            text: controller.detailsHtml
                            wrapMode: TextEdit.Wrap
                            font.family: "Consolas"
                            font.pointSize: 11
                            color: "#1f2a44"
                            placeholderText: "Select an image to see metadata"
                            background: null
                            padding: 0
                        }
                    }
                }

                Connections {
                    target: controller
                    function onFindScrollFractionChanged() {
                        var bar = detailsScrollView.ScrollBar.vertical
                        if (bar) {
                            bar.position = controller.findScrollFraction * (1.0 - bar.size)
                        }
                    }
                }
            }

            // ── EXIF key/value table ──────────────────────────────────────
            Rectangle {
                SplitView.preferredWidth: 380
                SplitView.minimumWidth: 180
                color: "#ffffff"
                border.color: "#d6dde8"
                radius: 6
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Column headers
                    Rectangle {
                        Layout.fillWidth: true
                        height: 32
                        color: "#f0f4fa"
                        radius: 6

                        RowLayout {
                            anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
                            spacing: 0

                            Label {
                                text: "Tag"
                                Layout.preferredWidth: parent.width * 0.42
                                font.pointSize: 10
                                color: "#5a6b86"
                                font.weight: Font.Medium
                            }
                            Label {
                                text: "Value"
                                Layout.fillWidth: true
                                font.pointSize: 10
                                color: "#5a6b86"
                                font.weight: Font.Medium
                            }
                        }
                    }

                    ListView {
                        id: exifList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: exifModel
                        ScrollBar.vertical: ScrollBar {}

                        delegate: Rectangle {
                            width: exifList.width
                            height: 32
                            color: index % 2 === 0 ? "#ffffff" : "#f8faff"

                            RowLayout {
                                anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
                                spacing: 8

                                Label {
                                    text: model.tag
                                    Layout.preferredWidth: exifList.width * 0.42 - 16
                                    font.pointSize: 10
                                    elide: Text.ElideRight
                                    color: "#1f2a44"
                                    ToolTip.text: model.tag
                                    ToolTip.visible: hovered && truncated
                                }
                                Label {
                                    text: model.value
                                    Layout.fillWidth: true
                                    font.pointSize: 10
                                    elide: Text.ElideRight
                                    color: "#4b5b78"
                                    ToolTip.text: model.value
                                    ToolTip.visible: hovered && truncated
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ── Status bar ────────────────────────────────────────────────────────
    footer: Rectangle {
        height: 28
        color: "#f0f4fa"
        border.color: "#d6dde8"

        Label {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 12 }
            text: controller.statusText
            font.pointSize: 10
            color: "#5a6b86"
        }
    }
}
