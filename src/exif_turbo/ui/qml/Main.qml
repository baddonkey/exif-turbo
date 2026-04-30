import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import QtWebEngine

ApplicationWindow {
    id: root
    width: 1200
    height: 800
    minimumWidth: 900
    minimumHeight: 600
    title: "exif-turbo"

    Material.theme: {
        if (settingsModel?.theme === "dark")  return Material.Dark
        if (settingsModel?.theme === "light") return Material.Light
        return Material.System
    }
    Material.accent: Material.Blue
    Material.primary: Material.Blue

    // Resolved accent colour — safe to use from bare Rectangle children.
    readonly property color _accentColor: Material.accentColor
    readonly property string monoFont: "Courier New"
    // Colours for the third-party licenses WebEngineView HTML template.
    // Use rgb() to avoid Qt's #AARRGGBB string format being misread by CSS as #RRGGBBAA.
    readonly property string _licenseLinkColor: settingsModel?.theme === "dark" ? "#64B5F6" : "#1565C0"
    function _toRgb(c) {
        return "rgb(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + ")"
    }
    readonly property string _licenseBgColor: _toRgb(Material.background)
    readonly property string _licenseTextColor: _toRgb(Material.foreground)
    readonly property string _licenseBorderColor: _toRgb(Qt.darker(Material.background, 1.4))
    readonly property string _licenseHeaderBg: _toRgb(Qt.darker(Material.background, 1.1))

    Component.onCompleted: showMaximized()

    onClosing: (close) => { if (controller) controller.onAppClosing() }

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
    Shortcut {
        sequences: [ StandardKey.MoveToNextPage ]
        enabled: mainTabBar.currentIndex === 0 && controller && controller.currentResultRow < resultsList.count - 1
        onActivated: {
            var step = Math.max(1, Math.floor(resultsList.height / 210))
            var next = Math.min(controller.currentResultRow + step, resultsList.count - 1)
            controller.selectResult(next)
            resultsList.positionViewAtIndex(next, ListView.Contain)
        }
    }
    Shortcut {
        sequences: [ StandardKey.MoveToPreviousPage ]
        enabled: mainTabBar.currentIndex === 0 && controller && controller.currentResultRow > 0
        onActivated: {
            var step = Math.max(1, Math.floor(resultsList.height / 210))
            var prev = Math.max(controller.currentResultRow - step, 0)
            controller.selectResult(prev)
            resultsList.positionViewAtIndex(prev, ListView.Contain)
        }
    }
    Shortcut {
        sequences: [ StandardKey.MoveToNextLine ]
        enabled: mainTabBar.currentIndex === 0 && controller && controller.currentResultRow < resultsList.count - 1
        onActivated: {
            var next = controller.currentResultRow + 1
            controller.selectResult(next)
            resultsList.positionViewAtIndex(next, ListView.Contain)
        }
    }
    Shortcut {
        sequences: [ StandardKey.MoveToPreviousLine ]
        enabled: mainTabBar.currentIndex === 0 && controller && controller.currentResultRow > 0
        onActivated: {
            var prev = controller.currentResultRow - 1
            controller.selectResult(prev)
            resultsList.positionViewAtIndex(prev, ListView.Contain)
        }
    }

    property bool findBarVisible: false

    // ── Null-safe proxies ─────────────────────────────────────────────────
    readonly property bool   _isLocked:            controller ? controller.isLocked           : true
    readonly property bool   _isNewDatabase:       controller ? controller.isNewDatabase      : false
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
    readonly property string _selectedThumbSource: controller ? controller.selectedThumbSource : ""
    readonly property int    _indexQueuePosition:  controller ? controller.indexQueuePosition  : 0
    readonly property int    _indexQueueTotal:     controller ? controller.indexQueueTotal     : 0
    readonly property string _detailsHtml:         controller ? controller.detailsHtml        : ""
    readonly property string _sortBy:             controller ? controller.sortBy             : ""
    readonly property string _extFilter:          controller ? controller.extFilter          : ""
    readonly property string _availableFormats:   controller ? controller.availableFormats   : "[]"
    readonly property string _folderTreeJson:     controller ? controller.folderTree         : "[]"
    readonly property string _folderFilter:       controller ? controller.folderFilter       : ""
    readonly property int    _totalResults:       controller ? controller.totalResults        : 0
    readonly property string _appVersion:         controller ? controller.appVersion          : ""

    // Settings model null-safe proxies
    readonly property int    _workerCount:         settingsModel ? settingsModel.workerCount   : 4
    readonly property int    _minWorkers:          settingsModel ? settingsModel.minWorkers    : 1
    readonly property int    _maxWorkers:          settingsModel ? settingsModel.maxWorkers    : 16
    readonly property int    _defaultWorkers:      settingsModel ? settingsModel.defaultWorkers : 1
    readonly property int    _cpuCount:             settingsModel ? settingsModel.cpuCount        : 1

    // Parsed format list — updated reactively when _availableFormats changes
    readonly property var _formats: {
        try { return JSON.parse(_availableFormats) } catch(e) { return [] }
    }

    // Parsed folder tree — updated reactively when _folderTreeJson changes
    readonly property var _folderTree: {
        try { return JSON.parse(_folderTreeJson) } catch(e) { return [] }
    }

    // ── Dialogs ───────────────────────────────────────────────────────────
    Dialog {
        id: aboutDialog
        title: qsTr("About exif-turbo")
        standardButtons: Dialog.Ok
        anchors.centerIn: Overlay.overlay
        width: 340

        Label {
            text: "exif-turbo" + (_appVersion ? " v" + _appVersion : "") + "\n\nCross-platform image EXIF metadata\nsearch and indexing tool.\n\nLicense: MIT"
        }
    }

    Dialog {
        id: thirdPartyDialog
        title: qsTr("Third-Party Licenses")
        standardButtons: Dialog.Close
        anchors.centerIn: Overlay.overlay
        width: Math.min(root.width * 0.85, 820)
        height: Math.min(root.height * 0.85, 640)

        ScrollView {
            id: licensesScroll
            anchors.fill: parent
            clip: true
            contentWidth: availableWidth

            WebEngineView {
                width: licensesScroll.availableWidth
                height: Math.max(licensesScroll.height, implicitHeight)
                settings.showScrollBars: false

                property string licenseHtml: thirdPartyLicensesHtml
                    .split("TEXTCOLOR").join(root._licenseTextColor)
                    .split("BGCOLOR").join(root._licenseBgColor)
                    .split("LINKCOLOR").join(root._licenseLinkColor)
                    .split("BORDERCOLOR").join(root._licenseBorderColor)
                    .split("HEADERBG").join(root._licenseHeaderBg)
                    .split("CODEBG").join(root._licenseBorderColor)

                onLicenseHtmlChanged: loadHtml(licenseHtml)
                Component.onCompleted: loadHtml(licenseHtml)

                onNavigationRequested: (request) => {
                    // navigationType 0 = LinkClickedNavigation
                    if (request.navigationType === 0) {
                        Qt.openUrlExternally(request.url)
                        request.reject()
                    }
                    // all other types (OtherNavigation = loadHtml) are allowed
                }
            }
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
                text: qsTr("&User Manual")
                enabled: typeof userManualUrl !== "undefined" && userManualUrl !== ""
                onTriggered: Qt.openUrlExternally(userManualUrl)
            }
            Action {
                text: qsTr("Third-Party &Licenses")
                onTriggered: thirdPartyDialog.open()
            }
            Action {
                text: qsTr("&About")
                onTriggered: aboutDialog.open()
            }
        }
    }

    // ── Toolbar (hidden — search moved into Search tab) ─────────────────
    header: ToolBar {
        implicitHeight: 0
        visible: false
    }

    // ── Lock screen ───────────────────────────────────────────────────────
    Pane {
        id: lockScreen
        anchors.fill: parent
        visible: _isLocked
        z: 100

        Pane {
            anchors.centerIn: parent
            width: 380
            padding: 28
            Material.elevation: 4

            ColumnLayout {
                width: parent.width
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
                    text: _appVersion ? "v" + _appVersion : ""
                    font.pixelSize: 12
                    opacity: 0.45
                    visible: _appVersion !== ""
                    Layout.topMargin: -10
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: _isNewDatabase
                          ? qsTr("Create a passphrase for your new database")
                          : qsTr("Enter the database password")
                    font.pixelSize: 14
                    opacity: 0.7
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }

                // New-database hint banner
                Label {
                    Layout.fillWidth: true
                    visible: _isNewDatabase
                    text: qsTr("This passphrase encrypts your entire image index. Use at least 12 characters and a mix of letters, numbers, and symbols. There is no way to recover a lost passphrase.")
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    opacity: 0.85
                    topPadding: 8; bottomPadding: 8; leftPadding: 8; rightPadding: 8
                    background: Rectangle {
                        radius: 6
                        color: Qt.rgba(Material.accentColor.r, Material.accentColor.g, Material.accentColor.b, 0.10)
                        border.color: Qt.rgba(Material.accentColor.r, Material.accentColor.g, Material.accentColor.b, 0.30)
                        border.width: 1
                    }
                }

                TextField {
                    id: passwordField
                    Layout.fillWidth: true
                    placeholderText: _isNewDatabase ? qsTr("New passphrase") : qsTr("Password")
                    echoMode: TextInput.Password
                    font.pixelSize: 14
                    Keys.onReturnPressed: _isNewDatabase ? confirmField.forceActiveFocus() : controller.unlock(text)
                    Component.onCompleted: forceActiveFocus()
                }

                TextField {
                    id: confirmField
                    Layout.fillWidth: true
                    visible: _isNewDatabase
                    placeholderText: qsTr("Confirm passphrase")
                    echoMode: TextInput.Password
                    font.pixelSize: 14
                    Keys.onReturnPressed: lockScreen._tryCreate()
                }

                // Mismatch / error label
                Label {
                    Layout.fillWidth: true
                    text: _unlockError !== "" ? _unlockError
                          : (_isNewDatabase && confirmField.text.length > 0 && passwordField.text !== confirmField.text
                             ? qsTr("Passphrases do not match") : "")
                    color: "#f44336"
                    font.pixelSize: 12
                    visible: text !== ""
                    wrapMode: Text.WordWrap
                }

                Button {
                    Layout.fillWidth: true
                    text: _isNewDatabase ? qsTr("Create Database") : qsTr("Unlock")
                    highlighted: true
                    implicitHeight: 44
                    font.pixelSize: 14
                    enabled: _isNewDatabase
                             ? (passwordField.text.length >= 1 && passwordField.text === confirmField.text)
                             : passwordField.text.length >= 1
                    onClicked: _isNewDatabase ? lockScreen._tryCreate() : controller.unlock(passwordField.text)
                }
            }
        }

        function _tryCreate() {
            if (passwordField.text !== confirmField.text) return
            controller.unlock(passwordField.text)
        }
    }

    // ── Progress panel (non-blocking, bottom-right corner) ───────────────
    Pane {
        id: progressPanel
        anchors { right: parent.right; bottom: parent.bottom; margins: 16 }
        width: 380
        visible: !_isLocked && (_isIndexing || _isBuildingThumbs) && mainTabBar.currentIndex === 2
        z: 20
        Material.elevation: 6
        padding: 16

        ColumnLayout {
            anchors.fill: parent
            spacing: 10

            // Title row
            Label {
                Layout.fillWidth: true
                text: {
                    if (_isIndexing) {
                        return _indexQueueTotal > 1
                            ? qsTr("Indexing folder %1 of %2").arg(_indexQueuePosition).arg(_indexQueueTotal)
                            : qsTr("Indexing")
                    }
                    return qsTr("Building Thumbnails")
                }
                font.pixelSize: 14
                font.weight: Font.Medium
            }

            // Progress bar
            ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: {
                    if (_isIndexing) return _indexTotal > 0 ? _indexTotal : 1
                    return _thumbTotal > 0 ? _thumbTotal : 1
                }
                value: _isIndexing ? _indexCurrent : _thumbCurrent
                indeterminate: _isIndexing ? _indexTotal === 0 : _thumbTotal === 0
            }

            // Count label
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: {
                    if (_isIndexing)
                        return _indexTotal > 0
                            ? _indexCurrent + " / " + _indexTotal + " " + qsTr("files")
                            : qsTr("Scanning for images\u2026")
                    return _thumbTotal > 0
                        ? _thumbCurrent + " / " + _thumbTotal + " " + qsTr("images")
                        : qsTr("Preparing\u2026")
                }
                font.pixelSize: 12
                opacity: 0.7
            }

            // Current file path
            Label {
                Layout.fillWidth: true
                text: _isIndexing ? _indexCurrentFile : _thumbCurrentFile
                font.pixelSize: 10
                opacity: 0.5
                elide: Text.ElideMiddle
                horizontalAlignment: Text.AlignHCenter
            }

            // Cancel button
            Button {
                Layout.alignment: Qt.AlignHCenter
                text: {
                    var canceling = controller ? controller.isCanceling : false
                    if (_isIndexing) return canceling ? qsTr("Canceling\u2026") : qsTr("Cancel Indexing")
                    return canceling ? qsTr("Canceling\u2026") : qsTr("Cancel Thumbnails")
                }
                enabled: !(controller ? controller.isCanceling : false)
                highlighted: true
                Material.accent: Material.Red
                implicitHeight: 36
                implicitWidth: 160
                onClicked: _isIndexing ? controller.cancelIndex() : controller.cancelThumbnails()
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
        objectName: "mainTabBar"
        anchors { top: parent.top; left: parent.left }
        width: 560   // 4 × 140 px — left-aligned, not stretched
        implicitHeight: 40
        visible: !_isLocked
        z: 10
        background: Item {}  // transparent; background rect above covers the row

        Repeater {
            model: [ qsTr("Search"), qsTr("Browse"), qsTr("Indexed Folders"), qsTr("Settings") ]
            TabButton {
                text: modelData
                implicitWidth: 140
                implicitHeight: 40
                enabled: true

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

                    // Search bar
                    Rectangle {
                        Layout.fillWidth: true
                        height: 52
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.07)

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 10; topMargin: 8; bottomMargin: 8 }
                            spacing: 6

                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 36
                                radius: 4
                                color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.07)
                                border.color: searchField.activeFocus ? root._accentColor : Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.2)
                                border.width: 1

                                Label {
                                    anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                                    visible: searchField.text.length === 0
                                    text: qsTr("Search EXIF metadata\u2026")
                                    font.pixelSize: 13
                                    opacity: 0.4
                                }

                                TextInput {
                                    id: searchField
                                    anchors { left: parent.left; right: parent.right; leftMargin: 10; rightMargin: text.length > 0 ? 28 : 10; verticalCenter: parent.verticalCenter }
                                    font.pixelSize: 13
                                    color: Material.foreground
                                    selectedTextColor: "white"
                                    selectionColor: root._accentColor
                                    clip: true
                                    Keys.onReturnPressed: controller.search(text)
                                }

                                // Clear button — visible whenever the field has text
                                Item {
                                    id: clearSearchButton
                                    anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter }
                                    width: 20; height: 20
                                    visible: searchField.text.length > 0

                                    Text {
                                        anchors.centerIn: parent
                                        text: "\u00D7"
                                        font.pixelSize: 16
                                        color: Material.foreground
                                        opacity: clearSearchMouse.containsMouse ? 1.0 : 0.45
                                        Behavior on opacity { NumberAnimation { duration: 80 } }
                                    }

                                    MouseArea {
                                        id: clearSearchMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            searchField.text = ""
                                            searchField.forceActiveFocus()
                                            controller.search("")
                                        }
                                    }
                                }
                            }

                            Button {
                                text: qsTr("Search")
                                highlighted: true
                                implicitHeight: 36
                                font.pixelSize: 13
                                onClicked: controller.search(searchField.text)
                            }
                        }
                    }

                    // Panel header
                    Rectangle {
                        Layout.fillWidth: true
                        height: 36
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.09)

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 6 }
                            spacing: 6

                            FloatingBadge { text: qsTr("RESULTS") }

                            Label {
                                text: _totalResults > 0 ? _totalResults.toString() : ""
                                font.pixelSize: 11
                                opacity: 0.55
                                visible: _totalResults > 0
                            }

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
                        currentIndex: controller ? controller.currentResultRow : -1
                        ScrollBar.vertical: ScrollBar {}

                        WheelHandler {
                            onWheel: (event) => {
                                var step = 210
                                var delta = event.angleDelta.y < 0 ? step : -step
                                resultsList.contentY = Math.max(0,
                                    Math.min(resultsList.contentY + delta,
                                             Math.max(0, resultsList.contentHeight - resultsList.height)))
                                event.accepted = true
                            }
                        }

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

                    // Preview: show cached thumbnail instantly as placeholder,
                    // then fade in the full image once it has loaded.
                    // Wheel/pinch to zoom · drag/swipe to pan · double-click/tap to reset.
                    Item {
                        id: previewHost
                        objectName: "previewHost"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        property real _zoom: 1.0
                        readonly property real _maxZoom: 8.0

                        Flickable {
                            id: previewFlick
                            objectName: "previewFlick"
                            anchors.fill: parent
                            contentWidth:  Math.max(width,  previewHost.width  * previewHost._zoom)
                            contentHeight: Math.max(height, previewHost.height * previewHost._zoom)
                            boundsBehavior: Flickable.StopAtBounds
                            clip: true

                            // Low-res thumbnail placeholder — visible from cache immediately
                            Image {
                                width:  previewFlick.contentWidth
                                height: previewFlick.contentHeight
                                source: _selectedThumbSource
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                visible: _selectedThumbSource !== "" && fullPreview.status !== Image.Ready
                            }

                            // Full-resolution image — fades in when loaded
                            Image {
                                id: fullPreview
                                objectName: "fullPreview"
                                property int loadStatus: status
                                width:  previewFlick.contentWidth
                                height: previewFlick.contentHeight
                                source: _selectedImageSource
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                asynchronous: true
                                cache: false
                                opacity: status === Image.Ready ? 1.0 : 0.0
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                                onSourceChanged: {
                                    previewHost._zoom = 1.0
                                    previewFlick.contentX = 0
                                    previewFlick.contentY = 0
                                }
                                onStatusChanged: {
                                    if (status === Image.Ready || status === Image.Error)
                                        if (controller) controller.onPreviewStatusChanged()
                                }
                            }

                            // Mouse-wheel zoom (physical scroll wheel, or Ctrl + trackpad scroll).
                            //
                            // acceptedDevices limits this handler to real wheel events so that
                            // plain two-finger trackpad scroll is left to the Flickable for panning.
                            // On macOS, Ctrl + two-finger scroll also reaches here (system zoom-
                            // scroll shortcut), which is a reasonable fallback for mouse users.
                            //
                            // Qt 6 delivers event.x/y in CONTENT coordinates (contentX + viewportX)
                            // when the WheelHandler is inside a Flickable.
                            // Correct cursor-anchor formula:
                            //   new_contentX = event.x * (factor − 1) + oldContentX
                            WheelHandler {
                                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                                acceptedModifiers: Qt.ControlModifier
                                onWheel: (event) => {
                                    if (event.phase === Qt.ScrollMomentum) { event.accepted = true; return }
                                    if (event.angleDelta.y === 0) return
                                    var step    = Math.pow(1.2, event.angleDelta.y / 120.0)
                                    var oldZoom = previewHost._zoom
                                    var newZoom = Math.max(1.0, Math.min(previewHost._maxZoom, oldZoom * step))
                                    if (newZoom === oldZoom) { event.accepted = true; return }
                                    var actualFactor = newZoom / oldZoom
                                    var oldContentX = previewFlick.contentX
                                    var oldContentY = previewFlick.contentY
                                    var newW = Math.max(previewFlick.width,  previewHost.width  * newZoom)
                                    var newH = Math.max(previewFlick.height, previewHost.height * newZoom)
                                    previewHost._zoom = newZoom
                                    previewFlick.contentX = Math.max(0,
                                        Math.min(event.x * (actualFactor - 1) + oldContentX, newW - previewFlick.width))
                                    previewFlick.contentY = Math.max(0,
                                        Math.min(event.y * (actualFactor - 1) + oldContentY, newH - previewFlick.height))
                                    event.accepted = true
                                }
                            }

                            // Double-click / double-tap resets zoom and pan to 1×.
                            // Must live inside the Flickable so it receives the press
                            // events that the Flickable otherwise consumes.
                            TapHandler {
                                onDoubleTapped: {
                                    previewHost._zoom = 1.0
                                    previewFlick.contentX = 0
                                    previewFlick.contentY = 0
                                }
                            }
                        }

                        // Touchpad pinch-to-zoom — anchored at the pinch centroid.
                        // centroid.position is in previewHost (viewport) coordinates.
                        //
                        // grabPermissions: CanTakeOverFromHandlersOfDifferentType lets the
                        // PinchHandler steal the touch points from the Flickable as soon as a
                        // pinch is recognised, eliminating the startup delay.
                        //
                        // scaleAxis.minimum/maximum remove Qt's built-in scale dead-zone so
                        // zoom responds from the very first movement.
                        PinchHandler {
                            target: null
                            grabPermissions: PointerHandler.CanTakeOverFromHandlersOfDifferentType
                                           | PointerHandler.ApprovesTakeOverByHandlersOfSameType
                            scaleAxis.minimum:  0.001   // allow any pinch distance; zoom is clamped in code
                            scaleAxis.maximum: 99.0

                            // _prevScale tracks the PinchHandler.scale from the previous
                            // onScaleChanged tick so we can compute an incremental factor:
                            //   factor = scale / _prevScale
                            // Applying the *delta* each tick (rather than startZoom * scale)
                            // means there is no stale "start-scale" that can diverge between
                            // two separate gestures and cause a jump on the second pinch.
                            property real _prevScale: 1.0

                            onActiveChanged: {
                                if (active) {
                                    _prevScale = scale   // scale resets to 1.0 at gesture start
                                }
                            }
                            onScaleChanged: {
                                var factor      = scale / _prevScale
                                _prevScale      = scale
                                var oldZoom     = previewHost._zoom
                                var newZoom     = Math.max(1.0, Math.min(previewHost._maxZoom, oldZoom * factor))
                                if (newZoom === oldZoom) return
                                var actualFactor = newZoom / oldZoom
                                // centroid.position is in previewHost (viewport) coordinates.
                                var cx = centroid.position.x
                                var cy = centroid.position.y
                                var oldContentX = previewFlick.contentX
                                var oldContentY = previewFlick.contentY
                                var newW = Math.max(previewFlick.width,  previewHost.width  * newZoom)
                                var newH = Math.max(previewFlick.height, previewHost.height * newZoom)
                                previewHost._zoom = newZoom
                                previewFlick.contentX = Math.max(0,
                                    Math.min((oldContentX + cx) * actualFactor - cx, newW - previewFlick.width))
                                previewFlick.contentY = Math.max(0,
                                    Math.min((oldContentY + cy) * actualFactor - cy, newH - previewFlick.height))
                            }
                        }

                        // Zoom level badge
                        Rectangle {
                            anchors { bottom: parent.bottom; right: parent.right; margins: 8 }
                            width: previewZoomLabel.implicitWidth + 16
                            height: 22
                            radius: 4
                            color: Qt.rgba(0, 0, 0, 0.55)
                            visible: previewHost._zoom > 1.05
                            Label {
                                id: previewZoomLabel
                                anchors.centerIn: parent
                                text: Math.round(previewHost._zoom * 100) + "%"
                                font.pixelSize: 11
                                color: "#ffffff"
                            }
                        }
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
                SplitView.preferredWidth: bottomSplit.width / 2
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
                SplitView.fillWidth: true
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

        onVisibleChanged: { if (visible) controller.loadFolderTree() }
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
                        currentIndex: controller ? controller.currentResultRow : -1
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

                    // Preview: show cached thumbnail instantly as placeholder,
                    // then fade in the full image once it has loaded.
                    // Wheel/pinch to zoom · drag/swipe to pan · double-click/tap to reset.
                    Item {
                        id: previewHost2
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        property real _zoom: 1.0
                        readonly property real _maxZoom: 8.0

                        Flickable {
                            id: previewFlick2
                            anchors.fill: parent
                            contentWidth:  Math.max(width,  previewHost2.width  * previewHost2._zoom)
                            contentHeight: Math.max(height, previewHost2.height * previewHost2._zoom)
                            boundsBehavior: Flickable.StopAtBounds
                            clip: true

                            Image {
                                width:  previewFlick2.contentWidth
                                height: previewFlick2.contentHeight
                                source: _selectedThumbSource
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                visible: _selectedThumbSource !== "" && fullPreview2.status !== Image.Ready
                            }

                            Image {
                                id: fullPreview2
                                objectName: "fullPreview2"
                                property int loadStatus: status
                                width:  previewFlick2.contentWidth
                                height: previewFlick2.contentHeight
                                source: _selectedImageSource
                                fillMode: Image.PreserveAspectFit
                                smooth: true; asynchronous: true; cache: false
                                opacity: status === Image.Ready ? 1.0 : 0.0
                                Behavior on opacity { NumberAnimation { duration: 150 } }
                                onSourceChanged: {
                                    previewHost2._zoom = 1.0
                                    previewFlick2.contentX = 0
                                    previewFlick2.contentY = 0
                                }
                                onStatusChanged: {
                                    if (status === Image.Ready || status === Image.Error)
                                        if (controller) controller.onPreviewStatusChanged()
                                }
                            }

                            WheelHandler {
                                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                                acceptedModifiers: Qt.ControlModifier
                                onWheel: (event) => {
                                    if (event.phase === Qt.ScrollMomentum) { event.accepted = true; return }
                                    if (event.angleDelta.y === 0) return
                                    var step    = Math.pow(1.2, event.angleDelta.y / 120.0)
                                    var oldZoom = previewHost2._zoom
                                    var newZoom = Math.max(1.0, Math.min(previewHost2._maxZoom, oldZoom * step))
                                    if (newZoom === oldZoom) { event.accepted = true; return }
                                    var actualFactor = newZoom / oldZoom
                                    var oldContentX = previewFlick2.contentX
                                    var oldContentY = previewFlick2.contentY
                                    var newW = Math.max(previewFlick2.width,  previewHost2.width  * newZoom)
                                    var newH = Math.max(previewFlick2.height, previewHost2.height * newZoom)
                                    previewHost2._zoom = newZoom
                                    previewFlick2.contentX = Math.max(0,
                                        Math.min(event.x * (actualFactor - 1) + oldContentX, newW - previewFlick2.width))
                                    previewFlick2.contentY = Math.max(0,
                                        Math.min(event.y * (actualFactor - 1) + oldContentY, newH - previewFlick2.height))
                                    event.accepted = true
                                }
                            }

                            // Double-click / double-tap resets zoom and pan to 1×.
                            // Must live inside the Flickable so it receives the press
                            // events that the Flickable otherwise consumes.
                            TapHandler {
                                onDoubleTapped: {
                                    previewHost2._zoom = 1.0
                                    previewFlick2.contentX = 0
                                    previewFlick2.contentY = 0
                                }
                            }
                        }

                        PinchHandler {
                            target: null
                            grabPermissions: PointerHandler.CanTakeOverFromHandlersOfDifferentType
                                           | PointerHandler.ApprovesTakeOverByHandlersOfSameType
                            scaleAxis.minimum:  0.001
                            scaleAxis.maximum: 99.0

                            property real _prevScale: 1.0

                            onActiveChanged: {
                                if (active) {
                                    _prevScale = scale
                                }
                            }
                            onScaleChanged: {
                                var factor      = scale / _prevScale
                                _prevScale      = scale
                                var oldZoom     = previewHost2._zoom
                                var newZoom     = Math.max(1.0, Math.min(previewHost2._maxZoom, oldZoom * factor))
                                if (newZoom === oldZoom) return
                                var actualFactor = newZoom / oldZoom
                                var cx = centroid.position.x
                                var cy = centroid.position.y
                                var oldContentX = previewFlick2.contentX
                                var oldContentY = previewFlick2.contentY
                                var newW = Math.max(previewFlick2.width,  previewHost2.width  * newZoom)
                                var newH = Math.max(previewFlick2.height, previewHost2.height * newZoom)
                                previewHost2._zoom = newZoom
                                previewFlick2.contentX = Math.max(0,
                                    Math.min((oldContentX + cx) * actualFactor - cx, newW - previewFlick2.width))
                                previewFlick2.contentY = Math.max(0,
                                    Math.min((oldContentY + cy) * actualFactor - cy, newH - previewFlick2.height))
                            }
                        }

                        Rectangle {
                            anchors { bottom: parent.bottom; right: parent.right; margins: 8 }
                            width: previewZoomLabel2.implicitWidth + 16
                            height: 22
                            radius: 4
                            color: Qt.rgba(0, 0, 0, 0.55)
                            visible: previewHost2._zoom > 1.05
                            Label {
                                id: previewZoomLabel2
                                anchors.centerIn: parent
                                text: Math.round(previewHost2._zoom * 100) + "%"
                                font.pixelSize: 11
                                color: "#ffffff"
                            }
                        }
                    }
                }
            }
        }
    }

    // ── Folders tab ──────────────────────────────────────────────────────
    FoldersPanel {
        anchors { top: mainTabBar.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        visible: !_isLocked && mainTabBar.currentIndex === 2
    }

    // ── Settings tab ─────────────────────────────────────────────────────
    Item {
        anchors { top: mainTabBar.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        visible: !_isLocked && mainTabBar.currentIndex === 3

        ScrollView {
            anchors.fill: parent
            contentWidth: parent.width
            clip: true

            ColumnLayout {
                width: parent.width
                anchors.leftMargin: 0
                spacing: 0

                // ── Page heading ─────────────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    height: 48
                    color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.07)

                    FloatingBadge {
                        anchors { left: parent.left; leftMargin: 40; verticalCenter: parent.verticalCenter }
                        text: qsTr("SETTINGS")
                    }
                }

                // ── Content area ─────────────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 40
                    Layout.rightMargin: 40
                    Layout.topMargin: 28
                    spacing: 0

                    // ── Worker threads ───────────────────────────────────
                    Label {
                        text: qsTr("Worker Threads")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 6
                    }
                    Label {
                        text: qsTr("Number of parallel threads used for indexing and thumbnail generation. Higher values speed up processing but use more CPU and memory.")
                        font.pixelSize: 12
                        opacity: 0.6
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.bottomMargin: 12
                    }

                    RowLayout {
                        spacing: 12
                        Layout.bottomMargin: 4

                        SpinBox {
                            id: workerSpinBox
                            from: _minWorkers
                            to: _maxWorkers
                            value: _workerCount
                            implicitWidth: 160
                            editable: false
                            onValueModified: settingsModel.setWorkerCount(value)
                        }

                        Label {
                            text: workerSpinBox.value === 1 ? qsTr("thread") : qsTr("threads")
                            font.pixelSize: 12
                            opacity: 0.7
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    Label {
                        text: qsTr("Factory default: %1 (%2 CPU threads detected)").arg(_defaultWorkers).arg(_cpuCount)
                        font.pixelSize: 11
                        opacity: 0.45
                        Layout.bottomMargin: 28
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor; Layout.bottomMargin: 28 }

                    // ── Indexing blacklist ────────────────────────────────
                    Label {
                        text: qsTr("Indexing Blacklist")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 6
                    }
                    Label {
                        text: qsTr("File and folder name patterns to skip during indexing. Supports wildcards (e.g. *, ?).\nChanges take effect on the next rescan.")
                        font.pixelSize: 12
                        opacity: 0.6
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.bottomMargin: 14
                    }

                    // Pattern list
                    Rectangle {
                        Layout.fillWidth: true
                        height: blacklistView.contentHeight + 2
                        color: Material.background
                        border.color: Material.dividerColor
                        border.width: 1
                        radius: 4
                        clip: true
                        Layout.bottomMargin: 10

                        ListView {
                            id: blacklistView
                            anchors { top: parent.top; left: parent.left; right: parent.right }
                            height: contentHeight
                            interactive: false
                            model: settingsModel ? settingsModel.blacklist : []

                            delegate: Rectangle {
                                width: blacklistView.width
                                height: 34
                                color: index % 2 === 0 ? Material.background : Qt.darker(Material.background, 1.03)

                                RowLayout {
                                    anchors { fill: parent; leftMargin: 12; rightMargin: 6 }
                                    spacing: 8

                                    Label {
                                        text: "\uD83D\uDEAB"
                                        font.pixelSize: 12
                                        opacity: 0.5
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: modelData
                                        font.pixelSize: 12
                                        font.family: root.monoFont
                                        elide: Text.ElideRight
                                    }

                                    ToolButton {
                                        icon.name: "window-close"
                                        text: "✕"
                                        implicitWidth: 28; implicitHeight: 28
                                        font.pixelSize: 11
                                        opacity: 0.6
                                        onClicked: settingsModel.removeBlacklistEntry(index)
                                        ToolTip.text: qsTr("Remove")
                                        ToolTip.visible: hovered
                                    }
                                }
                            }
                        }
                    }

                    // Add new pattern row
                    RowLayout {
                        spacing: 8
                        Layout.fillWidth: true
                        Layout.bottomMargin: 8

                        TextField {
                            id: newPatternField
                            Layout.fillWidth: true
                            placeholderText: qsTr("New pattern, e.g.  @eaDir  or  *.tmp")
                            font.pixelSize: 12
                            font.family: root.monoFont
                            onAccepted: {
                                if (text.trim() !== "") {
                                    settingsModel.addBlacklistEntry(text.trim())
                                    text = ""
                                }
                            }
                        }

                        Button {
                            text: qsTr("Add")
                            enabled: newPatternField.text.trim() !== ""
                            onClicked: {
                                settingsModel.addBlacklistEntry(newPatternField.text.trim())
                                newPatternField.text = ""
                            }
                        }
                    }

                    Label {
                        text: qsTr("Patterns are matched against individual file or folder names (not full paths). Wildcards: * matches any characters, ? matches one character.")
                        font.pixelSize: 11
                        opacity: 0.45
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.bottomMargin: 40
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor; Layout.bottomMargin: 28 }

                    // ── Theme ─────────────────────────────────────────────
                    Label {
                        text: qsTr("Theme")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 12
                    }

                    RowLayout {
                        spacing: 12
                        Layout.bottomMargin: 40

                        ComboBox {
                            id: themeCombo
                            objectName: "themeCombo"
                            Layout.preferredHeight: 38
                            Layout.preferredWidth: 200
                            model: ["system", "light", "dark"]
                            property bool ready: false
                            Component.onCompleted: {
                                if (!settingsModel) return
                                var idx = model.indexOf(settingsModel.theme)
                                currentIndex = idx >= 0 ? idx : 0
                                ready = true
                            }
                            onCurrentTextChanged: {
                                if (ready && settingsModel) settingsModel.theme = currentText
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor; Layout.bottomMargin: 28 }

                    // ── Language ──────────────────────────────────────────
                    Label {
                        text: qsTr("Language")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 12
                    }

                    RowLayout {
                        spacing: 12
                        Layout.bottomMargin: 4

                        ComboBox {
                            id: langCombo
                            Layout.preferredHeight: 38
                            Layout.preferredWidth: 200
                            model: settingsModel ? settingsModel.languageNames : []
                            property bool ready: false
                            Component.onCompleted: {
                                if (!settingsModel) return
                                var codes = settingsModel.languageCodes
                                var idx = codes.indexOf(settingsModel.language)
                                if (idx >= 0) currentIndex = idx
                                ready = true
                            }
                            onCurrentIndexChanged: {
                                if (!ready || !settingsModel) return
                                var codes = settingsModel.languageCodes
                                if (currentIndex >= 0 && currentIndex < codes.length)
                                    settingsModel.language = codes[currentIndex]
                            }
                        }
                    }

                    Label {
                        text: qsTr("Restart the application for language changes to take full effect.")
                        font.pixelSize: 11
                        font.italic: true
                        opacity: 0.55
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.bottomMargin: 40
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor; Layout.bottomMargin: 28 }

                    // ── Reset database ────────────────────────────────────
                    Label {
                        text: qsTr("Reset Database")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 6
                    }
                    Label {
                        text: qsTr("Permanently deletes all indexed images and folder records. This cannot be undone.")
                        font.pixelSize: 12
                        opacity: 0.6
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.bottomMargin: 14
                    }

                    RowLayout {
                        spacing: 10
                        Layout.bottomMargin: 40

                        Label {
                            text: "\u26A0\uFE0F"
                            font.pixelSize: 18
                            verticalAlignment: Text.AlignVCenter
                        }

                        Button {
                            id: resetDbButton
                            text: qsTr("Reset Database\u2026")
                            Material.background: Material.Red
                            Material.foreground: "white"
                            enabled: !_isIndexing && !_isLocked
                            onClicked: resetDbDialog.open()
                        }
                    }
                }
            }
        }
    }

    // ── Reset database confirmation dialog ────────────────────────────────
    Dialog {
        id: resetDbDialog
        title: qsTr("Reset Database")
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 420
        standardButtons: Dialog.Ok | Dialog.Cancel

        Label {
            width: 360
            wrapMode: Text.WordWrap
            text: qsTr("This will permanently delete all indexed images and indexed folder records.\n\nAre you sure you want to continue?")
        }

        onAccepted: controller.resetDatabase()
    }

    // ── Status bar ────────────────────────────────────────────────────────
    footer: Rectangle {
        implicitHeight: _isLocked ? 0 : 26
        visible: !_isLocked
        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.06)

        // Pulsing blue dot — visible only while indexing
        Rectangle {
            id: indexingDot
            anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
            width: 8; height: 8
            radius: 4
            color: root._accentColor
            visible: _isIndexing

            SequentialAnimation on opacity {
                running: indexingDot.visible
                loops: Animation.Infinite
                NumberAnimation { to: 0.25; duration: 800; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.0;  duration: 800; easing.type: Easing.InOutSine }
            }
        }

        Label {
            id: indexingLabel
            anchors { left: indexingDot.right; leftMargin: 5; verticalCenter: parent.verticalCenter }
            text: qsTr("Indexing…")
            visible: _isIndexing
            font.pixelSize: 11
            color: root._accentColor
        }

        Label {
            anchors {
                left: _isIndexing ? indexingLabel.right : parent.left
                leftMargin: _isIndexing ? 10 : 12
                verticalCenter: parent.verticalCenter
            }
            text: _statusText
            font.pixelSize: 11
            opacity: 0.7
        }
    }
}
