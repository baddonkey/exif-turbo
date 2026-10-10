import QtQuick
import QtQuick.Window

Window {
    width: 420
    height: 260
    x: Screen.virtualX + (Screen.width - width) / 2
    y: Screen.virtualY + (Screen.height - height) / 2
    visible: true
    flags: Qt.SplashScreen | Qt.FramelessWindowHint
    color: "#f7f9fc"
    title: "Exif-Turbo"

    Column {
        anchors.centerIn: parent
        spacing: 16

        Image {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 112
            height: 112
            source: "../../assets/logo.png"
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Exif-Turbo"
            color: "#20252b"
            font.pixelSize: 26
            font.weight: Font.DemiBold
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: qsTr("Starting...")
            color: "#58616c"
            font.pixelSize: 14
        }
    }
}