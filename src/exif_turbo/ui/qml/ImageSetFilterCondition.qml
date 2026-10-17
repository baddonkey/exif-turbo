pragma ComponentBehavior: Bound

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

RowLayout {
    id: root

    property var value: ({ field: "text", operator: "matches", value: "" })
    signal valueEdited(var updatedValue)

    readonly property var fieldOptions: [
        { text: qsTr("Text"), value: "text" },
        { text: qsTr("Folder"), value: "folder" },
        { text: qsTr("File type"), value: "file_type" },
        { text: qsTr("Capture date"), value: "capture_date" },
        { text: qsTr("Marked"), value: "marked" },
        { text: qsTr("Metadata field"), value: "metadata" }
    ]

    function operatorOptions(field) {
        if (field === "text")
            return [{ text: qsTr("matches"), value: "matches" }]
        if (field === "folder")
            return [{ text: qsTr("within any"), value: "within_any" }]
        if (field === "file_type")
            return [
                { text: qsTr("is"), value: "equals" },
                { text: qsTr("is one of"), value: "one_of" }
            ]
        if (field === "capture_date")
            return [{ text: qsTr("between"), value: "between" }]
        if (field === "marked")
            return [{ text: qsTr("is"), value: "equals" }]
        return [
            { text: qsTr("equals"), value: "equals" },
            { text: qsTr("does not equal"), value: "not_equals" },
            { text: qsTr("contains"), value: "contains" },
            { text: qsTr("does not contain"), value: "not_contains" },
            { text: qsTr("exists"), value: "exists" },
            { text: qsTr("is missing"), value: "missing" },
            { text: qsTr("greater than"), value: "greater_than" },
            { text: qsTr("at least"), value: "greater_than_or_equal" },
            { text: qsTr("less than"), value: "less_than" },
            { text: qsTr("at most"), value: "less_than_or_equal" }
        ]
    }

    function cloneValue() {
        return JSON.parse(JSON.stringify(value))
    }

    function emitUpdate(updated) {
        value = updated
        valueEdited(updated)
    }

    function changeField(field) {
        var defaults = {
            text: { field: "text", operator: "matches", value: "" },
            folder: { field: "folder", operator: "within_any", value: [] },
            file_type: { field: "file_type", operator: "equals", value: "jpg" },
            capture_date: { field: "capture_date", operator: "between", value: { from: null, to: null } },
            marked: { field: "marked", operator: "equals", value: true },
            metadata: { field: "metadata", key: "Make", operator: "exists" }
        }
        emitUpdate(defaults[field])
    }

    function changeOperator(operator) {
        var updated = cloneValue()
        updated.operator = operator
        if (updated.field === "file_type" && operator === "one_of" && !Array.isArray(updated.value))
            updated.value = updated.value ? [updated.value] : []
        if (updated.field === "file_type" && operator === "equals" && Array.isArray(updated.value))
            updated.value = updated.value.length > 0 ? updated.value[0] : ""
        if (["exists", "missing"].indexOf(operator) >= 0)
            delete updated.value
        else if (updated.field === "metadata" && updated.value === undefined)
            updated.value = ""
        emitUpdate(updated)
    }

    function displayValue() {
        if (value.field === "folder")
            return (value.value || []).join("; ")
        if (value.field === "file_type" && value.operator === "one_of")
            return (value.value || []).join(", ")
        return value.value === undefined || value.value === null ? "" : String(value.value)
    }

    function updateTextValue(text) {
        var updated = cloneValue()
        if (updated.field === "folder") {
            updated.value = text.split(";").map(function (path) { return path.trim() }).filter(function (path) { return path.length > 0 })
        } else if (updated.field === "file_type" && updated.operator === "one_of") {
            updated.value = text.split(",").map(function (extension) { return extension.trim() }).filter(function (extension) { return extension.length > 0 })
        } else {
            updated.value = text
        }
        emitUpdate(updated)
    }

    function valuePlaceholder() {
        if (value.field === "folder")
            return qsTr("Folder paths separated by ;")
        if (value.field === "file_type" && value.operator === "one_of")
            return qsTr("Extensions separated by ,")
        if (value.field === "metadata")
            return qsTr("Value")
        return qsTr("Search text")
    }

    function dateText(bound) {
        var timestamp = value.value ? value.value[bound] : null
        if (timestamp === null || timestamp === undefined)
            return ""
        return new Date(timestamp * 1000).toISOString().slice(0, 10)
    }

    function updateDate(bound, text) {
        var updated = cloneValue()
        var timestamp = null
        if (text.trim().length > 0) {
            if (!/^\d{4}-\d{2}-\d{2}$/.test(text))
                return
            var parsed = Date.parse(text + "T00:00:00Z")
            if (Number.isNaN(parsed))
                return
            timestamp = Math.floor(parsed / 1000)
            if (bound === "to")
                timestamp += 86399
        }
        updated.value[bound] = timestamp
        emitUpdate(updated)
    }

    spacing: 6
    implicitHeight: 34

    ComboBox {
        id: fieldCombo
        Layout.preferredWidth: implicitWidth
        model: root.fieldOptions
        textRole: "text"
        valueRole: "value"
        implicitWidth: {
            var widest = 0
            for (var i = 0; i < root.fieldOptions.length; i++)
                widest = Math.max(widest, fieldMetrics.advanceWidth(root.fieldOptions[i].text))
            return Math.max(140, widest + leftPadding + rightPadding
                            + (indicator ? indicator.width : 0) + 16)
        }
        currentIndex: {
            for (var i = 0; i < model.length; i++) {
                if (model[i].value === root.value.field)
                    return i
            }
            return 0
        }
        onActivated: root.changeField(currentValue)
    }

    FontMetrics {
        id: fieldMetrics
        font: fieldCombo.font
    }

    ComboBox {
        id: operatorCombo
        Layout.preferredWidth: implicitWidth
        model: root.operatorOptions(root.value.field)
        textRole: "text"
        valueRole: "value"
        implicitWidth: {
            var options = root.operatorOptions(root.value.field)
            var widest = 0
            for (var i = 0; i < options.length; i++)
                widest = Math.max(widest, operatorMetrics.advanceWidth(options[i].text))
            return Math.max(155, widest + leftPadding + rightPadding
                            + (indicator ? indicator.width : 0) + 16)
        }
        currentIndex: {
            for (var i = 0; i < model.length; i++) {
                if (model[i].value === root.value.operator)
                    return i
            }
            return 0
        }
        onActivated: root.changeOperator(currentValue)
    }

    FontMetrics {
        id: operatorMetrics
        font: operatorCombo.font
    }

    TextField {
        id: metadataKey
        Layout.preferredWidth: Math.max(
            140,
            metadataKeyMetrics.advanceWidth(placeholderText)
                + leftPadding + rightPadding + 20
        )
        visible: root.value.field === "metadata"
        placeholderText: qsTr("Metadata key")
        text: root.value.key || ""
        onEditingFinished: {
            var updated = root.cloneValue()
            updated.key = text.trim()
            root.emitUpdate(updated)
        }
    }

    FontMetrics {
        id: metadataKeyMetrics
        font: metadataKey.font
    }

    TextField {
        id: textValue
        Layout.fillWidth: true
        Layout.preferredWidth: Math.max(
            160,
            valueMetrics.advanceWidth(placeholderText)
                + leftPadding + rightPadding + 20
        )
        visible: ["text", "folder", "file_type", "metadata"].indexOf(root.value.field) >= 0
                 && ["exists", "missing"].indexOf(root.value.operator) < 0
        placeholderText: root.valuePlaceholder()
        text: root.displayValue()
        onEditingFinished: root.updateTextValue(text)
    }

    FontMetrics {
        id: valueMetrics
        font: textValue.font
    }

    RowLayout {
        Layout.fillWidth: true
        visible: root.value.field === "capture_date"
        spacing: 4
        TextField {
            id: dateFromField
            Layout.fillWidth: true
            Layout.preferredWidth: Math.max(
                150,
                dateFromMetrics.advanceWidth(placeholderText)
                    + leftPadding + rightPadding + 20
            )
            placeholderText: qsTr("From YYYY-MM-DD")
            text: root.dateText("from")
            validator: RegularExpressionValidator { regularExpression: /^$|^\d{4}-\d{2}-\d{2}$/ }
            onEditingFinished: root.updateDate("from", text)
        }
        FontMetrics {
            id: dateFromMetrics
            font: dateFromField.font
        }
        TextField {
            id: dateToField
            Layout.fillWidth: true
            Layout.preferredWidth: Math.max(
                150,
                dateToMetrics.advanceWidth(placeholderText)
                    + leftPadding + rightPadding + 20
            )
            placeholderText: qsTr("To YYYY-MM-DD")
            text: root.dateText("to")
            validator: RegularExpressionValidator { regularExpression: /^$|^\d{4}-\d{2}-\d{2}$/ }
            onEditingFinished: root.updateDate("to", text)
        }
        FontMetrics {
            id: dateToMetrics
            font: dateToField.font
        }
    }

    ComboBox {
        id: markedCombo
        Layout.preferredWidth: implicitWidth
        visible: root.value.field === "marked"
        model: [
            { text: qsTr("Marked"), value: true },
            { text: qsTr("Unmarked"), value: false }
        ]
        textRole: "text"
        valueRole: "value"
        implicitWidth: {
            var widest = Math.max(
                markedMetrics.advanceWidth(model[0].text),
                markedMetrics.advanceWidth(model[1].text)
            )
            return Math.max(115, widest + leftPadding + rightPadding
                            + (indicator ? indicator.width : 0) + 16)
        }
        currentIndex: root.value.value ? 0 : 1
        onActivated: {
            var updated = root.cloneValue()
            updated.value = currentValue
            root.emitUpdate(updated)
        }
    }

    FontMetrics {
        id: markedMetrics
        font: markedCombo.font
    }
}