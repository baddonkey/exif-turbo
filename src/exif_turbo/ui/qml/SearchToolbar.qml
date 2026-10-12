pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Rectangle {
    id: searchToolbar
    objectName: "searchToolbar"

    property bool aiEnabled: false
    property bool aiSearchMode: false
    property string aiSearchPrecision: "normal"
    property color accentColor: Material.accentColor
    property string monoFontFamily: "monospace"
    property alias queryText: searchField.text

    signal searchRequested(string query)
    signal aiSearchModeRequested(bool enabled)
    signal aiSearchPrecisionRequested(string precision)

    function focusQuery(): void {
        searchField.forceActiveFocus()
    }

    Layout.fillWidth: true
    height: 52
    color: Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.07)

    RowLayout {
        anchors { fill: parent; leftMargin: 10; rightMargin: 10; topMargin: 8; bottomMargin: 8 }
        spacing: 6

        Rectangle {
            visible: searchToolbar.aiEnabled
            implicitWidth: 82
            implicitHeight: 30
            radius: 4
            color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.08)
            border.color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.18)
            border.width: 1

            RowLayout {
                anchors.fill: parent
                spacing: 0

                Button {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    flat: true
                    text: qsTr("EXIF")
                    font.pixelSize: 11
                    font.bold: !searchToolbar.aiSearchMode
                    highlighted: !searchToolbar.aiSearchMode
                    onClicked: searchToolbar.aiSearchModeRequested(false)
                    topPadding: 0; bottomPadding: 0
                    leftPadding: 4; rightPadding: 4
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.18)
                }

                Button {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    flat: true
                    text: qsTr("AI")
                    font.pixelSize: 11
                    font.bold: searchToolbar.aiSearchMode
                    highlighted: searchToolbar.aiSearchMode
                    onClicked: searchToolbar.aiSearchModeRequested(true)
                    topPadding: 0; bottomPadding: 0
                    leftPadding: 4; rightPadding: 4
                }
            }
        }

        Rectangle {
            visible: searchToolbar.aiSearchMode
            implicitWidth: 148
            implicitHeight: 30
            radius: 4
            color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.08)
            border.color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.18)
            border.width: 1

            RowLayout {
                anchors.fill: parent
                spacing: 0

                Repeater {
                    model: [
                        { key: "fine", label: qsTr("Fine") },
                        { key: "normal", label: qsTr("Normal") },
                        { key: "broad", label: qsTr("Broad") },
                    ]

                    delegate: RowLayout {
                        required property int index
                        required property var modelData
                        spacing: 0
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        Rectangle {
                            visible: parent.index > 0
                            Layout.preferredWidth: 1
                            Layout.fillHeight: true
                            color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.18)
                        }

                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            flat: true
                            text: parent.modelData.label
                            font.pixelSize: 11
                            font.bold: searchToolbar.aiSearchPrecision === parent.modelData.key
                            highlighted: searchToolbar.aiSearchPrecision === parent.modelData.key
                            onClicked: searchToolbar.aiSearchPrecisionRequested(parent.modelData.key)
                            topPadding: 0; bottomPadding: 0
                            leftPadding: 4; rightPadding: 4
                            ToolTip.text: parent.modelData.key === "fine" ? qsTr("Precise — score ≥ 0.22 (strictest)") :
                                          parent.modelData.key === "normal" ? qsTr("Balanced — score ≥ 0.20") :
                                          qsTr("Broad — score ≥ 0.18 (most results)")
                            ToolTip.visible: hovered
                            ToolTip.delay: 600
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 36
            radius: 4
            color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.07)
            border.color: searchField.activeFocus ? searchToolbar.accentColor : Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.2)
            border.width: 1

            Label {
                anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                visible: searchField.text.length === 0
                text: searchToolbar.aiSearchMode ? qsTr("Describe what you’re looking for…") : qsTr("Search EXIF metadata…")
                font.pixelSize: 13
                opacity: 0.4
            }

            TextInput {
                id: searchField
                objectName: "searchField"
                anchors { left: parent.left; right: parent.right; leftMargin: 10; rightMargin: text.length > 0 ? 52 : 32; verticalCenter: parent.verticalCenter }
                font.pixelSize: 13
                color: Material.foreground
                selectedTextColor: "white"
                selectionColor: searchToolbar.accentColor
                clip: true
                Keys.onReturnPressed: searchToolbar.searchRequested(text)
            }

            Item {
                id: clearSearchButton
                objectName: "clearSearchButton"
                anchors { right: searchHelpButton.left; rightMargin: 2; verticalCenter: parent.verticalCenter }
                width: 20; height: 20
                visible: searchField.text.length > 0

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    font.pixelSize: 16
                    color: Material.foreground
                    opacity: clearSearchMouse.containsMouse ? 1.0 : 0.45
                    Behavior on opacity { NumberAnimation { duration: 80 } }
                }

                MouseArea {
                    id: clearSearchMouse
                    objectName: "clearSearchMouse"
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        searchField.text = ""
                        searchField.forceActiveFocus()
                        searchToolbar.searchRequested("")
                    }
                }
            }

            Item {
                id: searchHelpButton
                anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                width: 20; height: 20
                visible: !searchToolbar.aiSearchMode

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
                    x: -contentItem.implicitWidth + searchHelpButton.width
                    y: searchHelpButton.height + 6
                    padding: 12

                    contentItem: ColumnLayout {
                        spacing: 8

                        Label {
                            text: qsTr("Search syntax")
                            font.pixelSize: 13
                            font.bold: true
                            color: searchToolbar.accentColor
                        }

                        GridLayout {
                            columns: 2
                            columnSpacing: 16
                            rowSpacing: 4

                            Label { text: qsTr("Example"); font.pixelSize: 11; font.bold: true; opacity: 0.65 }
                            Label { text: qsTr("Meaning"); font.pixelSize: 11; font.bold: true; opacity: 0.65 }

                            Label { text: "canon"; font.family: searchToolbar.monoFontFamily; font.pixelSize: 12 }
                            Label { text: qsTr("single token"); font.pixelSize: 12 }

                            Label { text: "canon r5"; font.family: searchToolbar.monoFontFamily; font.pixelSize: 12 }
                            Label { text: qsTr("both tokens (implicit AND)"); font.pixelSize: 12 }

                            Label { text: "canon OR nikon"; font.family: searchToolbar.monoFontFamily; font.pixelSize: 12 }
                            Label { text: qsTr("either token"); font.pixelSize: 12 }

                            Label { text: "canon NOT raw"; font.family: searchToolbar.monoFontFamily; font.pixelSize: 12 }
                            Label { text: qsTr("exclude token"); font.pixelSize: 12 }

                            Label { text: "\"Z 9\""; font.family: searchToolbar.monoFontFamily; font.pixelSize: 12 }
                            Label { text: qsTr("exact phrase"); font.pixelSize: 12 }

                            Label { text: "summer*"; font.family: searchToolbar.monoFontFamily; font.pixelSize: 12 }
                            Label { text: qsTr("prefix wildcard"); font.pixelSize: 12 }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 1
                            color: Qt.rgba(Material.foreground.r, Material.foreground.g, Material.foreground.b, 0.15)
                        }

                        Label {
                            text: qsTr("Tips")
                            font.pixelSize: 13
                            font.bold: true
                            color: searchToolbar.accentColor
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
            onClicked: searchToolbar.searchRequested(searchField.text)
        }
    }
}
