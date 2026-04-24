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
    }

    // ── Keyboard shortcuts ────────────────────────────────────────────────
    Shortcut {
        sequences: [ StandardKey.Find ]
        onActivated: {
            findBarVisible = !findBarVisible
            if (findBarVisible) {
                findField.forceActiveFocus()
                findField.selectAll()
            }
        }
    }
    Shortcut {
        sequences: [ StandardKey.FindNext ]
        onActivated: controller.findNext(findField.text)
    }
    Shortcut {
        sequences: [ StandardKey.FindPrevious ]
        onActivated: controller.findPrev(findField.text)
    }

    property bool findBarVisible: false
    property bool _pendingFullReindex: false

    // Null-safe proxies — shield child bindings from the transient null window
    // that occurs while the QML engine resolves context properties on startup.
    readonly property bool _isLocked:           controller ? controller.isLocked           : true
    readonly property bool _isIndexing:         controller ? controller.isIndexing         : false
    readonly property bool _isBuildingThumbs:   controller ? controller.isBuildingThumbs   : false
    readonly property string _unlockError:      controller ? controller.unlockError        : ""
    readonly property string _statusText:       controller ? controller.statusText         : ""
    readonly property int    _indexCurrent:     controller ? controller.indexCurrent       : 0
    readonly property int    _indexTotal:       controller ? controller.indexTotal         : 0
    readonly property string _indexCurrentFile: controller ? controller.indexCurrentFile   : ""
    readonly property int    _thumbCurrent:     controller ? controller.thumbCurrent       : 0
    readonly property int    _thumbTotal:       controller ? controller.thumbTotal         : 0
    readonly property string _thumbCurrentFile: controller ? controller.thumbCurrentFile   : ""
    readonly property string _selectedImageSource: controller ? controller.selectedImageSource : ""
    readonly property string _detailsHtml:      controller ? controller.detailsHtml        : ""

    // ── Dialogs ─────────────────────────────────────────────────────
    FolderDialog {
        id: folderDialog
        title: _pendingFullReindex ? "Select folder — Full Re-index" : "Select folder to index"
        onAccepted: {
            if (_pendingFullReindex) {
                _pendingFullReindex = false
                controller.startFullReindex(selectedFolder.toString())
            } else {
                controller.startIndexing(selectedFolder.toString())
            }
        }
        onRejected: _pendingFullReindex = false
    }

    FileDialog {
        id: saveDialog
        title: "Save CSV"
        fileMode: FileDialog.SaveFile
        nameFilters: ["CSV Files (*.csv)"]
        defaultSuffix: "csv"
        onAccepted: controller.exportCsv(selectedFile.toString())
    }

    // ── Header toolbar (hidden when locked) ───────────────────────────────
    header: ToolBar {
        Material.background: "#1565c0"
        implicitHeight: _isLocked ? 0 : 64
        visible: !_isLocked

        RowLayout {
            anchors {
                left: parent.left
                right: parent.right
                verticalCenter: parent.verticalCenter
                margins: 10
            }
            spacing: 8
            enabled: !_isIndexing && !_isBuildingThumbs

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 44
                radius: 8
                color: "#ffffff"
                border.color: searchField.activeFocus ? "#90caf9" : "#d6dde8"
                border.width: searchField.activeFocus ? 2 : 1

                Label {
                    anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                    visible: searchField.text.length === 0
                    text: "Full-text search  (e.g. camera:Canon lens:50mm)"
                    color: "#9aaab8"
                    font.pointSize: 12
                }

                TextInput {
                    id: searchField
                    anchors {
                        left: parent.left; right: parent.right
                        leftMargin: 12; rightMargin: 12
                        verticalCenter: parent.verticalCenter
                    }
                    font.pointSize: 12
                    color: "#1f2a44"
                    selectedTextColor: "#ffffff"
                    selectionColor: "#1976d2"
                    clip: true
                    Keys.onReturnPressed: controller.search(text)
                }
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
                Material.background: "#1976d2"
                Material.foreground: "#ffffff"
                implicitHeight: 44
                onClicked: {
                    _pendingFullReindex = false
                    folderDialog.open()
                }
            }

            Button {
                text: "Full Re-index"
                Material.background: "#6a1b9a"
                Material.foreground: "#ffffff"
                implicitHeight: 44
                ToolTip.text: "Re-extract EXIF for every file, ignoring the existing index"
                ToolTip.visible: hovered
                onClicked: {
                    _pendingFullReindex = true
                    folderDialog.open()
                }
            }

            Button {
                text: "Build Thumbs"
                visible: !_isBuildingThumbs
                Material.background: "#1976d2"
                Material.foreground: "#ffffff"
                implicitHeight: 44
                onClicked: controller.buildThumbnails()
            }

            Button {
                text: "Cancel Thumbs"
                visible: _isBuildingThumbs
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

    // ── Password / lock screen ────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: "#f5f7fb"
        visible: _isLocked
        z: 100

        Column {
            anchors.centerIn: parent
            spacing: 18
            width: 360

            Label {
                text: "Exif-Turbo"
                font.pointSize: 26
                font.weight: Font.Bold
                color: "#1565c0"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Label {
                text: "Enter the database password"
                font.pointSize: 13
                color: "#4b5b78"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            TextField {
                id: passwordField
                width: parent.width
                placeholderText: "Password"
                echoMode: TextInput.Password
                font.pointSize: 13
                Keys.onReturnPressed: controller.unlock(text)
                Component.onCompleted: forceActiveFocus()
            }

            Label {
                text: _unlockError
                color: "#c62828"
                font.pointSize: 11
                visible: _unlockError !== ""
                wrapMode: Text.WordWrap
                width: parent.width
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Button {
                text: "Unlock"
                width: parent.width
                implicitHeight: 44
                Material.background: "#1976d2"
                Material.foreground: "#ffffff"
                font.pointSize: 13
                anchors.horizontalCenter: parent.horizontalCenter
                onClicked: controller.unlock(passwordField.text)
            }
        }
    }
    // ── Indexing progress overlay ─────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: "#aa000000"
        visible: _isIndexing
        z: 50

        Rectangle {
            anchors.centerIn: parent
            width: 480
            height: 250
            radius: 14
            color: "#ffffff"

            ColumnLayout {
                anchors { fill: parent; margins: 28 }
                spacing: 14

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Indexing Images"
                    font.pointSize: 16
                    font.weight: Font.Medium
                    color: "#1f2a44"
                }

                ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: _indexTotal > 0 ? _indexTotal : 1
                    value: _indexCurrent
                    indeterminate: _indexTotal === 0
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: _indexTotal > 0
                          ? _indexCurrent + " / " + _indexTotal + " files"
                          : "Scanning for images…"
                    font.pointSize: 12
                    color: "#4b5b78"
                }

                Label {
                    Layout.fillWidth: true
                    text: _indexCurrentFile
                    font.pointSize: 10
                    color: "#8a9ab8"
                    elide: Text.ElideMiddle
                    horizontalAlignment: Text.AlignHCenter
                }

                Button {
                    Layout.alignment: Qt.AlignHCenter
                    text: _statusText.indexOf("Cancel") >= 0 ? "Canceling…" : "Cancel"
                    enabled: _statusText.indexOf("Cancel") < 0
                    Material.background: "#e53935"
                    Material.foreground: "#ffffff"
                    implicitHeight: 40
                    implicitWidth: 140
                    onClicked: controller.cancelIndex()
                }
            }
        }
    }
    // ── Thumbnail progress overlay ───────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: "#aa000000"
        visible: _isBuildingThumbs
        z: 50

        Rectangle {
            anchors.centerIn: parent
            width: 480
            height: 250
            radius: 14
            color: "#ffffff"

            ColumnLayout {
                anchors { fill: parent; margins: 28 }
                spacing: 14

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Building Thumbnails"
                    font.pointSize: 16
                    font.weight: Font.Medium
                    color: "#1f2a44"
                }

                ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: _thumbTotal > 0 ? _thumbTotal : 1
                    value: _thumbCurrent
                    indeterminate: _thumbTotal === 0
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: _thumbTotal > 0
                          ? _thumbCurrent + " / " + _thumbTotal + " images"
                          : "Preparing…"
                    font.pointSize: 12
                    color: "#4b5b78"
                }

                Label {
                    Layout.fillWidth: true
                    text: _thumbCurrentFile
                    font.pointSize: 10
                    color: "#8a9ab8"
                    elide: Text.ElideMiddle
                    horizontalAlignment: Text.AlignHCenter
                }

                Button {
                    Layout.alignment: Qt.AlignHCenter
                    text: _statusText.indexOf("Cancel") >= 0 ? "Canceling…" : "Cancel"
                    enabled: _statusText.indexOf("Cancel") < 0
                    Material.background: "#e53935"
                    Material.foreground: "#ffffff"
                    implicitHeight: 40
                    implicitWidth: 140
                    onClicked: controller.cancelThumbnails()
                }
            }
        }
    }

    // ── Main content ──────────────────────────────────────────────────────
    SplitView {
        id: mainSplit
        anchors.fill: parent
        visible: !_isLocked
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
                    source: _selectedImageSource
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
                            text: _detailsHtml
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
                                    id: tagLabel
                                    text: model.tag
                                    Layout.preferredWidth: exifList.width * 0.42 - 16
                                    font.pointSize: 10
                                    elide: Text.ElideRight
                                    color: "#1f2a44"
                                    ToolTip.text: model.tag
                                    ToolTip.visible: (tagHover ? tagHover.hovered : false) && truncated
                                    HoverHandler { id: tagHover }
                                }
                                Label {
                                    id: valueLabel
                                    text: model.value
                                    Layout.fillWidth: true
                                    font.pointSize: 10
                                    elide: Text.ElideRight
                                    color: "#4b5b78"
                                    ToolTip.text: model.value
                                    ToolTip.visible: (valueHover ? valueHover.hovered : false) && truncated
                                    HoverHandler { id: valueHover }
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
        height: _isLocked ? 0 : 28
        visible: !_isLocked
        color: "#f0f4fa"
        border.color: "#d6dde8"

        Label {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 12 }
            text: _statusText
            font.pointSize: 10
            color: "#5a6b86"
        }
    }
}
