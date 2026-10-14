pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Rectangle {
    id: dateFilterRow
    objectName: "dateFilterRow"

    property var years: []
    property bool loading: false
    property real dateFrom: -1
    property real dateTo: -1
    property color accentColor: Material.accentColor

    signal dateFilterRequested(real from, real to)
    signal dateFilterCleared()

    Layout.fillWidth: true
    readonly property bool _hasYears: years.length > 0
    readonly property bool _filterActive: dateFrom !== -1 || dateTo !== -1
    implicitHeight: (_hasYears || loading) ? contentRowLayout.implicitHeight + 8 : 0
    visible: _hasYears || loading
    color: Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.04)

    readonly property int _maxCount: {
        var maximum = 1
        for (var i = 0; i < years.length; i++)
            if (years[i].count > maximum) maximum = years[i].count
        return maximum
    }
    readonly property int _minYear: _hasYears ? years[0].year : 0
    readonly property int _maxYear: _hasYears ? years[years.length - 1].year : 0
    readonly property int _activeFrom: dateFrom !== -1
        ? new Date(dateFrom * 1000).getUTCFullYear() : _minYear
    readonly property int _activeTo: dateTo !== -1
        ? new Date(dateTo * 1000).getUTCFullYear() : _maxYear

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        hoverEnabled: true
        ToolTip.text: qsTr("Filter by capture date — click a year to select it, Shift-click to extend the range")
        ToolTip.visible: containsMouse
        ToolTip.delay: 600
    }

    RowLayout {
        id: contentRowLayout
        anchors { top: parent.top; left: parent.left; right: parent.right; leftMargin: 8; rightMargin: 8; topMargin: 4 }
        spacing: 8

        BusyIndicator {
            objectName: "timelineLoadingIndicator"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 22
            Layout.preferredHeight: 22
            running: dateFilterRow.loading
            visible: running
        }

        Label {
            Layout.alignment: Qt.AlignTop
            visible: dateFilterRow.loading && !dateFilterRow._hasYears
            text: qsTr("Loading timeline...")
            font.pixelSize: 10
            opacity: 0.65
        }

        Flow {
            Layout.fillWidth: true
            spacing: 2

            Repeater {
                model: dateFilterRow.years
                delegate: Item {
                    id: yearBarDelegate
                    required property var modelData
                    property bool _ready: false
                    Component.onCompleted: _ready = true
                    width: 18
                    height: 60

                    readonly property bool _inRange:
                        yearBarDelegate.modelData.year >= dateFilterRow._activeFrom &&
                        yearBarDelegate.modelData.year <= dateFilterRow._activeTo
                    readonly property int _barH: Math.max(3, Math.round(
                        Math.min(1, yearBarDelegate.modelData.count / dateFilterRow._maxCount) * (height - 18)
                    ))

                    Label {
                        anchors { bottom: bar.top; horizontalCenter: parent.horizontalCenter; bottomMargin: 1 }
                        text: yearBarDelegate.modelData.year.toString()
                        font.pixelSize: 8
                        rotation: -45
                        transformOrigin: Item.Center
                        opacity: yearBarDelegate._inRange ? 1.0 : 0.4
                        color: Material.foreground
                    }

                    Rectangle {
                        id: bar
                        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
                        width: 14
                        height: yearBarDelegate._barH
                        radius: 2
                        color: yearBarDelegate._inRange
                            ? dateFilterRow.accentColor
                            : Qt.rgba(dateFilterRow.accentColor.r, dateFilterRow.accentColor.g, dateFilterRow.accentColor.b, 0.25)

                        Behavior on height {
                            enabled: yearBarDelegate._ready
                            NumberAnimation { duration: 150 }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        hoverEnabled: true
                        onClicked: (mouse) => {
                            var year = yearBarDelegate.modelData.year
                            var yearStart = Math.floor(Date.UTC(year, 0, 1) / 1000)
                            var yearEnd = Math.floor(Date.UTC(year + 1, 0, 1) / 1000) - 1
                            if (dateFilterRow._activeFrom === year && dateFilterRow._activeTo === year
                                    && dateFilterRow.dateFrom !== -1) {
                                dateFilterRow.dateFilterCleared()
                            } else if (dateFilterRow.dateFrom !== -1 && (mouse.modifiers & Qt.ShiftModifier)) {
                                var from = year < dateFilterRow._activeFrom
                                    ? yearStart
                                    : Math.floor(Date.UTC(dateFilterRow._activeFrom, 0, 1) / 1000)
                                var to = year > dateFilterRow._activeTo
                                    ? yearEnd
                                    : Math.floor(Date.UTC(dateFilterRow._activeTo + 1, 0, 1) / 1000) - 1
                                dateFilterRow.dateFilterRequested(from, to)
                            } else {
                                dateFilterRow.dateFilterRequested(yearStart, yearEnd)
                            }
                        }
                        ToolTip.text: {
                            var base = yearBarDelegate.modelData.year + ": " + yearBarDelegate.modelData.count + " " + qsTr("images")
                            if (dateFilterRow.dateFrom !== -1 && !(dateFilterRow._activeFrom === yearBarDelegate.modelData.year && dateFilterRow._activeTo === yearBarDelegate.modelData.year))
                                return base + "\n" + qsTr("Shift-click to extend range")
                            return base
                        }
                        ToolTip.visible: containsMouse
                        ToolTip.delay: 400
                    }
                }
            }
        }

        Rectangle {
            visible: dateFilterRow._filterActive
            Layout.alignment: Qt.AlignTop
            implicitHeight: 22
            implicitWidth: clearDateLabel.implicitWidth + 14
            radius: 11
            color: Qt.rgba(dateFilterRow.accentColor.r, dateFilterRow.accentColor.g, dateFilterRow.accentColor.b, 0.15)

            Label {
                id: clearDateLabel
                anchors.centerIn: parent
                text: "\u2715"
                font.pixelSize: 11
                color: Material.foreground
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: dateFilterRow.dateFilterCleared()
                ToolTip.text: qsTr("Clear date filter")
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
            }
        }
    }
}
