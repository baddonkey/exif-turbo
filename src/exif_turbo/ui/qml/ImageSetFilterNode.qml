pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    objectName: depth === 0 ? "imageSetFilterRoot" : "imageSetFilterNested"

    property var value: ({ op: "and", conditions: [] })
    property int depth: 0
    signal valueEdited(var updatedValue)

    function cloneValue() {
        return JSON.parse(JSON.stringify(value))
    }

    function updateValue(updated) {
        value = updated
        valueEdited(updated)
    }

    function replaceChild(index, child) {
        var updated = cloneValue()
        updated.conditions[index] = child
        updateValue(updated)
    }

    function removeChild(index) {
        var updated = cloneValue()
        updated.conditions.splice(index, 1)
        updateValue(updated)
    }

    function addCondition() {
        var updated = cloneValue()
        updated.conditions.push({ field: "text", operator: "matches", value: "" })
        updateValue(updated)
    }

    function addGroup() {
        var updated = cloneValue()
        updated.conditions.push({ op: "and", conditions: [] })
        updateValue(updated)
    }

    implicitWidth: editorColumn.implicitWidth
    implicitHeight: editorColumn.implicitHeight

    ColumnLayout {
        id: editorColumn
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Math.min(root.depth * 14, 56)
            spacing: 6

            Label {
                text: qsTr("Group")
                font.pixelSize: 11
                opacity: 0.65
            }

            ComboBox {
                id: operatorCombo
                Layout.preferredWidth: implicitWidth
                model: [
                    { text: qsTr("All conditions"), value: "and" },
                    { text: qsTr("Any condition"), value: "or" }
                ]
                textRole: "text"
                valueRole: "value"
                implicitWidth: {
                    var widest = 0
                    for (var i = 0; i < model.length; i++)
                        widest = Math.max(widest, groupOperatorMetrics.advanceWidth(model[i].text))
                    return Math.max(130, widest + leftPadding + rightPadding
                                    + (indicator ? indicator.width : 0) + 16)
                }
                currentIndex: root.value.op === "or" ? 1 : 0
                onActivated: {
                    var updated = root.cloneValue()
                    updated.op = currentValue
                    root.updateValue(updated)
                }
            }

            FontMetrics {
                id: groupOperatorMetrics
                font: operatorCombo.font
            }

            Button {
                objectName: "addFilterConditionButton"
                text: qsTr("Add condition")
                onClicked: root.addCondition()
            }

            Button {
                objectName: "addFilterGroupButton"
                text: qsTr("Add group")
                onClicked: root.addGroup()
            }

            Item { Layout.fillWidth: true }
        }

        Repeater {
            objectName: "imageSetFilterChildRepeater"
            model: root.value.conditions || []
            delegate: RowLayout {
                id: childRow
                required property var modelData
                required property int index
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(root.depth * 14, 56)
                spacing: 6

                Loader {
                    id: childEditor
                    objectName: "imageSetFilterChildLoader"
                    Layout.fillWidth: true
                    source: childRow.modelData.op === "and" || childRow.modelData.op === "or"
                            ? Qt.resolvedUrl("ImageSetFilterNode.qml")
                            : Qt.resolvedUrl("ImageSetFilterCondition.qml")
                    onLoaded: {
                        item.value = childRow.modelData
                        if (childRow.modelData.op === "and" || childRow.modelData.op === "or")
                            item.depth = root.depth + 1
                    }
                }

                Connections {
                    target: childEditor.item
                    ignoreUnknownSignals: true
                    function onValueEdited(updated) {
                        root.replaceChild(childRow.index, updated)
                    }
                }

                Button {
                    text: qsTr("Remove")
                    onClicked: root.removeChild(childRow.index)
                }
            }
        }
    }
}