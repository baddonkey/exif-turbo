pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Controls.Material 2.15
import QtQuick.Layouts 1.15

Dialog {
    id: root
    objectName: "imageSetFilterDialog"

    required property var appController
    property int setId: -1
    property var initialFilter: null
    signal saved()

    modal: true
    width: Math.min(820, parent ? parent.width - 32 : 760)
    height: Math.min(620, parent ? parent.height - 32 : 560)
    title: qsTr("Set apply filter")

    function copyFilter(filter) {
        if (!filter)
            return { op: "and", conditions: [] }
        return JSON.parse(JSON.stringify(filter))
    }

    onOpened: filterRoot.value = copyFilter(initialFilter)

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        Label {
            Layout.fillWidth: true
            text: qsTr("Combine indexed-image conditions with nested All/Any groups.")
            wrapMode: Text.Wrap
            opacity: 0.7
            font.pixelSize: 12
        }

        ScrollView {
            id: filterScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.vertical.policy: ScrollBar.AsNeeded
            ScrollBar.horizontal.policy: ScrollBar.AsNeeded

            ImageSetFilterNode {
                id: filterRoot
                width: Math.max(implicitWidth, filterScroll.availableWidth - 16)
                value: ({ op: "and", conditions: [] })
            }
        }

        Label {
            Layout.fillWidth: true
            visible: text.length > 0
            text: root.appController ? root.appController.imageSetStatus : ""
            wrapMode: Text.Wrap
            color: Material.color(Material.Red)
            font.pixelSize: 11
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button {
                text: qsTr("Cancel")
                onClicked: root.reject()
            }
            Button {
                text: qsTr("Save filter")
                highlighted: true
                onClicked: {
                    if (root.appController.setImageSetFilterJson(
                                root.setId, JSON.stringify(filterRoot.value))) {
                        root.saved()
                        root.accept()
                    }
                }
            }
        }
    }
}