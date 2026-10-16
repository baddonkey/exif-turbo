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
        text: qsTr("MCP Interface")
        font.pixelSize: 14
        font.weight: Font.DemiBold
    }

    Label {
        text: qsTr("Expose the currently selected image to local MCP clients (for example AI assistants). Disabled by default. Binds to localhost unless you change the host.")
        font.pixelSize: 12
        opacity: 0.6
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        Layout.bottomMargin: 4
    }

    Switch {
        id: mcpEnabledSwitch
        objectName: "mcpEnabledSwitch"
        text: qsTr("Enable MCP server for this database")
        checked: appSettings ? appSettings.mcpEnabled : false
        onToggled: {
            if (appSettings)
                appSettings.setMcpEnabled(checked)
        }
    }

    GridLayout {
        columns: 2
        columnSpacing: 12
        rowSpacing: 8
        Layout.fillWidth: true
        enabled: appSettings ? appSettings.mcpEnabled : false

        Label {
            text: qsTr("Host")
            font.pixelSize: 13
        }
        TextField {
            id: mcpHostField
            objectName: "mcpHostField"
            text: appSettings ? appSettings.mcpHost : "127.0.0.1"
            Layout.fillWidth: true
            placeholderText: "127.0.0.1"
            onEditingFinished: {
                if (appSettings)
                    appSettings.setMcpHost(text)
            }
        }

        Label {
            text: qsTr("Port")
            font.pixelSize: 13
        }
        SpinBox {
            id: mcpPortSpin
            objectName: "mcpPortSpin"
            from: 1
            to: 65535
            editable: true
            value: appSettings ? appSettings.mcpPort : 8765
            Layout.preferredWidth: 140
            onValueModified: {
                if (appSettings)
                    appSettings.setMcpPort(value)
            }
        }
    }

    RowLayout {
        visible: appController && appController.mcpUrl !== ""
        Layout.fillWidth: true
        spacing: 8

        Label {
            text: qsTr("Endpoint: %1").arg(appController ? appController.mcpUrl : "")
            font.pixelSize: 12
            font.family: "monospace"
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
            opacity: 0.85
        }

        Button {
            id: mcpCopyUrlButton
            objectName: "mcpCopyUrlButton"
            text: qsTr("Copy")
            flat: true
            enabled: appController && appController.mcpUrl !== ""
            onClicked: {
                if (appController)
                    appController.copyTextToClipboard(appController.mcpUrl)
            }
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: qsTr("Copy MCP endpoint URL to clipboard")
        }
    }

    Label {
        visible: appController && appController.mcpStatusMessage !== ""
        text: appController ? appController.mcpStatusMessage : ""
        font.pixelSize: 12
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        color: (appController && appController.mcpRunning)
               ? (Material.theme === Material.Dark ? "#a5d6a7" : "#2e7d32")
               : (Material.theme === Material.Dark ? "#ffcc80" : "#ef6c00")
    }
}
