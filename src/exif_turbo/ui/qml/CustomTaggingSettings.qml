import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: root
    required property var appController
    required property var appSettings
    Layout.fillWidth: true
    spacing: 8

    Label {
        text: qsTr("Custom Tagging")
        font.pixelSize: 14
        font.weight: Font.DemiBold
    }

    Switch {
        id: taggingEnabledSwitch
        objectName: "taggingEnabledSwitch"
        text: qsTr("Enable tagging for this database")
        checked: root.appSettings ? root.appSettings.taggingEnabled : false
        onToggled: root.appController.setTaggingEnabled(checked)
    }

    Switch {
        objectName: "autoRepairDerivativeTagsSwitch"
        text: qsTr("Auto-Repair Tags for Derivatives")
        checked: root.appSettings ? root.appSettings.autoRepairDerivativeTags : true
        onToggled: {
            if (root.appSettings)
                root.appSettings.setAutoRepairDerivativeTags(checked)
        }
    }

    Switch {
        objectName: "writeDescriptionToXpCommentSwitch"
        text: qsTr("Write Description to EXIF XPComment")
        checked: root.appSettings ? root.appSettings.writeDescriptionToXpComment : true
        onToggled: {
            if (root.appSettings)
                root.appSettings.setWriteDescriptionToXpComment(checked)
        }
    }
}