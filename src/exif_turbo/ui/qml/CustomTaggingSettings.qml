import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
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
        checked: appSettings ? appSettings.taggingEnabled : false
        onToggled: appController.setTaggingEnabled(checked)
    }

    Switch {
        objectName: "autoRepairDerivativeTagsSwitch"
        text: qsTr("Auto-Repair Tags for Derivatives")
        checked: appSettings ? appSettings.autoRepairDerivativeTags : true
        onToggled: {
            if (appSettings)
                appSettings.setAutoRepairDerivativeTags(checked)
        }
    }

    Switch {
        objectName: "writeDescriptionToXpCommentSwitch"
        text: qsTr("Write Description to EXIF XPComment")
        checked: appSettings ? appSettings.writeDescriptionToXpComment : true
        onToggled: {
            if (appSettings)
                appSettings.setWriteDescriptionToXpComment(checked)
        }
    }
}