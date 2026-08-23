import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: section
    required property var appController
    required property var appSettings
    required property bool aiFeatureAvailable
    required property bool aiEnabled
    Layout.fillWidth: true
    spacing: 8

    Label { text: qsTr("Tagging and Controlled Vocabulary"); font.pixelSize: 14; font.weight: Font.DemiBold }

    Switch {
        id: taggingEnabledSwitch
        objectName: "taggingEnabledSwitch"
        text: qsTr("Enable tagging for this database")
        checked: appSettings ? appSettings.taggingEnabled : false
        onToggled: appController.setTaggingEnabled(checked)
    }

    RowLayout {
        Layout.fillWidth: true
        enabled: taggingEnabledSwitch.checked
        Label {
            Layout.fillWidth: true
            text: qsTr("Bundled Wikidata snapshot: %1 subjects, %2 genre/form terms").arg(appController.tgmSubjectCount).arg(appController.tgmGenreFormatCount)
            wrapMode: Text.WordWrap
            font.pixelSize: 12
            opacity: 0.7
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Label { text: qsTr("Snapshot date: %1").arg(appController.tgmSourceDate || qsTr("unknown")); font.pixelSize: 11; opacity: 0.55 }
        Label {
            Layout.fillWidth: true
            text: appController.tgmChecksum
            elide: Text.ElideMiddle
            horizontalAlignment: Text.AlignRight
            font.family: "Courier New"
            font.pixelSize: 10
            opacity: 0.45
            ToolTip.text: appController.tgmChecksum
            ToolTip.visible: checksumHover.hovered && truncated
            HoverHandler { id: checksumHover }
        }
    }

    Label {
        Layout.fillWidth: true
        visible: appController.tgmDiagnosticsSummary !== ""
        text: appController.tgmDiagnosticsSummary
        wrapMode: Text.WordWrap
        font.pixelSize: 11
        opacity: 0.6
    }

    ProgressBar {
        Layout.fillWidth: true
        visible: appController.isTgmUpdating
        from: 0
        to: Math.max(1, appController.tgmUpdateTotal)
        value: appController.tgmUpdateCurrent
        indeterminate: appController.tgmUpdateTotal === 0
    }

    RowLayout {
        visible: appController.isTgmUpdating
        Layout.fillWidth: true
        Label { Layout.fillWidth: true; text: qsTr("Building controlled-vocabulary vectors"); font.pixelSize: 11 }
        Button { text: qsTr("Cancel"); onClicked: appController.cancelTgmOperation() }
    }

    Label {
        Layout.fillWidth: true
        visible: appController.tgmUpdateError !== ""
        text: appController.tgmUpdateError
        color: Material.color(Material.Red)
        wrapMode: Text.WordWrap
        font.pixelSize: 11
    }

    RowLayout {
        Layout.fillWidth: true
        enabled: taggingEnabledSwitch.checked
        Label {
            Layout.fillWidth: true
            text: appController.tgmStatus === "ready" ? qsTr("Wikidata vectors are current") : qsTr("Wikidata vectors are required")
            font.pixelSize: 12
            opacity: 0.7
        }
        Button {
            objectName: "rebuildTgmVectorsButton"
            text: appController.tgmStatus === "ready" ? qsTr("Rebuild Vectors") : qsTr("Build Vectors")
            enabled: aiFeatureAvailable && aiEnabled && !appController.isTgmUpdating
            onClicked: appController.rebuildTgmVectors()
            ToolTip.text: !aiFeatureAvailable ? qsTr("AI features are unavailable on this platform")
                : !aiEnabled ? qsTr("Enable AI features first") : ""
            ToolTip.visible: hovered && !enabled
        }
    }

    GridLayout {
        columns: 3
        columnSpacing: 12
        rowSpacing: 8
        enabled: taggingEnabledSwitch.checked

        Label { text: qsTr("Proposal threshold"); font.pixelSize: 12 }
        SpinBox {
            id: proposalThresholdSpinBox
            objectName: "proposalThresholdSpinBox"
            from: 0; to: 99
            value: appSettings ? Math.round(appSettings.proposalThreshold * 100) : 24
            editable: false
            onValueModified: appSettings.setProposalThreshold(value / 100.0)
        }
        Label { text: "%"; opacity: 0.6 }

        Label { text: qsTr("Auto-accept proposals"); font.pixelSize: 12 }
        Switch {
            id: autoAcceptSwitch
            objectName: "autoAcceptSwitch"
            checked: appSettings ? appSettings.autoAcceptEnabled : false
            onToggled: appSettings.setAutoAcceptEnabled(checked)
        }
        Item { width: 1; height: 1 }

        Label { text: qsTr("Auto-accept threshold"); font.pixelSize: 12; enabled: autoAcceptSwitch.checked }
        SpinBox {
            objectName: "autoAcceptThresholdSpinBox"
            from: proposalThresholdSpinBox.value + 1
            to: 100
            value: appSettings ? Math.round(appSettings.autoAcceptThreshold * 100) : 32
            editable: false
            enabled: autoAcceptSwitch.checked
            onValueModified: appSettings.setAutoAcceptThreshold(value / 100.0)
        }
        Label { text: "%"; opacity: 0.6; enabled: autoAcceptSwitch.checked }
    }

    RowLayout {
        Layout.fillWidth: true
        enabled: taggingEnabledSwitch.checked
        Label {
            Layout.fillWidth: true
            text: qsTr("Developer diagnostics: show raw top 20 candidates")
            font.pixelSize: 12
        }
        Switch {
            objectName: "showRawTagCandidatesSwitch"
            checked: appSettings ? appSettings.showRawTagCandidates : false
            onToggled: appSettings.setShowRawTagCandidates(checked)
        }
    }

    RowLayout {
        Layout.fillWidth: true
        enabled: taggingEnabledSwitch.checked
        Label {
            text: qsTr("Metadata language (independent of interface)")
            font.pixelSize: 12
        }
        ComboBox {
            id: metadataLanguageCombo
            objectName: "metadataLanguageCombo"
            Layout.fillWidth: true
            model: appController ? appController.tgmLocalizationLocales : ["en"]
            currentIndex: {
                if (!appSettings) return 0
                var index = model.indexOf(appSettings.metadataLanguage)
                return index < 0 ? 0 : index
            }
            onActivated: appController.setMetadataLanguage(model[currentIndex])
        }
    }

    RowLayout {
        Layout.fillWidth: true
        enabled: taggingEnabledSwitch.checked
        Label { text: qsTr("Export controlled-vocabulary labels"); font.pixelSize: 12 }
        ComboBox {
            id: tagExportModeCombo
            objectName: "tagExportModeCombo"
            Layout.fillWidth: true
            model: [qsTr("Canonical English"), qsTr("Metadata language"), qsTr("Selected languages")]
            currentIndex: {
                if (!appSettings || appSettings.tagExportMode === "canonical") return 0
                return appSettings.tagExportMode === "interface" ? 1 : 2
            }
            onActivated: appSettings.setTagExportMode(["canonical", "interface", "selected"][currentIndex])
        }
    }

    Flow {
        Layout.fillWidth: true
        spacing: 8
        visible: taggingEnabledSwitch.checked && appSettings && appSettings.tagExportMode === "selected"
        Repeater {
            model: appController ? appController.tgmLocalizationLocales : ["en"]
            CheckBox {
                required property int index
                required property string modelData
                text: modelData
                checked: appSettings.tagExportLanguages.indexOf(modelData) >= 0
                onToggled: appSettings.setTagExportLanguageEnabled(modelData, checked)
            }
        }
    }
}