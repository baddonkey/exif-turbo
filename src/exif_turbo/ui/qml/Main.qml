import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: root
    width: 1200
    height: 800
    minimumWidth: 900
    minimumHeight: 600
    title: "exif-turbo"

    Material.theme: Material.System
    Material.accent: Material.Blue
    Material.primary: Material.Blue

    // Resolved accent colour — safe to use from bare Rectangle children.
    readonly property color _accentColor: Material.accentColor
    readonly property string monoFont: Qt.platform.os === "osx" ? "Menlo" : "Consolas"

    Component.onCompleted: showMaximized()

    // ── Keyboard shortcuts ────────────────────────────────────────────────
    Shortcut {
        sequences: [ StandardKey.Find ]
        onActivated: {
            findBarVisible = !findBarVisible
            if (findBarVisible) { findField.forceActiveFocus(); findField.selectAll() }
        }
    }
    Shortcut { sequences: [ StandardKey.FindNext ];     onActivated: controller.findNext(findField.text) }
    Shortcut { sequences: [ StandardKey.FindPrevious ]; onActivated: controller.findPrev(findField.text) }

    property bool findBarVisible: false
    property bool _pendingFullReindex: false

    // ── Null-safe proxies ─────────────────────────────────────────────────
    readonly property bool   _isLocked:            controller ? controller.isLocked           : true
    readonly property bool   _isIndexing:          controller ? controller.isIndexing         : false
    readonly property bool   _isBuildingThumbs:    controller ? controller.isBuildingThumbs   : false
    readonly property string _unlockError:         controller ? controller.unlockError        : ""
    readonly property string _statusText:          controller ? controller.statusText         : ""
    readonly property int    _indexCurrent:        controller ? controller.indexCurrent       : 0
    readonly property int    _indexTotal:          controller ? controller.indexTotal         : 0
    readonly property string _indexCurrentFile:    controller ? controller.indexCurrentFile   : ""
    readonly property int    _thumbCurrent:        controller ? controller.thumbCurrent       : 0
    readonly property int    _thumbTotal:          controller ? controller.thumbTotal         : 0
    readonly property string _thumbCurrentFile:    controller ? controller.thumbCurrentFile   : ""
    readonly property string _selectedImageSource: controller ? controller.selectedImageSource : ""
    readonly property string _detailsHtml:         controller ? controller.detailsHtml        : ""
    readonly property string _sortBy:             controller ? controller.sortBy             : ""
    readonly property string _extFilter:          controller ? controller.extFilter          : ""
    readonly property string _availableFormats:   controller ? controller.availableFormats   : "[]"
    readonly property string _folderTreeJson:     controller ? controller.folderTree         : "[]"
    readonly property string _folderFilter:       controller ? controller.folderFilter       : ""

    // Parsed format list — updated reactively when _availableFormats changes
    readonly property var _formats: {
        try { return JSON.parse(_availableFormats) } catch(e) { return [] }
    }

    // Parsed folder tree — updated reactively when _folderTreeJson changes
    readonly property var _folderTree: {
        try { return JSON.parse(_folderTreeJson) } catch(e) { return [] }
    }

    // ── Dialogs ───────────────────────────────────────────────────────────
    FolderDialog {
        id: folderDialog
        title: _pendingFullReindex ? qsTr("Select Folder — Full Re-index") : qsTr("Select Folder to Index")
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

    Dialog {
        id: aboutDialog
        title: qsTr("About exif-turbo")
        standardButtons: Dialog.Ok
        anchors.centerIn: Overlay.overlay

        Label {
            text: "exif-turbo\n\nCross-platform image EXIF metadata\nsearch and indexing tool.\n\nLicense: MIT"
        }
    }

    // ── Menu bar ──────────────────────────────────────────────────────────
    menuBar: MenuBar {
        Menu {
            title: qsTr("&File")
            Action {
                text: qsTr("E&xit")
                shortcut: "Ctrl+Q"
                onTriggered: Qt.quit()
            }
        }
        Menu {
            title: qsTr("&Help")
            Action {
                text: qsTr("&About")
                onTriggered: aboutDialog.open()
            }
        }
    }

    // ── Toolbar (hidden when locked) ──────────────────────────────────────
    header: ToolBar {
        implicitHeight: _isLocked ? 0 : 56
        visible: !_isLocked

        RowLayout {
            anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
            spacing: 6
            enabled: !_isIndexing && !_isBuildingThumbs

            // Search field
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 38
                radius: 4
                color: Qt.rgba(1, 1, 1, 0.15)
                border.color: searchField.activeFocus ? Qt.rgba(1, 1, 1, 0.85) : Qt.rgba(1, 1, 1, 0.3)
                border.width: 1

                Label {
                    anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                    visible: searchField.text.length === 0
                    text: qsTr("Search EXIF metadata\u2026")
                    color: Qt.rgba(1, 1, 1, 0.5)
                    font.pixelSize: 13
                }

                TextInput {
                    id: searchField
                    anchors { left: parent.left; right: parent.right; leftMargin: 10; rightMargin: 10; verticalCenter: parent.verticalCenter }
                    font.pixelSize: 13
                    color: "white"
                    selectedTextColor: "#0d47a1"
                    selectionColor: Qt.rgba(1, 1, 1, 0.85)
                    clip: true
                    Keys.onReturnPressed: controller.search(text)
                }
            }

            Button {
                flat: true
                text: qsTr("Search")
                Material.foreground: "white"
                implicitHeight: 38
                onClicked: controller.search(searchField.text)
            }

            ToolSeparator {}

            Button {
                flat: true
                text: qsTr("Index")
                Material.foreground: "white"
                implicitHeight: 38
                ToolTip.text: qsTr("Index a folder (incremental)")
                ToolTip.visible: hovered
                onClicked: { _pendingFullReindex = false; folderDialog.open() }
            }

            Button {
                flat: true
                text: qsTr("Re-index")
                Material.foreground: "white"
                implicitHeight: 38
                ToolTip.text: qsTr("Re-extract EXIF for every file, ignoring the existing index")
                ToolTip.visible: hovered
                onClicked: { _pendingFullReindex = true; folderDialog.open() }
            }

            ToolSeparator {}

            Button {
                flat: true
                text: _isBuildingThumbs ? qsTr("Cancel Thumbs") : qsTr("Create Thumbs")
                Material.foreground: "white"
                implicitHeight: 38
                enabled: !_isIndexing
                ToolTip.text: _isBuildingThumbs
                    ? qsTr("Cancel thumbnail generation")
                    : qsTr("Generate thumbnails for all indexed images (skip existing)")
                ToolTip.visible: hovered
                onClicked: _isBuildingThumbs ? controller.cancelThumbnails() : controller.buildThumbnails()
            }

            Button {
                flat: true
                text: qsTr("Recreate Thumbs")
                Material.foreground: "white"
                implicitHeight: 38
                enabled: !_isIndexing && !_isBuildingThumbs
                ToolTip.text: qsTr("Delete all cached thumbnails and regenerate from scratch")
                ToolTip.visible: hovered
                onClicked: controller.recreateThumbnails()
            }
        }
    }

    // ── Lock screen ───────────────────────────────────────────────────────
    Pane {
        anchors.fill: parent
        visible: _isLocked
        z: 100

        Pane {
            anchors.centerIn: parent
            width: 360
            padding: 28
            Material.elevation: 4

            ColumnLayout {
                anchors.fill: parent
                spacing: 16

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "exif-turbo"
                    font.pixelSize: 28
                    font.weight: Font.Bold
                    color: Material.accent
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: qsTr("Enter the database password")
                    font.pixelSize: 14
                    opacity: 0.7
                }

                TextField {
                    id: passwordField
                    Layout.fillWidth: true
                    placeholderText: qsTr("Password")
                    echoMode: TextInput.Password
                    font.pixelSize: 14
                    Keys.onReturnPressed: controller.unlock(text)
                    Component.onCompleted: forceActiveFocus()
                }

                Label {
                    Layout.fillWidth: true
                    text: _unlockError
                    color: "#f44336"
                    font.pixelSize: 12
                    visible: _unlockError !== ""
                    wrapMode: Text.WordWrap
                }

                Button {
                    Layout.fillWidth: true
                    text: qsTr("Unlock")
                    highlighted: true
                    implicitHeight: 44
                    font.pixelSize: 14
                    onClicked: controller.unlock(passwordField.text)
                }
            }
        }
    }

    // ── Indexing progress overlay ─────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.55)
        visible: _isIndexing
        z: 50

        Pane {
            anchors.centerIn: parent
            width: 480
            padding: 24
            Material.elevation: 8

            ColumnLayout {
                anchors.fill: parent
                spacing: 14

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: qsTr("Indexing Images")
                    font.pixelSize: 18
                    font.weight: Font.Medium
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
                          : qsTr("Scanning for images\u2026")
                    font.pixelSize: 13
                    opacity: 0.7
                }

                Label {
                    Layout.fillWidth: true
                    text: _indexCurrentFile
                    font.pixelSize: 11
                    opacity: 0.5
                    elide: Text.ElideMiddle
                    horizontalAlignment: Text.AlignHCenter
                }

                Button {
                    Layout.alignment: Qt.AlignHCenter
                    text: _statusText.indexOf("Cancel") >= 0 ? qsTr("Canceling\u2026") : qsTr("Cancel")
                    enabled: _statusText.indexOf("Cancel") < 0
                    highlighted: true
                    Material.accent: Material.Red
                    implicitHeight: 40
                    implicitWidth: 140
                    onClicked: controller.cancelIndex()
                }
            }
        }
    }

    // ── Thumbnail progress overlay ────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.55)
        visible: _isBuildingThumbs
        z: 50

        Pane {
            anchors.centerIn: parent
            width: 480
            padding: 24
            Material.elevation: 8

            ColumnLayout {
                anchors.fill: parent
                spacing: 14

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: qsTr("Building Thumbnails")
                    font.pixelSize: 18
                    font.weight: Font.Medium
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
                          : qsTr("Preparing\u2026")
                    font.pixelSize: 13
                    opacity: 0.7
                }

                Label {
                    Layout.fillWidth: true
                    text: _thumbCurrentFile
                    font.pixelSize: 11
                    opacity: 0.5
                    elide: Text.ElideMiddle
                    horizontalAlignment: Text.AlignHCenter
                }

                Button {
                    Layout.alignment: Qt.AlignHCenter
                    text: _statusText.indexOf("Cancel") >= 0 ? qsTr("Canceling\u2026") : qsTr("Cancel")
                    enabled: _statusText.indexOf("Cancel") < 0
                    highlighted: true
                    Material.accent: Material.Red
                    implicitHeight: 40
                    implicitWidth: 140
                    onClicked: controller.cancelThumbnails()
                }
            }
        }
    }

    // ── Tab bar background (full-width row behind the buttons) ───────────
    Rectangle {
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 40
        color: Material.background
        visible: !_isLocked
        z: 9
    }

    // ── Tab bar ───────────────────────────────────────────────────────────
    TabBar {
        id: mainTabBar
        anchors { top: parent.top; left: parent.left }
        width: 240   // 2 × 120 px — left-aligned, not stretched
        implicitHeight: 40
        visible: !_isLocked
        z: 10
        background: Item {}  // transparent; background rect above covers the row

        Repeater {
            model: [ qsTr("Search"), qsTr("Browse") ]
            TabButton {
                text: modelData
                implicitWidth: 120
                implicitHeight: 40

                background: Rectangle {
                    color: TabBar.tabBar && TabBar.tabBar.currentIndex === index
                           ? Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.14)
                           : "transparent"
                    radius: 0
                }

                contentItem: Label {
                    text: modelData
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 13
                    font.weight: TabBar.tabBar && TabBar.tabBar.currentIndex === index
                                 ? Font.DemiBold : Font.Normal
                    color: TabBar.tabBar && TabBar.tabBar.currentIndex === index
                           ? root._accentColor : Material.foreground
                    opacity: TabBar.tabBar && TabBar.tabBar.currentIndex === index ? 1.0 : 0.6
                }
            }
        }

        onCurrentIndexChanged: {
            if (currentIndex === 0) {
                // Returning to Search: clear folder filter and re-run last query
                controller.setFolderFilter("")
                controller.search(searchField.text)
            }
        }
    }

    // ── Search tab ───────────────────────────────────────────────────────
    SplitView {
        id: mainSplit
        anchors { top: mainTabBar.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        visible: !_isLocked && mainTabBar.currentIndex === 0
        orientation: Qt.Vertical
        handle: Rectangle {
            implicitHeight: 5
            color: SplitHandle.pressed ? root._accentColor : Material.dividerColor
        }

        // Top: results list + image preview
        SplitView {
            id: topSplit
            orientation: Qt.Horizontal
            SplitView.fillHeight: true
            SplitView.minimumHeight: 180
            handle: Rectangle {
                implicitWidth: 5
                color: SplitHandle.pressed ? root._accentColor : Material.dividerColor
            }

            // ── Results ───────────────────────────────────────────────────
            Rectangle {
                SplitView.preferredWidth: topSplit.width / 2
                SplitView.minimumWidth: 300
                color: Material.background
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Panel header
                    Rectangle {
                        Layout.fillWidth: true
                        height: 36
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.09)

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 6 }
                            spacing: 6

                            FloatingBadge { text: qsTr("RESULTS") }

                            Item { Layout.fillWidth: true }

                            Label {
                                text: qsTr("Sort")
                                font.pixelSize: 11
                                opacity: 0.6
                            }

                            ComboBox {
                                id: sortCombo
                                implicitHeight: 28
                                implicitWidth: 130
                                font.pixelSize: 11

                                readonly property var _opts: [
                                    { text: qsTr("Name A→Z"),      value: "filename_asc"  },
                                    { text: qsTr("Name Z→A"),      value: "filename_desc" },
                                    { text: qsTr("Path A→Z"),      value: "path_asc"      },
                                    { text: qsTr("Path Z→A"),      value: "path_desc"     },
                                    { text: qsTr("Newest first"),  value: "date_desc"     },
                                    { text: qsTr("Oldest first"),  value: "date_asc"      },
                                    { text: qsTr("Largest"),       value: "size_desc"     },
                                ]

                                model: _opts
                                textRole: "text"
                                valueRole: "value"
                                currentIndex: {
                                    var sv = root._sortBy
                                    for (var i = 0; i < _opts.length; i++) {
                                        if (_opts[i].value === sv) return i
                                    }
                                    return 2  // fallback: Path A→Z
                                }
                                onActivated: controller.setSortBy(sortCombo._opts[currentIndex].value)
                            }
                        }
                    }

                    // Format facet chips — hidden when only one format or none
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: root._formats.length > 1 ? 36 : 0
                        visible: root._formats.length > 1
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.04)

                        Flickable {
                            anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
                            contentWidth: chipRow.implicitWidth
                            flickableDirection: Flickable.HorizontalFlick
                            clip: true

                            Row {
                                id: chipRow
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 6

                                // "All" chip
                                Rectangle {
                                    height: 22
                                    width: allChipLabel.implicitWidth + 16
                                    radius: 11
                                    color: root._extFilter === ""
                                           ? root._accentColor
                                           : Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.15)

                                    Label {
                                        id: allChipLabel
                                        anchors.centerIn: parent
                                        text: qsTr("All")
                                        font.pixelSize: 11
                                        font.weight: root._extFilter === "" ? Font.DemiBold : Font.Normal
                                        color: root._extFilter === "" ? "white" : Material.foreground
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: controller.setExtFilter("")
                                    }
                                }

                                Repeater {
                                    model: root._formats
                                    delegate: Rectangle {
                                        height: 22
                                        width: fmtLabel.implicitWidth + 16
                                        radius: 11
                                        color: root._extFilter === modelData.ext
                                               ? root._accentColor
                                               : Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.15)

                                        Label {
                                            id: fmtLabel
                                            anchors.centerIn: parent
                                            text: modelData.ext.toUpperCase() + " \u00b7 " + modelData.count
                                            font.pixelSize: 11
                                            font.weight: root._extFilter === modelData.ext ? Font.DemiBold : Font.Normal
                                            color: root._extFilter === modelData.ext ? "white" : Material.foreground
                                        }

                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: controller.setExtFilter(modelData.ext)
                                        }
                                    }
                                }
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
                            id: cardDelegate
                            width: resultsList.width
                            height: 210
                            color: "transparent"

                            readonly property bool _isSelected: ListView.isCurrentItem

                            // Parse EXIF once per delegate instantiation
                            readonly property var _exif: {
                                try { return JSON.parse(model.metadataJson) } catch(e) { return {} }
                            }
                            readonly property string _camera: {
                                var make   = _exif["EXIF:Make"]   || _exif["IFD0:Make"]  || _exif["XMP:Make"]  || ""
                                var model2 = _exif["EXIF:Model"]  || _exif["IFD0:Model"] || _exif["XMP:Model"] || ""
                                if (make && model2) {
                                    return model2.startsWith(make) ? model2.trim() : (make + " " + model2).trim()
                                }
                                return (make || model2).trim()
                            }
                            readonly property string _date: {
                                var d = _exif["EXIF:DateTimeOriginal"] || _exif["EXIF:DateTime"] || _exif["IFD0:ModifyDate"] || ""
                                return d ? d.replace("T", " ").split(".")[0] : ""
                            }
                            readonly property string _dims: {
                                var w = _exif["EXIF:ExifImageWidth"]  || _exif["File:ImageWidth"]  || _exif["PNG:ImageWidth"]  || ""
                                var h = _exif["EXIF:ExifImageHeight"] || _exif["File:ImageHeight"] || _exif["PNG:ImageHeight"] || ""
                                return (w && h) ? (w + " × " + h) : ""
                            }
                            readonly property string _lens: {
                                var fl  = _exif["EXIF:FocalLength"] || ""
                                var fn  = _exif["EXIF:FNumber"]     || _exif["EXIF:ApertureValue"] || ""
                                var iso = _exif["EXIF:ISO"]         || _exif["EXIF:ISOSpeedRatings"] || ""
                                var parts = []
                                if (fl)  parts.push(fl + " mm")
                                if (fn)  parts.push("ƒ/" + fn)
                                if (iso) parts.push("ISO " + iso)
                                return parts.join("  ")
                            }
                            readonly property string _sizeText: {
                                var bytes = model.fileSize || 0
                                if (bytes <= 0)  return ""
                                if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB"
                                if (bytes >= 1048576)    return (bytes / 1048576).toFixed(1) + " MB"
                                return Math.round(bytes / 1024) + " KB"
                            }

                            // Card background with border
                            Rectangle {
                                anchors { fill: parent; leftMargin: 6; rightMargin: 6; topMargin: 3; bottomMargin: 3 }
                                radius: 7
                                color: _isSelected
                                       ? Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.12)
                                       : Material.background
                                border.color: _isSelected
                                              ? Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.45)
                                              : Material.dividerColor
                                border.width: 1
                            }

                            // Left selection accent bar
                            Rectangle {
                                x: 6; y: 12
                                width: 3
                                height: parent.height - 24
                                radius: 2
                                color: _isSelected ? root._accentColor : "transparent"
                            }

                            RowLayout {
                                anchors { fill: parent; leftMargin: 16; rightMargin: 14; topMargin: 10; bottomMargin: 10 }
                                spacing: 14

                                // Thumbnail
                                Image {
                                    Layout.preferredWidth: 182
                                    Layout.preferredHeight: 182
                                    source: model.thumbnailSource
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    asynchronous: true
                                }

                                // Info column
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 0

                                    // Filename
                                    Label {
                                        Layout.fillWidth: true
                                        text: model.filename
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }

                                    Item { height: 2 }

                                    // Full path — elide middle so both root and filename are hinted
                                    Label {
                                        Layout.fillWidth: true
                                        text: model.path
                                        font.pixelSize: 10
                                        font.family: root.monoFont
                                        opacity: 0.45
                                        elide: Text.ElideMiddle
                                    }

                                    Item { height: 8 }

                                    // Divider
                                    Rectangle {
                                        Layout.fillWidth: true
                                        height: 1
                                        color: Material.dividerColor
                                    }

                                    Item { height: 6 }

                                    // EXIF key-value rows
                                    Repeater {
                                        model: [
                                            { label: qsTr("Camera"),     value: _camera   },
                                            { label: qsTr("Date"),       value: _date      },
                                            { label: qsTr("Dimensions"), value: _dims      },
                                            { label: qsTr("Exposure"),   value: _lens      },
                                            { label: qsTr("File size"),  value: _sizeText  },
                                        ]
                                        delegate: RowLayout {
                                            visible: modelData.value !== ""
                                            Layout.fillWidth: true
                                            spacing: 8

                                            Label {
                                                text: modelData.label
                                                font.pixelSize: 10
                                                opacity: 0.45
                                                Layout.preferredWidth: 68
                                            }
                                            Label {
                                                text: modelData.value
                                                font.pixelSize: 11
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                            }
                                        }
                                    }

                                    Item { Layout.fillHeight: true }
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton
                                onClicked: {
                                    resultsList.currentIndex = index
                                    controller.selectResult(index)
                                }
                                onDoubleClicked: (mouse) => {
                                    if (mouse.x > 200) controller.openFolder(model.path)
                                    else               controller.openImage(model.path)
                                }
                            }
                        }

                        onAtYEndChanged: {
                            if (atYEnd && count > 0) controller.loadMore()
                        }
                    }
                }
            }

            // ── Preview ───────────────────────────────────────────────────
            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 200
                color: Material.background
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        height: 30
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.09)

                        FloatingBadge {
                            anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                            text: qsTr("PREVIEW")
                        }
                    }

                    Image {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        source: _selectedImageSource
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        asynchronous: true
                        cache: false
                    }
                }
            }
        }

        // Bottom: details text + EXIF table
        SplitView {
            id: bottomSplit
            orientation: Qt.Horizontal
            SplitView.preferredHeight: 280
            SplitView.minimumHeight: 90
            handle: Rectangle {
                implicitWidth: 5
                color: SplitHandle.pressed ? root._accentColor : Material.dividerColor
            }

            // ── Details ───────────────────────────────────────────────────
            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 200
                color: Material.background
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Panel header
                    Rectangle {
                        Layout.fillWidth: true
                        height: 30
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.09)

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 6 }
                            spacing: 4

                            FloatingBadge { text: qsTr("METADATA") }

                            Item { Layout.fillWidth: true }

                            Button {
                                flat: true
                                icon.name: "edit-find"
                                text: qsTr("Find")
                                font.pixelSize: 11
                                implicitHeight: 24
                                checkable: true
                                checked: root.findBarVisible
                                onClicked: {
                                    root.findBarVisible = !root.findBarVisible
                                    if (root.findBarVisible) { findField.forceActiveFocus(); findField.selectAll() }
                                }
                                ToolTip.text: qsTr("Find in metadata (Ctrl+F)")
                                ToolTip.visible: hovered
                            }
                        }
                    }

                    // Find bar row — below the header, not clipped by it
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: root.findBarVisible ? 42 : 0
                        visible: root.findBarVisible
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.05)

                        RowLayout {
                            anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
                            spacing: 4

                            TextField {
                                id: findField
                                Layout.fillWidth: true
                                implicitHeight: 32
                                placeholderText: qsTr("Find in metadata\u2026")
                                font.pixelSize: 12
                                Keys.onReturnPressed: controller.findNext(text)
                                Keys.onEscapePressed: root.findBarVisible = false
                            }

                            Button {
                                flat: true; text: "\u25b2"
                                implicitHeight: 32; implicitWidth: 32; font.pixelSize: 11
                                onClicked: controller.findPrev(findField.text)
                                ToolTip.text: qsTr("Previous match"); ToolTip.visible: hovered
                            }
                            Button {
                                flat: true; text: "\u25bc"
                                implicitHeight: 32; implicitWidth: 32; font.pixelSize: 11
                                onClicked: controller.findNext(findField.text)
                                ToolTip.text: qsTr("Next match"); ToolTip.visible: hovered
                            }
                        }
                    }

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
                            font.family: root.monoFont
                            font.pixelSize: 12
                            placeholderText: qsTr("Select an image to see metadata")
                            background: null
                            padding: 8
                        }
                    }
                }

                Connections {
                    target: controller
                    function onFindScrollFractionChanged() {
                        var bar = detailsScrollView.ScrollBar.vertical
                        if (bar) bar.position = controller.findScrollFraction * (1.0 - bar.size)
                    }
                }
            }

            // ── EXIF tags ─────────────────────────────────────────────────
            Rectangle {
                SplitView.preferredWidth: 380
                SplitView.minimumWidth: 180
                color: Material.background
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        height: 30
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.09)

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 10 }

                            FloatingBadge { text: qsTr("EXIF TAGS") }

                            Item { Layout.fillWidth: true }

                            Label { text: qsTr("Tag");   font.pixelSize: 10; opacity: 0.45; Layout.preferredWidth: exifList.width * 0.42 - 16 }
                            Label { text: qsTr("Value"); font.pixelSize: 10; opacity: 0.45 }
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
                            color: index % 2 === 0 ? Material.background : Qt.darker(Material.background, 1.03)

                            RowLayout {
                                anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
                                spacing: 8

                                Label {
                                    id: tagLabel
                                    text: model.tag
                                    Layout.preferredWidth: exifList.width * 0.42 - 16
                                    font.pixelSize: 11
                                    font.family: root.monoFont
                                    elide: Text.ElideRight
                                    ToolTip.text: model.tag
                                    ToolTip.visible: (tagHover ? tagHover.hovered : false) && truncated
                                    HoverHandler { id: tagHover }
                                }

                                Label {
                                    id: valueLabel
                                    text: model.value
                                    Layout.fillWidth: true
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                    opacity: 0.75
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

    // ── Browse tab ───────────────────────────────────────────────────────
    SplitView {
        id: browseSplit
        anchors { top: mainTabBar.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        visible: !_isLocked && mainTabBar.currentIndex === 1
        orientation: Qt.Horizontal
        handle: Rectangle {
            implicitWidth: 5
            color: SplitHandle.pressed ? root._accentColor : Material.dividerColor
        }

        // ── Folder tree ──────────────────────────────────────────────────
        Rectangle {
            SplitView.preferredWidth: 260
            SplitView.minimumWidth: 160
            SplitView.maximumWidth: 480
            color: Material.background
            clip: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Rectangle {
                    Layout.fillWidth: true
                    height: 36
                    color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.09)

                    FloatingBadge {
                        anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                        text: qsTr("FOLDERS")
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: root._folderTree.length === 0

                    Label {
                        anchors.centerIn: parent
                        text: qsTr("No folders indexed yet")
                        opacity: 0.35; font.pixelSize: 12
                    }
                }

                ListView {
                    id: browseTreeList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    visible: root._folderTree.length > 0
                    model: root._folderTree
                    ScrollBar.vertical: ScrollBar {}

                    delegate: Rectangle {
                        width: browseTreeList.width
                        height: 30
                        color: root._folderFilter === modelData.path
                               ? Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.12)
                               : "transparent"

                        Rectangle {
                            visible: root._folderFilter === modelData.path
                            x: 0; y: 4; width: 3; height: parent.height - 8; radius: 2
                            color: root._accentColor
                        }

                        RowLayout {
                            anchors { fill: parent; leftMargin: modelData.depth * 14 + 10; rightMargin: 8 }
                            spacing: 5

                            Label {
                                text: root._folderFilter === modelData.path ? "\ud83d\udcc2" : "\ud83d\udcc1"
                                font.pixelSize: 13
                            }

                            Label {
                                Layout.fillWidth: true
                                text: modelData.name
                                font.pixelSize: 12
                                font.weight: root._folderFilter === modelData.path ? Font.DemiBold : Font.Normal
                                color: root._folderFilter === modelData.path ? root._accentColor : Material.foreground
                                elide: Text.ElideRight
                            }

                            Rectangle {
                                visible: modelData.count > 0
                                height: 18; width: bcnt.implicitWidth + 10; radius: 9
                                color: root._folderFilter === modelData.path
                                       ? root._accentColor
                                       : Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.18)

                                Label {
                                    id: bcnt
                                    anchors.centerIn: parent
                                    text: modelData.count; font.pixelSize: 9
                                    color: root._folderFilter === modelData.path ? "white" : Material.foreground
                                }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: controller.browseFolder(modelData.path)
                        }
                    }
                }
            }
        }

        // ── Image list + preview ─────────────────────────────────────────
        SplitView {
            id: browseContentSplit
            SplitView.fillWidth: true
            orientation: Qt.Horizontal
            handle: Rectangle {
                implicitWidth: 5
                color: SplitHandle.pressed ? root._accentColor : Material.dividerColor
            }

            // Image list
            Rectangle {
                SplitView.preferredWidth: browseContentSplit.width / 2
                SplitView.minimumWidth: 260
                color: Material.background
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        height: 36
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.09)

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                            FloatingBadge { text: qsTr("IMAGES") }
                            Item { Layout.fillWidth: true }
                            Label {
                                text: root._folderFilter !== ""
                                      ? browseImageList.count + qsTr(" images")
                                      : qsTr("Select a folder")
                                font.pixelSize: 11; opacity: 0.6
                            }
                        }
                    }

                    // Empty-state hint
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: root._folderFilter === ""

                        Label {
                            anchors.centerIn: parent
                            text: qsTr("\u2190 Select a folder to browse images")
                            opacity: 0.35; font.pixelSize: 13
                        }
                    }

                    // Image list
                    ListView {
                        id: browseImageList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        visible: root._folderFilter !== ""
                        model: root._folderFilter !== "" ? searchModel : null
                        ScrollBar.vertical: ScrollBar {}

                        delegate: Rectangle {
                            id: browseCardDelegate
                            width: browseImageList.width
                            height: 210
                            color: "transparent"

                            readonly property bool _isSelected: ListView.isCurrentItem

                            readonly property var _exif: {
                                try { return JSON.parse(model.metadataJson) } catch(e) { return {} }
                            }
                            readonly property string _camera: {
                                var make   = _exif["EXIF:Make"]  || _exif["IFD0:Make"]  || _exif["XMP:Make"]  || ""
                                var model2 = _exif["EXIF:Model"] || _exif["IFD0:Model"] || _exif["XMP:Model"] || ""
                                if (make && model2)
                                    return model2.startsWith(make) ? model2.trim() : (make + " " + model2).trim()
                                return (make || model2).trim()
                            }
                            readonly property string _date: {
                                var d = _exif["EXIF:DateTimeOriginal"] || _exif["EXIF:DateTime"] || _exif["IFD0:ModifyDate"] || ""
                                return d ? d.replace("T", " ").split(".")[0] : ""
                            }
                            readonly property string _dims: {
                                var w = _exif["EXIF:ExifImageWidth"]  || _exif["File:ImageWidth"]  || _exif["PNG:ImageWidth"]  || ""
                                var h = _exif["EXIF:ExifImageHeight"] || _exif["File:ImageHeight"] || _exif["PNG:ImageHeight"] || ""
                                return (w && h) ? (w + " × " + h) : ""
                            }
                            readonly property string _lens: {
                                var fl  = _exif["EXIF:FocalLength"] || ""
                                var fn  = _exif["EXIF:FNumber"]     || _exif["EXIF:ApertureValue"] || ""
                                var iso = _exif["EXIF:ISO"]         || _exif["EXIF:ISOSpeedRatings"] || ""
                                var parts = []
                                if (fl)  parts.push(fl + " mm")
                                if (fn)  parts.push("ƒ/" + fn)
                                if (iso) parts.push("ISO " + iso)
                                return parts.join("  ")
                            }
                            readonly property string _sizeText: {
                                var bytes = model.fileSize || 0
                                if (bytes <= 0)  return ""
                                if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB"
                                if (bytes >= 1048576)    return (bytes / 1048576).toFixed(1) + " MB"
                                return Math.round(bytes / 1024) + " KB"
                            }

                            Rectangle {
                                anchors { fill: parent; leftMargin: 6; rightMargin: 6; topMargin: 3; bottomMargin: 3 }
                                radius: 7
                                color: _isSelected
                                       ? Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.12)
                                       : Material.background
                                border.color: _isSelected
                                              ? Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.45)
                                              : Material.dividerColor
                                border.width: 1
                            }

                            Rectangle {
                                x: 6; y: 12; width: 3; height: parent.height - 24; radius: 2
                                color: _isSelected ? root._accentColor : "transparent"
                            }

                            RowLayout {
                                anchors { fill: parent; leftMargin: 16; rightMargin: 14; topMargin: 10; bottomMargin: 10 }
                                spacing: 14

                                Image {
                                    Layout.preferredWidth: 182
                                    Layout.preferredHeight: 182
                                    source: model.thumbnailSource
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true; asynchronous: true
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 0

                                    Label {
                                        Layout.fillWidth: true
                                        text: model.filename
                                        font.pixelSize: 13; font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }

                                    Item { height: 2 }

                                    Label {
                                        Layout.fillWidth: true
                                        text: model.path
                                        font.pixelSize: 10; font.family: root.monoFont
                                        opacity: 0.45; elide: Text.ElideMiddle
                                    }

                                    Item { height: 8 }

                                    Rectangle {
                                        Layout.fillWidth: true; height: 1
                                        color: Material.dividerColor
                                    }

                                    Item { height: 6 }

                                    Repeater {
                                        model: [
                                            { label: qsTr("Camera"),     value: _camera  },
                                            { label: qsTr("Date"),       value: _date    },
                                            { label: qsTr("Dimensions"), value: _dims    },
                                            { label: qsTr("Exposure"),   value: _lens    },
                                            { label: qsTr("File size"),  value: _sizeText },
                                        ]
                                        delegate: RowLayout {
                                            visible: modelData.value !== ""
                                            Layout.fillWidth: true
                                            spacing: 8
                                            Label {
                                                text: modelData.label
                                                font.pixelSize: 10; opacity: 0.45
                                                Layout.preferredWidth: 68
                                            }
                                            Label {
                                                text: modelData.value
                                                font.pixelSize: 11
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                            }
                                        }
                                    }

                                    Item { Layout.fillHeight: true }
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton
                                onClicked: {
                                    browseImageList.currentIndex = index
                                    controller.selectResult(index)
                                }
                                onDoubleClicked: controller.openImage(model.path)
                            }
                        }

                        onAtYEndChanged: {
                            if (atYEnd && count > 0) controller.loadMore()
                        }
                    }
                }
            }

            // Preview
            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 200
                color: Material.background
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        height: 30
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.09)

                        FloatingBadge {
                            anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                            text: qsTr("PREVIEW")
                        }
                    }

                    Image {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        source: _selectedImageSource
                        fillMode: Image.PreserveAspectFit
                        smooth: true; asynchronous: true; cache: false
                    }
                }
            }
        }
    }

    // ── Status bar ────────────────────────────────────────────────────────
    footer: Rectangle {
        implicitHeight: _isLocked ? 0 : 26
        visible: !_isLocked
        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.06)

        Label {
            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
            text: _statusText
            font.pixelSize: 11
            opacity: 0.7
        }
    }
}
