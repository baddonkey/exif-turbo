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
    // Automation helper: used by the screenshot script to open the folder filter popup
    function openFolderFilterPopup() { folderMultiCombo.popup.open() }
    // Automation helper: used by the screenshot script to close the folder filter popup
    function closeFolderFilterPopup() { folderMultiCombo.popup.close() }
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
    // After unlock, reclaim window focus so macOS doesn't leave the menu bar focused.
    Connections {
        target: controller
        function onIsLockedChanged() {
            if (!controller.isLocked) {
                root.requestActivate()
                searchField.forceActiveFocus()
            }
        }
        function onClipboardCopyDone(message) {
            clipboardToast.show(message)
        }
    }

    // ── Preview context menu (right-click on either preview pane) ─────────
    Menu {
        id: previewContextMenu
        MenuItem {
            text: qsTr("Copy Image to Clipboard")
            enabled: _selectedImageSource !== ""
            onTriggered: { if (controller) controller.copyPreviewToClipboard() }
        }
    }

    // ── Clipboard copy toast ──────────────────────────────────────────────
    Rectangle {
        id: clipboardToast
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 32 }
        width: clipboardToastLabel.implicitWidth + 32
        height: 36
        radius: 18
        color: Qt.rgba(0.1, 0.1, 0.1, 0.88)
        z: 9999
        opacity: 0.0
        visible: opacity > 0.0

        function show(message) {
            clipboardToastLabel.text = message
            opacity = 1.0
            clipboardToastTimer.restart()
        }

        Behavior on opacity { NumberAnimation { duration: 180 } }

        Timer {
            id: clipboardToastTimer
            interval: 2000
            onTriggered: clipboardToast.opacity = 0.0
        }

        Label {
            id: clipboardToastLabel
            anchors.centerIn: parent
            font.pixelSize: 13
            color: "#ffffff"
        }
    }

    readonly property bool   _isNewDatabase:       controller ? controller.isNewDatabase      : false
    readonly property bool   _isIndexing:          controller ? controller.isIndexing         : false
    readonly property bool   _isBuildingThumbs:    controller ? controller.isBuildingThumbs   : false
    readonly property bool   _isBuildingPreviews:  controller ? controller.isBuildingPreviews : false
    readonly property int    _previewCurrent:      controller ? controller.previewCurrent     : 0
    readonly property int    _previewTotal:        controller ? controller.previewTotal       : 0
    readonly property string _previewCurrentFile:  controller ? controller.previewCurrentFile : ""
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
    readonly property string _geoLocationUrl:       controller ? controller.geoLocationUrl     : ""
    readonly property string _geoGoogleMapsUrl:     controller ? controller.geoGoogleMapsUrl   : ""
    readonly property string _geoWikipediaUrl:      controller ? controller.geoWikipediaUrl    : ""
    readonly property bool   _checkedOnlyFilter:   controller ? controller.checkedOnlyFilter  : false
    readonly property string _sortBy:                  controller ? controller.sortBy              : ""
    readonly property string _extFilter:               controller ? controller.extFilter           : ""
    readonly property string _availableFormats:        controller ? controller.availableFormats    : "[]"
    readonly property string _folderTreeJson:          controller ? controller.folderTree          : "[]"
    readonly property string _folderFilter:            controller ? controller.folderFilter        : ""
    readonly property string _searchFolderFilters:     controller ? controller.searchFolderFilters : "[]"
    readonly property string _searchFolderListJson:    controller ? controller.searchFolderListJson : "[]"
    readonly property int    _indexedFolderCount:      controller ? controller.indexedFolderCount  : 0
    readonly property int    _totalResults:       controller ? controller.totalResults        : 0
    readonly property string _searchError:        controller ? controller.searchError         : ""
    readonly property string _appVersion:         controller ? controller.appVersion          : ""
    readonly property bool   _isBusy:             controller ? controller.isBusy             : false
    readonly property string _busyLabel:          controller ? controller.busyLabel          : ""
    readonly property int    _bulkProgress:       controller ? controller.bulkProgress       : 0
    readonly property int    _bulkProgressTotal:  controller ? controller.bulkProgressTotal  : 0
    readonly property bool   _isUnlocking:        controller ? controller.isUnlocking        : false

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

    // Parsed folder filter (single active path, or "" for All)
    readonly property var _searchFolderFiltersArray: {
        try { return JSON.parse(_searchFolderFilters) } catch(e) { return [] }
    }

    // Parsed list of indexed folders for the folder combo
    readonly property var _searchFolderList: {
        try { return JSON.parse(_searchFolderListJson) } catch(e) { return [] }
    }

    // ── Dialogs ───────────────────────────────────────────────────────────

    // ExifTool-missing warning — shown once after unlock if exiftool is not found
    Dialog {
        id: exiftoolMissingDialog
        title: qsTr("ExifTool not found")
        standardButtons: Dialog.Ok
        anchors.centerIn: Overlay.overlay
        width: 420
        modal: true

        Connections {
            target: controller
            function onExiftoolMissingChanged() {
                if (controller.exiftoolMissing)
                    exiftoolMissingDialog.open()
            }
        }

        ColumnLayout {
            width: parent.width
            spacing: 12

            Label {
                Layout.fillWidth: true
                text: qsTr("ExifTool was not found on your system. Indexing is disabled until ExifTool is installed and available on your PATH.")
                wrapMode: Text.WordWrap
                font.pixelSize: 13
            }

            Label {
                Layout.fillWidth: true
                text: qsTr("Download ExifTool from:")
                font.pixelSize: 13
            }

            Label {
                Layout.fillWidth: true
                text: "<a href='https://exiftool.org/' style='color: " + Material.accent + ";'>https://exiftool.org/</a>"
                font.pixelSize: 13
                textFormat: Text.RichText
                onLinkActivated: (link) => Qt.openUrlExternally(link)
                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }

            Label {
                Layout.fillWidth: true
                text: qsTr("After installing ExifTool, restart exif-turbo.")
                font.pixelSize: 12
                opacity: 0.7
                wrapMode: Text.WordWrap
            }
        }
    }

    Dialog {
        id: aboutDialog
        title: qsTr("About exif-turbo")
        standardButtons: Dialog.Ok
        anchors.centerIn: Overlay.overlay
        width: 340

        Label {
            text: "exif-turbo" + (_appVersion ? " v" + _appVersion : "") + "\n\n" +
                  qsTr("Cross-platform image EXIF metadata\nsearch and indexing tool.") +
                  "\n\n" + qsTr("License: MIT")
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
                    if (request.navigationType === WebEngineNavigationRequest.LinkClickedNavigation) {
                        Qt.openUrlExternally(request.url)
                        request.action = WebEngineNavigationRequest.IgnoreRequest
                        request.accepted = false
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
            id: selectMenu
            title: qsTr("&Select")
            // Auto-size to the widest item label so long entries (e.g.
            // "Select Images Without Thumbnail") are never truncated.
            TextMetrics {
                id: selectMenuMetrics
                font: selectMenu.font
                text: selectMissingItem.text
            }
            implicitWidth: selectMenuMetrics.width + 64

            Action {
                text: qsTr("Select &All")
                enabled: !_isLocked
                onTriggered: if (!_isLocked) controller.selectAll()
            }
            Action {
                text: qsTr("&Deselect All")
                enabled: !_isLocked
                onTriggered: if (!_isLocked) controller.deselectAll()
            }
            Action {
                text: qsTr("&Invert Selection")
                enabled: !_isLocked
                onTriggered: if (!_isLocked) controller.invertSelection()
            }
            MenuSeparator {}
            Action {
                id: selectMissingItem
                text: qsTr("Select Images Without &Thumbnail")
                enabled: !_isLocked
                onTriggered: if (!_isLocked) controller.selectMissingThumbnails()
            }
        }
        Menu {
            id: actionMenu
            title: qsTr("&Action")
            // Auto-size to the widest item label so long entries (e.g. "Delete
            // Marked Images… (1234 selected)") are never truncated.  Width is
            // measured via TextMetrics on the live action texts.
            TextMetrics {
                id: actionMenuMetrics
                font: actionMenu.font
                text: {
                    const a = exportJsonItem.text
                    const b = deleteMarkedItem.text
                    return a.length > b.length ? a : b
                }
            }
            implicitWidth: actionMenuMetrics.width + 64

            Action {
                id: exportJsonItem
                readonly property int _cnt: controller ? controller.checkedCount : 0
                text: _cnt > 0
                      ? qsTr("Export Metadata as &JSON\u2026 (%1 selected)").arg(_cnt)
                      : qsTr("Export Metadata as &JSON\u2026 (all results)")
                enabled: !_isLocked
                onTriggered: if (!_isLocked) exportJsonDialog.open()
            }
            MenuSeparator {}
            Action {
                id: deleteMarkedItem
                readonly property int _cnt: controller ? controller.checkedCount : 0
                text: qsTr("&Delete Marked Images\u2026 (%1 selected)").arg(_cnt)
                enabled: !_isLocked && _cnt > 0
                onTriggered: if (!_isLocked && _cnt > 0) deleteMarkedDialog.open()
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

    // ── Export-metadata file dialog ───────────────────────────────────────
    FileDialog {
        id: exportJsonDialog
        title: qsTr("Export Metadata as JSON")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("JSON files (*.json)"), qsTr("All files (*)")]
        defaultSuffix: "json"
        onAccepted: controller.exportMarkedMetadataJson(selectedFile)
    }

    // ── Delete-marked confirmation dialog ─────────────────────────────────
    Dialog {
        id: deleteMarkedDialog
        title: qsTr("Delete Marked Images")
        standardButtons: Dialog.Yes | Dialog.Cancel
        anchors.centerIn: Overlay.overlay
        modal: true
        width: 460

        readonly property int expectedCount: controller ? controller.checkedCount : 0
        readonly property bool _confirmed:
            parseInt(confirmCountField.text, 10) === expectedCount && expectedCount > 0

        onOpened: {
            confirmCountField.text = ""
            confirmCountField.forceActiveFocus()
            _refreshYesEnabled()
        }
        on_ConfirmedChanged: _refreshYesEnabled()

        function _refreshYesEnabled() {
            const yesBtn = standardButton(Dialog.Yes)
            if (yesBtn) yesBtn.enabled = _confirmed
        }

        ColumnLayout {
            width: parent.width
            spacing: 12

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("Permanently delete %1 marked image file(s) from disk and remove them from the index?\n\nThis cannot be undone.")
                    .arg(deleteMarkedDialog.expectedCount)
            }

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("To confirm, type the number %1 below:")
                    .arg(deleteMarkedDialog.expectedCount)
            }

            TextField {
                id: confirmCountField
                Layout.fillWidth: true
                placeholderText: qsTr("Enter %1").arg(deleteMarkedDialog.expectedCount)
                inputMethodHints: Qt.ImhDigitsOnly
                validator: IntValidator { bottom: 0 }
                onAccepted: if (deleteMarkedDialog._confirmed) deleteMarkedDialog.accept()
            }
        }

        onAccepted: {
            if (_confirmed) controller.deleteMarkedImages()
        }
    }

    // ── Toolbar (hidden — search moved into Search tab) ─────────────────
    header: ToolBar {
        implicitHeight: 0
        visible: false
    }

    // ── Lock screen ───────────────────────────────────────────────────────
    // Use a Loader so the password TextFields are *destroyed* (not just hidden)
    // after unlock. If they remain in the component tree with echoMode:Password,
    // macOS AutoFill service detects them and injects an "AutoFill" entry into
    // every native menu bar menu.
    Loader {
        anchors.fill: parent
        z: 100
        active: _isLocked
        sourceComponent: Component {
            Pane {
                id: lockOverlay
                anchors.fill: parent

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
                            Keys.onReturnPressed: lockOverlay._tryCreate()
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
                            enabled: !_isUnlocking && (_isNewDatabase
                                     ? (passwordField.text.length >= 1 && passwordField.text === confirmField.text)
                                     : passwordField.text.length >= 1)
                            onClicked: _isNewDatabase ? lockOverlay._tryCreate() : controller.unlock(passwordField.text)
                        }

                        // Unlock-in-progress indicator
                        RowLayout {
                            Layout.alignment: Qt.AlignHCenter
                            visible: _isUnlocking
                            spacing: 10

                            BusyIndicator {
                                running: _isUnlocking
                                implicitWidth: 28
                                implicitHeight: 28
                            }

                            Label {
                                text: qsTr("Unlocking…")
                                font.pixelSize: 13
                                opacity: 0.75
                            }
                        }
                    }
                }

                function _tryCreate() {
                    if (passwordField.text !== confirmField.text) return
                    controller.unlock(passwordField.text)
                }
            }
        }
    }

    // ── Progress panel (non-blocking, bottom-right corner) ───────────────
    Pane {
        id: progressPanel
        anchors { right: parent.right; bottom: parent.bottom; margins: 16 }
        width: 380
        visible: !_isLocked && (_isIndexing || _isBuildingThumbs || _isBuildingPreviews) && mainTabBar.currentIndex === 2
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
                    if (_isBuildingPreviews) return qsTr("Building Previews")
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
                    if (_isBuildingPreviews) return _previewTotal > 0 ? _previewTotal : 1
                    return _thumbTotal > 0 ? _thumbTotal : 1
                }
                value: _isIndexing
                       ? _indexCurrent
                       : (_isBuildingPreviews ? _previewCurrent : _thumbCurrent)
                indeterminate: _isIndexing
                       ? _indexTotal === 0
                       : (_isBuildingPreviews ? _previewTotal === 0 : _thumbTotal === 0)
            }

            // Count label
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: {
                    if (_isIndexing)
                        return _indexTotal > 0
                            ? _indexCurrent + " / " + _indexTotal + " " + qsTr("files")
                            : _indexCurrent > 0
                                ? _indexCurrent + " " + qsTr("indexed, scanning\u2026")
                                : qsTr("Scanning for images\u2026")
                    if (_isBuildingPreviews)
                        return _previewTotal > 0
                            ? _previewCurrent + " / " + _previewTotal + " " + qsTr("images")
                            : qsTr("Preparing\u2026")
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
                text: _isIndexing
                      ? _indexCurrentFile
                      : (_isBuildingPreviews ? _previewCurrentFile : _thumbCurrentFile)
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
                    if (_isBuildingPreviews) return qsTr("Cancel Previews")
                    return canceling ? qsTr("Canceling\u2026") : qsTr("Cancel Thumbnails")
                }
                enabled: !(controller ? controller.isCanceling : false)
                highlighted: true
                Material.accent: Material.Red
                implicitHeight: 36
                implicitWidth: 160
                onClicked: {
                    if (_isIndexing) controller.cancelIndex()
                    else if (_isBuildingPreviews) controller.cancelPreviewBuild()
                    else controller.cancelThumbnails()
                }
            }
        }
    }

    // ── Tab bar background (full-width row behind the buttons) ───────────
    // ── Busy overlay (blocks UI during bulk operations) ───────────────────
    Rectangle {
        id: busyOverlay
        anchors.fill: parent
        z: 60
        visible: _isBusy
        color: Qt.rgba(0, 0, 0, 0.45)

        // Swallow all mouse/touch events so the UI is fully blocked
        MouseArea { anchors.fill: parent; hoverEnabled: true }

        Pane {
            anchors.centerIn: parent
            width: 320
            Material.elevation: 8
            padding: 28

            ColumnLayout {
                anchors.fill: parent
                spacing: 18

                BusyIndicator {
                    Layout.alignment: Qt.AlignHCenter
                    running: _isBusy
                }

                Label {
                    Layout.fillWidth: true
                    text: _busyLabel
                    font.pixelSize: 14
                    font.weight: Font.Medium
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }

                ProgressBar {
                    Layout.fillWidth: true
                    indeterminate: _bulkProgressTotal === 0
                    from: 0
                    to: Math.max(1, _bulkProgressTotal)
                    value: _bulkProgress
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    visible: _bulkProgressTotal > 0
                    text: _bulkProgress + " / " + _bulkProgressTotal
                    font.pixelSize: 12
                    opacity: 0.7
                }

                Button {
                    Layout.alignment: Qt.AlignHCenter
                    text: qsTr("Cancel")
                    highlighted: true
                    Material.accent: Material.Red
                    implicitWidth: 120
                    implicitHeight: 36
                    visible: controller ? controller.busyCancelable : true
                    onClicked: controller.cancelBulkOp()
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
                                    anchors { left: parent.left; right: parent.right; leftMargin: 10; rightMargin: text.length > 0 ? 52 : 32; verticalCenter: parent.verticalCenter }
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
                                    anchors { right: searchHelpButton.left; rightMargin: 2; verticalCenter: parent.verticalCenter }
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

                                // Help (?) button — shows search-syntax hints on hover
                                Item {
                                    id: searchHelpButton
                                    anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                                    width: 20; height: 20

                                    Text {
                                        anchors.centerIn: parent
                                        text: "?"
                                        font.pixelSize: 13
                                        font.bold: true
                                        color: Material.foreground
                                        opacity: searchHelpHover.hovered ? 1.0 : 0.45
                                        Behavior on opacity { NumberAnimation { duration: 80 } }
                                    }

                                    HoverHandler { id: searchHelpHover }

                                    ToolTip {
                                        id: searchHelpTip
                                        visible: searchHelpHover.hovered
                                        delay: 300
                                        timeout: 20000
                                        // Anchor the tip below the help icon so it doesn't cover the search field
                                        x: -contentItem.implicitWidth + searchHelpButton.width
                                        y: searchHelpButton.height + 6
                                        padding: 12

                                        contentItem: ColumnLayout {
                                            spacing: 8

                                            Label {
                                                text: qsTr("Search syntax")
                                                font.pixelSize: 13
                                                font.bold: true
                                                color: root._accentColor
                                            }

                                            GridLayout {
                                                columns: 2
                                                columnSpacing: 16
                                                rowSpacing: 4

                                                // header row
                                                Label { text: qsTr("Example"); font.pixelSize: 11; font.bold: true; opacity: 0.65 }
                                                Label { text: qsTr("Meaning"); font.pixelSize: 11; font.bold: true; opacity: 0.65 }

                                                Label { text: "canon";          font.family: monoFont; font.pixelSize: 12 }
                                                Label { text: qsTr("single token"); font.pixelSize: 12 }

                                                Label { text: "canon r5";       font.family: monoFont; font.pixelSize: 12 }
                                                Label { text: qsTr("both tokens (implicit AND)"); font.pixelSize: 12 }

                                                Label { text: "canon OR nikon"; font.family: monoFont; font.pixelSize: 12 }
                                                Label { text: qsTr("either token"); font.pixelSize: 12 }

                                                Label { text: "canon NOT raw";  font.family: monoFont; font.pixelSize: 12 }
                                                Label { text: qsTr("exclude token"); font.pixelSize: 12 }

                                                Label { text: "\"Z 9\"";        font.family: monoFont; font.pixelSize: 12 }
                                                Label { text: qsTr("exact phrase"); font.pixelSize: 12 }

                                                Label { text: "summer*";        font.family: monoFont; font.pixelSize: 12 }
                                                Label { text: qsTr("prefix wildcard"); font.pixelSize: 12 }
                                            }

                                            Rectangle {
                                                Layout.fillWidth: true
                                                height: 1
                                                color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.15)
                                            }

                                            Label {
                                                text: qsTr("Tips")
                                                font.pixelSize: 13
                                                font.bold: true
                                                color: root._accentColor
                                            }

                                            Label {
                                                text: qsTr("• Operators AND, OR, NOT must be UPPERCASE\n• Quote multi-word phrases\n• In ExifTool keys (e.g. GPS:GPSLatitude) the colon acts as a separator")
                                                font.pixelSize: 12
                                                lineHeight: 1.25
                                                wrapMode: Text.WordWrap
                                            }
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
                                text: qsTr("Folder(s)")
                                font.pixelSize: 11
                                opacity: 0.6
                                visible: root._indexedFolderCount > 1
                            }

                            // Checked-only filter chip
                            Rectangle {
                                id: checkedFilterChip
                                visible: controller && (controller.checkedCount > 0 || controller.checkedOnlyFilter)
                                implicitHeight: 22
                                implicitWidth: _chipLabel.implicitWidth + 14
                                radius: 11
                                color: controller && controller.checkedOnlyFilter
                                       ? root._accentColor
                                       : Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.15)

                                Label {
                                    id: _chipLabel
                                    anchors.centerIn: parent
                                    text: {
                                        if (!controller) return "\u2611 0"
                                        var total = controller.checkedCount
                                        var here = controller.checkedInResultsCount
                                        return here === total
                                            ? "\u2611 " + total
                                            : "\u2611 " + here + "/" + total
                                    }
                                    font.pixelSize: 11
                                    font.weight: controller && controller.checkedOnlyFilter ? Font.DemiBold : Font.Normal
                                    color: controller && controller.checkedOnlyFilter ? "white" : Material.foreground
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    hoverEnabled: true
                                    onClicked: controller.setCheckedOnlyFilter(!controller.checkedOnlyFilter)
                                    ToolTip.text: controller && controller.checkedOnlyFilter
                                                  ? qsTr("Show all results")
                                                  : qsTr("Show only selected images")
                                    ToolTip.visible: containsMouse
                                    ToolTip.delay: 600
                                }
                            }

                            // Multi-select folder filter — checkbox popup inside a ComboBox shell
                            ComboBox {
                                id: folderMultiCombo
                                objectName: "folderMultiCombo"
                                visible: root._indexedFolderCount > 1
                                implicitHeight: 28
                                implicitWidth: 170
                                font.pixelSize: 11
                                model: []   // no model items; displayText is computed

                                displayText: {
                                    var active = root._searchFolderFiltersArray
                                    if (active.length === 0) return qsTr("All folders")
                                    if (active.length === 1) {
                                        var folders = root._searchFolderList
                                        for (var i = 0; i < folders.length; i++) {
                                            if (folders[i].path === active[0]) return folders[i].name
                                        }
                                    }
                                    return qsTr("%1 folders").arg(active.length)
                                }

                                popup: Popup {
                                    y: folderMultiCombo.height + 2
                                    width: folderMultiCombo.width
                                    padding: 6
                                    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

                                    Column {
                                        width: parent.width
                                        spacing: 0

                                        CheckBox {
                                            width: parent.width
                                            text: qsTr("All folders")
                                            font.pixelSize: 11
                                            checked: root._searchFolderFiltersArray.length === 0
                                            onClicked: controller.clearSearchFolderFilters()
                                        }

                                        Repeater {
                                            model: root._searchFolderList
                                            delegate: CheckBox {
                                                required property var modelData
                                                width: parent.width
                                                text: modelData.name
                                                font.pixelSize: 11
                                                checked: root._searchFolderFiltersArray.indexOf(modelData.path) >= 0
                                                onClicked: controller.toggleSearchFolderFilter(modelData.path)
                                                ToolTip.text: modelData.path
                                                ToolTip.visible: hovered
                                                ToolTip.delay: 600
                                            }
                                        }
                                    }
                                }

                                onActivated: {}  // prevent default single-select behavior
                            }

                            Label {
                                text: qsTr("Sort")
                                font.pixelSize: 11
                                opacity: 0.6
                            }

                            ComboBox {
                                id: sortCombo
                                objectName: "sortCombo"
                                implicitHeight: 28
                                font.pixelSize: 11

                                // Grow to the widest translated label so no popup entry is
                                // ever clipped.  FontMetrics.advanceWidth() is an invokable
                                // method — not a property read — so it does not register
                                // as a reactive dependency and avoids a re-entrant loop.
                                // Reading `_sortFM.font` creates the font-change dependency.
                                implicitWidth: {
                                    var _f = _sortFM.font
                                    var w = 0
                                    for (var i = 0; i < _opts.length; i++)
                                        w = Math.max(w, _sortFM.advanceWidth(_opts[i].text))
                                    return w + leftPadding + rightPadding
                                         + (indicator ? indicator.width : 0)
                                }

                                FontMetrics { id: _sortFM; font: sortCombo.font }

                                readonly property var _opts: [
                                    { text: qsTr("Name A→Z"),      value: "filename_asc"  },
                                    { text: qsTr("Name Z→A"),      value: "filename_desc" },
                                    { text: qsTr("Path A→Z"),      value: "path_asc"      },
                                    { text: qsTr("Path Z→A"),      value: "path_desc"     },
                                    { text: qsTr("Newest first"),  value: "date_desc"     },
                                    { text: qsTr("Oldest first"),  value: "date_asc"      },
                                    { text: qsTr("Largest"),       value: "size_desc"     },
                                    { text: qsTr("Smallest"),      value: "size_asc"      },
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

                    // Format facet chips — hidden when only one format and
                    // no active filter. We keep the row visible whenever an
                    // ext filter is active so the user can always switch back
                    // to "All" or to another available format.
                    Rectangle {
                        Layout.fillWidth: true
                        readonly property bool _showChips: root._formats.length > 1 || root._extFilter !== ""
                        implicitHeight: _showChips ? 36 : 0
                        visible: _showChips
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

                    // Search error banner — replaces results when a query
                    // fails (e.g. malformed FTS expression).
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: root._searchError !== ""

                        ColumnLayout {
                            anchors.centerIn: parent
                            width: Math.min(parent.width - 32, 480)
                            spacing: 8

                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: qsTr("Search failed")
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                                color: Material.color(Material.Red)
                            }
                            Label {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                                text: root._searchError
                                font.pixelSize: 12
                                opacity: 0.75
                            }
                        }
                    }

                    ListView {
                        id: resultsList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        visible: root._searchError === ""
                        model: filteredSearchModel
                        currentIndex: controller ? controller.currentProxyResultRow : -1
                        ScrollBar.vertical: ScrollBar {}

                        WheelHandler {
                            onWheel: (event) => {
                                var delta = event.pixelDelta.y !== 0
                                    ? -event.pixelDelta.y
                                    : -event.angleDelta.y / 120.0 * 210
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

                            readonly property string _sizeText: {
                                var bytes = model.fileSize || 0
                                if (bytes <= 0)  return ""
                                if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB"
                                if (bytes >= 1048576)    return (bytes / 1048576).toFixed(1) + " MB"
                                return Math.round(bytes / 1024) + " KB"
                            }
                            readonly property string _camera: model.camera ?? ""
                            readonly property string _date:   model.date   ?? ""
                            readonly property string _dims:   model.dims   ?? ""
                            readonly property string _lens:   model.lens   ?? ""

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
                                            { label: qsTr("Date"),       value: _date     },
                                            { label: qsTr("Dimensions"), value: _dims     },
                                            { label: qsTr("Exposure"),   value: _lens     },
                                            { label: qsTr("File size"),  value: _sizeText },
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

                            // Selection checkbox — bottom-right corner, above MouseArea
                            CheckBox {
                                anchors {
                                    right: parent.right
                                    bottom: parent.bottom
                                    rightMargin: 14
                                    bottomMargin: 4
                                }
                                z: 2
                                checked: model.checked
                                padding: 4
                                onToggled: controller.toggleChecked(index)
                                ToolTip.text: checked ? qsTr("Deselect image") : qsTr("Select image")
                                ToolTip.visible: hovered
                                ToolTip.delay: 600
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

                        // Copy to clipboard button
                        Rectangle {
                            id: copyToClipboardBtn
                            anchors {
                                right: previewSourceToggle.visible ? previewSourceToggle.left : parent.right
                                rightMargin: previewSourceToggle.visible ? 6 : 8
                                verticalCenter: parent.verticalCenter
                            }
                            width: copyToClipboardLabel.implicitWidth + 28
                            height: 22
                            radius: 11
                            color: Qt.rgba(0, 0, 0, copyBtnArea.containsMouse ? 0.75 : 0.45)
                            border.color: Qt.rgba(1, 1, 1, 0.25)
                            border.width: 1
                            visible: _selectedImageSource !== ""
                            opacity: copyBtnArea.containsMouse ? 1.0 : 0.5
                            Behavior on color { ColorAnimation { duration: 120 } }
                            Behavior on opacity { NumberAnimation { duration: 120 } }

                            Label {
                                id: copyToClipboardLabel
                                anchors.centerIn: parent
                                text: qsTr("Copy")
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                color: "#ffffff"
                            }

                            MouseArea {
                                id: copyBtnArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { if (controller) controller.copyPreviewToClipboard() }
                            }

                            ToolTip.text: qsTr("Copy preview image to clipboard")
                            ToolTip.visible: copyBtnArea.containsMouse
                            ToolTip.delay: 400
                        }

                        // Preview / Raw source toggle — lets the user override
                        // the cached preview to load the full-resolution raw
                        // file when zooming in for detail.
                        Rectangle {
                            id: previewSourceToggle
                            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            width: previewSourceLabel.implicitWidth + 28
                            height: 22
                            radius: 11
                            color: Qt.rgba(0, 0, 0, sourceToggleArea.containsMouse ? 0.75 : 0.45)
                            border.color: Qt.rgba(1, 1, 1, 0.25)
                            border.width: 1
                            visible: _selectedImageSource !== "" && controller && controller.selectedHasPreview
                            opacity: sourceToggleArea.containsMouse ? 1.0 : 0.5
                            Behavior on color { ColorAnimation { duration: 120 } }
                            Behavior on opacity { NumberAnimation { duration: 120 } }

                            Row {
                                anchors.centerIn: parent
                                spacing: 6
                                Rectangle {
                                    width: 8; height: 8; radius: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: (controller && controller.useRawPreview) ? "#ff9800" : "#4caf50"
                                }
                                Label {
                                    id: previewSourceLabel
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: (controller && controller.useRawPreview) ? qsTr("Show Preview") : qsTr("Show Original")
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                    color: "#ffffff"
                                }
                            }

                            MouseArea {
                                id: sourceToggleArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (controller)
                                        controller.setUseRawPreview(!controller.useRawPreview)
                                }
                            }

                            ToolTip.text: (controller && controller.useRawPreview)
                                          ? qsTr("Showing full-resolution source. Click to use cached preview.")
                                          : qsTr("Showing cached preview. Click to load the full-resolution source.")
                            ToolTip.visible: sourceToggleArea.containsMouse
                            ToolTip.delay: 400
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

                            // Low-res thumbnail placeholder — visible from
                            // cache immediately and stays put underneath while
                            // the full preview / raw image fades in on top.
                            Image {
                                id: thumbPreview
                                width:  previewFlick.contentWidth
                                height: previewFlick.contentHeight
                                source: _selectedThumbSource
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                visible: _selectedThumbSource !== ""
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
                                Behavior on opacity { NumberAnimation { duration: 200 } }
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

                            // Right-click context menu
                            TapHandler {
                                acceptedButtons: Qt.RightButton
                                onTapped: (eventPoint) => {
                                    previewContextMenu.popup()
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

                        // Loading overlay — shown while the full preview / original
                        // image is decoding (full-resolution originals can take a
                        // few seconds, especially for raws and large JPEGs).
                        Rectangle {
                            id: previewLoadingOverlay
                            anchors.centerIn: parent
                            width: previewLoadingRow.implicitWidth + 24
                            height: previewLoadingRow.implicitHeight + 14
                            radius: 6
                            color: Qt.rgba(0, 0, 0, 0.55)
                            visible: opacity > 0.0
                            // Only show the overlay when loading the full original
                            // image — cached previews load quickly enough that an
                            // overlay would just flicker on screen.
                            opacity: (fullPreview.status === Image.Loading
                                      && controller && controller.useRawPreview) ? 1.0 : 0.0
                            Behavior on opacity { NumberAnimation { duration: 150 } }

                            Row {
                                id: previewLoadingRow
                                anchors.centerIn: parent
                                spacing: 8
                                BusyIndicator {
                                    width: 18; height: 18
                                    anchors.verticalCenter: parent.verticalCenter
                                    running: previewLoadingOverlay.visible
                                }
                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: qsTr("Loading original\u2026")
                                    font.pixelSize: 12
                                    color: "#ffffff"
                                }
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

                    // OpenStreetMap link bar — visible when GPS coordinates are present
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: _geoLocationUrl !== "" ? 30 : 0
                        visible: _geoLocationUrl !== ""
                        color: Qt.rgba(root._accentColor.r, root._accentColor.g, root._accentColor.b, 0.07)

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 8 }
                            spacing: 6

                            Label {
                                text: "\ud83d\uddfa"
                                font.pixelSize: 13
                            }
                            Label {
                                text: qsTr("GPS location —")
                                font.pixelSize: 11
                                opacity: 0.65
                            }
                            Label {
                                text: qsTr("OpenStreetMap")
                                font.pixelSize: 11
                                color: Material.accent
                                font.underline: true
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Qt.openUrlExternally(_geoLocationUrl)
                                }
                                ToolTip.text: _geoLocationUrl
                                ToolTip.visible: osmLinkHover.hovered
                                HoverHandler { id: osmLinkHover }
                            }
                            Label {
                                text: "|"
                                font.pixelSize: 11
                                opacity: 0.35
                            }
                            Label {
                                text: qsTr("Google Maps")
                                font.pixelSize: 11
                                color: Material.accent
                                font.underline: true
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Qt.openUrlExternally(_geoGoogleMapsUrl)
                                }
                                ToolTip.text: _geoGoogleMapsUrl
                                ToolTip.visible: gmapsLinkHover.hovered
                                HoverHandler { id: gmapsLinkHover }
                            }
                            Label {
                                text: "|"
                                font.pixelSize: 11
                                opacity: 0.35
                            }
                            Label {
                                text: qsTr("GeoHack")
                                font.pixelSize: 11
                                color: Material.accent
                                font.underline: true
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Qt.openUrlExternally(_geoWikipediaUrl)
                                }
                                ToolTip.text: _geoWikipediaUrl
                                ToolTip.visible: wikiLinkHover.hovered
                                HoverHandler { id: wikiLinkHover }
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }

                    Flickable {
                        id: detailsScrollView
                        objectName: "detailsScrollView"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: width
                        contentHeight: detailsEditLoader.item
                            ? detailsEditLoader.item.implicitHeight + detailsEditLoader.item.padding * 2
                            : 0
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            id: detailsVBar
                            policy: ScrollBar.AsNeeded
                        }

                        // The TextEdit is recreated on every detailsHtml change
                        // to defeat a Qt 6.10 RHI bug where TextEdit.RichText
                        // leaves stale (black) tiles after replacing a long
                        // document from a scrolled position. A fresh component
                        // instance has a clean layout cache.
                        property string detailsHtmlSnapshot: controller ? controller.detailsHtml : ""
                        onDetailsHtmlSnapshotChanged: {
                            detailsEditLoader.active = false
                            detailsEditLoader.active = true
                            contentY = 0
                        }

                        Loader {
                            id: detailsEditLoader
                            width: detailsScrollView.width
                            active: true
                            sourceComponent: detailsEditComponent
                        }

                        Component {
                            id: detailsEditComponent
                            TextEdit {
                                objectName: "detailsArea"
                                readOnly: true
                                selectByMouse: true
                                selectByKeyboard: true
                                persistentSelection: false
                                textFormat: TextEdit.RichText
                                text: detailsScrollView.detailsHtmlSnapshot
                                wrapMode: TextEdit.Wrap
                                font.family: root.monoFont
                                font.pixelSize: 12
                                color: Material.foreground
                                selectionColor: Material.accent
                                selectedTextColor: Material.background
                                width: detailsScrollView.width - padding * 2
                                x: padding
                                y: padding
                                property real padding: 8
                            }
                        }

                        Label {
                            anchors.centerIn: parent
                            visible: detailsScrollView.detailsHtmlSnapshot.length === 0
                            text: qsTr("Select an image to see metadata")
                            opacity: 0.4
                        }
                    }
                }

                Connections {
                    target: controller
                    function onFindScrollFractionChanged() {
                        detailsScrollView.contentY = controller.findScrollFraction
                            * Math.max(0, detailsScrollView.contentHeight - detailsScrollView.height)
                    }
                    function onGeoLocationUrlChanged() {
                        // Defer until after the ColumnLayout has finished its resize pass.
                        Qt.callLater(function() {
                            detailsScrollView.contentY = 0
                        })
                    }
                    function onDetailsHtmlChanged() {
                        detailsScrollView.contentY = 0
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
                        model: root._folderFilter !== "" ? filteredSearchModel : null
                        currentIndex: controller ? controller.currentProxyResultRow : -1
                        ScrollBar.vertical: ScrollBar {}

                        WheelHandler {
                            onWheel: (event) => {
                                var delta = event.pixelDelta.y !== 0
                                    ? -event.pixelDelta.y
                                    : -event.angleDelta.y / 120.0 * 210
                                browseImageList.contentY = Math.max(0,
                                    Math.min(browseImageList.contentY + delta,
                                             Math.max(0, browseImageList.contentHeight - browseImageList.height)))
                                event.accepted = true
                            }
                        }

                        delegate: Rectangle {
                            id: browseCardDelegate
                            width: browseImageList.width
                            height: 210
                            color: "transparent"

                            readonly property bool _isSelected: ListView.isCurrentItem

                            readonly property string _sizeText: {
                                var bytes = model.fileSize || 0
                                if (bytes <= 0)  return ""
                                if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB"
                                if (bytes >= 1048576)    return (bytes / 1048576).toFixed(1) + " MB"
                                return Math.round(bytes / 1024) + " KB"
                            }
                            readonly property string _camera: model.camera ?? ""
                            readonly property string _date:   model.date   ?? ""
                            readonly property string _dims:   model.dims   ?? ""
                            readonly property string _lens:   model.lens   ?? ""

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
                                            { label: qsTr("Camera"),     value: _camera   },
                                            { label: qsTr("Date"),       value: _date     },
                                            { label: qsTr("Dimensions"), value: _dims     },
                                            { label: qsTr("Exposure"),   value: _lens     },
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

                            // Selection checkbox — bottom-right corner, above MouseArea
                            CheckBox {
                                anchors {
                                    right: parent.right
                                    bottom: parent.bottom
                                    rightMargin: 14
                                    bottomMargin: 4
                                }
                                z: 2
                                checked: model.checked
                                padding: 4
                                onToggled: controller.toggleChecked(index)
                                ToolTip.text: checked ? qsTr("Deselect image") : qsTr("Select image")
                                ToolTip.visible: hovered
                                ToolTip.delay: 600
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

                        // Copy to clipboard button
                        Rectangle {
                            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            width: copyToClipboardLabel2.implicitWidth + 28
                            height: 22
                            radius: 11
                            color: Qt.rgba(0, 0, 0, copyBtnArea2.containsMouse ? 0.75 : 0.45)
                            border.color: Qt.rgba(1, 1, 1, 0.25)
                            border.width: 1
                            visible: _selectedImageSource !== ""
                            opacity: copyBtnArea2.containsMouse ? 1.0 : 0.5
                            Behavior on color { ColorAnimation { duration: 120 } }
                            Behavior on opacity { NumberAnimation { duration: 120 } }

                            Label {
                                id: copyToClipboardLabel2
                                anchors.centerIn: parent
                                text: qsTr("Copy")
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                color: "#ffffff"
                            }

                            MouseArea {
                                id: copyBtnArea2
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { if (controller) controller.copyPreviewToClipboard() }
                            }

                            ToolTip.text: qsTr("Copy preview image to clipboard")
                            ToolTip.visible: copyBtnArea2.containsMouse
                            ToolTip.delay: 400
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

                            // Right-click context menu
                            TapHandler {
                                acceptedButtons: Qt.RightButton
                                onTapped: (eventPoint) => {
                                    previewContextMenu.popup()
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
                            enabled: true
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

                    // ── Preview cache size ────────────────────────────────
                    Label {
                        text: qsTr("Preview Cache Size")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 6
                    }
                    Label {
                        text: qsTr("Long-edge resolution used by the preview-cache builder. Larger values give sharper detail when zooming but take more disk space and longer to render.")
                        font.pixelSize: 12
                        opacity: 0.6
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.bottomMargin: 12
                    }
                    RowLayout {
                        spacing: 12
                        Layout.bottomMargin: 28

                        ComboBox {
                            id: previewSizeCombo
                            implicitWidth: 160
                            model: settingsModel ? settingsModel.previewSizeChoices : [2048]
                            currentIndex: {
                                var v = settingsModel ? settingsModel.previewMaxSize : 2048
                                var choices = settingsModel ? settingsModel.previewSizeChoices : [2048]
                                var idx = choices.indexOf(v)
                                return idx >= 0 ? idx : 0
                            }
                            onActivated: {
                                if (settingsModel)
                                    settingsModel.setPreviewMaxSize(model[currentIndex])
                            }
                        }
                        Label {
                            text: qsTr("pixels (long edge)")
                            font.pixelSize: 12
                            opacity: 0.7
                            verticalAlignment: Text.AlignVCenter
                        }
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

                    // ── ExifTool ──────────────────────────────────────────
                    Label {
                        text: qsTr("ExifTool")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 6
                    }
                    Label {
                        text: qsTr("ExifTool is required for indexing. It must be installed and available on your PATH.")
                        font.pixelSize: 12
                        opacity: 0.6
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.bottomMargin: 12
                    }

                    RowLayout {
                        spacing: 12
                        Layout.bottomMargin: 6

                        Button {
                            id: checkExiftoolButton
                            text: qsTr("Check")
                            implicitWidth: 100
                            onClicked: controller.checkExiftool()
                        }

                        // Status badge — shown after first check (or after unlock auto-check)
                        RowLayout {
                            id: exiftoolStatusRow
                            spacing: 6
                            visible: controller ? (controller.exiftoolVersion !== "" || controller.exiftoolMissing) : false

                            Rectangle {
                                width: 10; height: 10; radius: 5
                                color: (controller && controller.exiftoolMissing) ? "#ef5350" : "#66bb6a"
                            }

                            Label {
                                text: (controller && controller.exiftoolMissing)
                                    ? qsTr("Not found")
                                    : qsTr("Found — ExifTool %1").arg(controller ? controller.exiftoolVersion : "")
                                font.pixelSize: 13
                                color: (controller && controller.exiftoolMissing)
                                    ? (Material.theme === Material.Dark ? "#ef9a9a" : "#c62828")
                                    : (Material.theme === Material.Dark ? "#a5d6a7" : "#2e7d32")
                            }
                        }
                    }

                    // Download link — shown when exiftool is missing
                    Label {
                        visible: controller ? controller.exiftoolMissing : false
                        text: "<a href='https://exiftool.org/' style='color: " + Material.accent + ";'>https://exiftool.org/</a>"
                        font.pixelSize: 12
                        textFormat: Text.RichText
                        onLinkActivated: (link) => Qt.openUrlExternally(link)
                        Layout.bottomMargin: 2
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                    }

                    Label {
                        text: qsTr("After installing ExifTool, restart exif-turbo.")
                        visible: controller ? controller.exiftoolMissing : false
                        font.pixelSize: 11
                        opacity: 0.55
                        Layout.bottomMargin: 0
                    }

                    // spacer below the section
                    Item { height: 28; Layout.fillWidth: true }

                    Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor; Layout.bottomMargin: 28 }

                    // ── Change password ───────────────────────────────────
                    Label {
                        text: qsTr("Change Password")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 6
                    }
                    Label {
                        text: qsTr("Re-encrypts the database under a new password. Existing thumbnails are preserved.")
                        font.pixelSize: 12
                        opacity: 0.6
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.bottomMargin: 14
                    }
                    Button {
                        id: changePasswordButton
                        text: qsTr("Change Password\u2026")
                        enabled: !_isIndexing && !_isLocked
                        Layout.bottomMargin: 40
                        onClicked: {
                            changePasswordDialog.resetFields()
                            changePasswordDialog.open()
                        }
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

    // ── Change password dialog ────────────────────────────────────────────
    Dialog {
        id: changePasswordDialog
        title: qsTr("Change Password")
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 460
        closePolicy: changePasswordDialog.busy ? Popup.NoAutoClose : Popup.CloseOnEscape

        property bool busy: false

        function resetFields() {
            oldPwField.text = ""
            newPwField.text = ""
            confirmPwField.text = ""
            errorLabel.text = ""
            changePasswordDialog.busy = false
            confirmButton.enabled = true
            oldPwField.focus = true
        }

        Connections {
            target: controller
            function onPasswordChangeFinished(success, message) {
                changePasswordDialog.busy = false
                confirmButton.enabled = true
                if (success) {
                    changePasswordDialog.close()
                    passwordChangedDialog.message = message
                    passwordChangedDialog.open()
                } else {
                    errorLabel.color = Material.color(Material.Red)
                    errorLabel.text = message
                }
            }
        }

        ColumnLayout {
            width: parent.width
            spacing: 12

            Label {
                text: qsTr("Enter your current password and choose a new one.")
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Label { text: qsTr("Current password"); font.pixelSize: 12; opacity: 0.7 }
            TextField {
                id: oldPwField
                Layout.fillWidth: true
                echoMode: TextInput.Password
                enabled: !changePasswordDialog.busy
                onTextChanged: errorLabel.text = ""
            }

            Label { text: qsTr("New password"); font.pixelSize: 12; opacity: 0.7 }
            TextField {
                id: newPwField
                Layout.fillWidth: true
                echoMode: TextInput.Password
                enabled: !changePasswordDialog.busy
                onTextChanged: errorLabel.text = ""
            }

            Label { text: qsTr("Confirm new password"); font.pixelSize: 12; opacity: 0.7 }
            TextField {
                id: confirmPwField
                Layout.fillWidth: true
                echoMode: TextInput.Password
                enabled: !changePasswordDialog.busy
                onTextChanged: errorLabel.text = ""
                onAccepted: confirmButton.clicked()
            }

            RowLayout {
                Layout.fillWidth: true
                visible: changePasswordDialog.busy
                spacing: 10
                BusyIndicator {
                    running: changePasswordDialog.busy
                    Layout.preferredWidth: 22
                    Layout.preferredHeight: 22
                }
                Label {
                    text: qsTr("Changing password\u2026 This may take a moment.")
                    font.pixelSize: 12
                    Layout.fillWidth: true
                }
            }

            Label {
                id: errorLabel
                text: ""
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                visible: text !== ""
                font.pixelSize: 12
            }
        }

        footer: DialogButtonBox {
            Button {
                text: qsTr("Cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
                enabled: !changePasswordDialog.busy
                onClicked: changePasswordDialog.close()
            }
            Button {
                id: confirmButton
                text: qsTr("Change Password")
                // ApplyRole does NOT auto-close the dialog — we close it
                // ourselves only after the controller reports success.
                DialogButtonBox.buttonRole: DialogButtonBox.ApplyRole
                highlighted: true
                enabled: !changePasswordDialog.busy
                onClicked: {
                    if (newPwField.text === "") {
                        errorLabel.color = Material.color(Material.Red)
                        errorLabel.text = qsTr("New password must not be empty.")
                        return
                    }
                    if (newPwField.text !== confirmPwField.text) {
                        errorLabel.color = Material.color(Material.Red)
                        errorLabel.text = qsTr("New password and confirmation do not match.")
                        return
                    }
                    errorLabel.text = ""
                    changePasswordDialog.busy = true
                    controller.changePassword(oldPwField.text, newPwField.text)
                }
            }
        }

        onClosed: {
            busy = false
            confirmButton.enabled = true
        }
    }

    // ── Password changed confirmation dialog ──────────────────────────────
    Dialog {
        id: passwordChangedDialog
        property string message: ""
        title: qsTr("Password Changed")
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 380
        standardButtons: Dialog.Ok

        Label {
            width: 320
            wrapMode: Text.WordWrap
            text: passwordChangedDialog.message
        }
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
