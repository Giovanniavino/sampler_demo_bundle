import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs

ApplicationWindow {
    id: root
    // Sized for a typical 7" embedded touchscreen (1024x600) but works on desktop too.
    width: 1024
    height: 600
    visible: true
    title: "Sampler"
    color: "#0F0F12"

    FileDialog {
        id: fileDialog
        title: "Choose an audio track"
        nameFilters: ["Audio (*.mp3 *.wav *.flac *.ogg *.m4a)"]
        onAccepted: controller.loadTrack(selectedFile.toString())
    }

    // --- Top bar -----------------------------------------------------------
    Rectangle {
        id: topBar
        anchors.top: parent.top
        width: parent.width
        height: 60
        color: "#1A1A20"

        RowLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 12

            Button {
                text: "Load"
                onClicked: fileDialog.open()
                background: Rectangle {
                    color: parent.pressed ? "#3498DB" : "#2C3E50"
                    radius: 6
                }
                contentItem: Text {
                    text: parent.text
                    color: "white"
                    font.pixelSize: 14
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                implicitWidth: 90
                implicitHeight: 36
            }

            Button {
                text: "Stop All"
                onClicked: controller.stopAll()
                background: Rectangle {
                    color: parent.pressed ? "#E74C3C" : "#34495E"
                    radius: 6
                }
                contentItem: Text {
                    text: parent.text
                    color: "white"
                    font.pixelSize: 14
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                implicitWidth: 90
                implicitHeight: 36
            }

            Item { Layout.fillWidth: true }

            ColumnLayout {
                spacing: 0
                Text {
                    text: controller.trackName.length ? controller.trackName : "No track"
                    color: "#ECF0F1"
                    font.pixelSize: 16
                    font.bold: true
                    Layout.alignment: Qt.AlignRight
                }
                Text {
                    text: controller.bpm > 0 ? controller.bpm.toFixed(1) + " BPM" : ""
                    color: "#95A5A6"
                    font.pixelSize: 12
                    Layout.alignment: Qt.AlignRight
                }
            }
        }
    }

    // --- Pad grid (4x4) ----------------------------------------------------
    GridView {
        id: padGrid
        anchors.top: topBar.bottom
        anchors.bottom: bottomBar.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 16

        // Compute pad size to fit a square grid
        property int columns: 4
        cellWidth: width / columns
        cellHeight: height / columns

        model: controller.padModel
        interactive: false

        delegate: Item {
            width: padGrid.cellWidth
            height: padGrid.cellHeight

            Rectangle {
                id: pad
                anchors.fill: parent
                anchors.margins: 6
                radius: 10
                color: hasSample ? model.color : "#1E1E24"
                opacity: active ? 1.0 : (hasSample ? 0.85 : 0.5)
                border.color: active ? "#FFFFFF" : "#000000"
                border.width: active ? 3 : 1

                Behavior on opacity { NumberAnimation { duration: 80 } }
                Behavior on border.width { NumberAnimation { duration: 60 } }

                // Pad number (top-left)
                Text {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.margins: 8
                    text: (model.padIndex + 1).toString().padStart(2, "0")
                    color: "#000000"
                    opacity: 0.45
                    font.pixelSize: 12
                    font.bold: true
                }

                // Sample label (bottom)
                Text {
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.margins: 8
                    text: model.label
                    color: "#FFFFFF"
                    font.pixelSize: 11
                    font.bold: true
                    elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter
                }

                // Mode badge (top-right)
                Rectangle {
                    visible: hasSample
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 8
                    width: modeText.width + 10
                    height: 16
                    radius: 8
                    color: "#000000"
                    opacity: 0.4
                    Text {
                        id: modeText
                        anchors.centerIn: parent
                        text: model.mode
                        color: "white"
                        font.pixelSize: 9
                        font.bold: true
                    }
                }

                // Touch / click handling
                MouseArea {
                    anchors.fill: parent
                    onPressed: controller.triggerPad(model.padIndex)
                    onReleased: controller.releasePad(model.padIndex)
                    onCanceled: controller.releasePad(model.padIndex)
                }
            }
        }
    }

    // --- Bottom status bar -------------------------------------------------
    Rectangle {
        id: bottomBar
        anchors.bottom: parent.bottom
        width: parent.width
        height: 32
        color: "#1A1A20"

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 12
            text: controller.status
            color: "#BDC3C7"
            font.pixelSize: 12
        }
    }
}
