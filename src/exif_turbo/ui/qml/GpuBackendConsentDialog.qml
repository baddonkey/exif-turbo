import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Dialog {
    id: root
    required property var appSettings
    property string backend: ""
    property var _meta: ({})

    title: qsTr("Enable GPU Acceleration")
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 480
    closePolicy: (appSettings && appSettings.gpuInstallInProgress) ? Popup.NoAutoClose : Popup.CloseOnEscape

    function openFor(backendKey) {
        root.backend = backendKey
        root._meta = appSettings ? appSettings.gpuBackendMetadata(backendKey) : ({})
        agreeCheck.checked = false
        root.open()
    }

    onClosed: {
        if (appSettings && appSettings.gpuInstallInProgress)
            appSettings.cancelGpuBackendInstall()
    }

    Connections {
        target: appSettings
        function onGpuInstallFinished(success, message) {
            if (success) root.close()
        }
    }

    ColumnLayout {
        width: parent.width
        spacing: 10

        Label {
            text: qsTr("%1 requires downloading additional components before it can be used.")
                .arg(_meta.displayName || root.backend)
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        GridLayout {
            columns: 2
            columnSpacing: 12
            rowSpacing: 4
            Layout.fillWidth: true

            Label { text: qsTr("Source:"); font.pixelSize: 12; opacity: 0.7 }
            Label { text: _meta.indexUrl || ""; font.pixelSize: 12; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }

            Label { text: qsTr("Download size:"); font.pixelSize: 12; opacity: 0.7 }
            Label { text: qsTr("~%1 MB").arg(_meta.sizeMb || 0); font.pixelSize: 12 }

            Label { text: qsTr("License:"); font.pixelSize: 12; opacity: 0.7 }
            Label {
                text: _meta.licenseName || ""
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        Label {
            visible: !!_meta.licenseUrl
            text: _meta.licenseUrl
                ? qsTr("Full license text: <a href='%1' style='color: %2;'>%1</a>")
                    .arg(_meta.licenseUrl).arg(Material.accent)
                : ""
            font.pixelSize: 11
            opacity: 0.6
            textFormat: Text.RichText
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
            onLinkActivated: (link) => controller.openUrl(link)
            HoverHandler { cursorShape: Qt.PointingHandCursor }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Material.dividerColor }

        Label {
            text: _meta.riskNote || ""
            wrapMode: Text.WordWrap
            font.pixelSize: 12
            color: Material.theme === Material.Dark ? "#ef9a9a" : "#b71c1c"
            Layout.fillWidth: true
        }

        CheckBox {
            id: agreeCheck
            text: qsTr("I have read and agree to the license terms above")
            Layout.fillWidth: true
        }

        ProgressBar {
            Layout.fillWidth: true
            visible: appSettings && appSettings.gpuInstallInProgress
            indeterminate: true
        }
        Label {
            visible: appSettings && appSettings.gpuInstallStatusText !== ""
            text: appSettings ? appSettings.gpuInstallStatusText : ""
            font.pixelSize: 11
            opacity: 0.7
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
            maximumLineCount: 3
            elide: Text.ElideRight
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 8
            Item { Layout.fillWidth: true }
            Button {
                text: qsTr("Cancel")
                enabled: !(appSettings && appSettings.gpuInstallInProgress)
                onClicked: root.close()
            }
            Button {
                text: (appSettings && appSettings.gpuInstallInProgress) ? qsTr("Installing...") : qsTr("Install")
                enabled: agreeCheck.checked && !(appSettings && appSettings.gpuInstallInProgress)
                onClicked: {
                    appSettings.recordGpuConsent(root.backend)
                    appSettings.startGpuBackendInstall(root.backend)
                }
            }
        }
    }
}
