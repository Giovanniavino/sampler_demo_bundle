import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs

ApplicationWindow {
    id: root
    width: 800; height: 480
    visible: true
    title: "Sampler"
    color: "#0F0F12"

    readonly property color cBg:     "#0F0F12"
    readonly property color cPanel:  "#1A1A22"
    readonly property color cCard:   "#24242E"
    readonly property color cBorder: "#2E2E3A"
    readonly property color cAccent: "#3D8EF0"
    readonly property color cText:   "#E8E8F0"
    readonly property color cMuted:  "#7878A0"
    readonly property color cGreen:  "#1ABC9C"
    readonly property color cOrange: "#E67E22"
    readonly property color cRed:    "#E74C3C"

    property bool showSettings: false

    FileDialog {
        id: fileDialog
        nameFilters: ["Audio (*.mp3 *.wav *.flac *.ogg *.m4a)"]
        onAccepted: controller.loadTrack(selectedFile.toString())
    }

    // ════════════════════════════════════════════════════════════════
    // FIRST-LAUNCH DIALOG (unchanged)
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        visible: !controller.qualityModeChosen
        anchors.fill: parent
        color: "#000000CC"; z: 100

        Rectangle {
            anchors.centerIn: parent
            width: 460; height: 300; radius: 12
            color: cCard; border.color: cAccent; border.width: 1

            Column {
                anchors.fill: parent; anchors.margins: 24; spacing: 16
                Text { text: "Choose Processing Mode"; color: cText
                    font.pixelSize: 18; font.bold: true; width: parent.width
                    horizontalAlignment: Text.AlignHCenter }
                Text { text: "Saved permanently. Reset from Settings."
                    color: cMuted; font.pixelSize: 11; width: parent.width
                    horizontalAlignment: Text.AlignHCenter }

                Row {
                    spacing: 16; anchors.horizontalCenter: parent.horizontalCenter

                    Rectangle {
                        width: 180; height: 140; radius: 10
                        color: fastH.containsMouse ? "#2A2A38" : cPanel
                        border.color: fastH.containsMouse ? cAccent : cBorder
                        border.width: fastH.containsMouse ? 2 : 1
                        Column { anchors.centerIn: parent; spacing: 8
                            Text { text: "⚡"; font.pixelSize: 30
                                anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: "Fast"; color: cText
                                font.pixelSize: 16; font.bold: true
                                anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: "Faster, less polished"
                                color: cMuted; font.pixelSize: 10
                                anchors.horizontalCenter: parent.horizontalCenter }
                        }
                        MouseArea { id: fastH; anchors.fill: parent
                            hoverEnabled: true
                            onClicked: controller.setQualityMode("fast") }
                    }
                    Rectangle {
                        width: 180; height: 140; radius: 10
                        color: qualH.containsMouse ? "#2A2A38" : cPanel
                        border.color: qualH.containsMouse ? cGreen : cBorder
                        border.width: qualH.containsMouse ? 2 : 1
                        Column { anchors.centerIn: parent; spacing: 8
                            Text { text: "✦"; font.pixelSize: 30; color: cGreen
                                anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: "Quality"; color: cText
                                font.pixelSize: 16; font.bold: true
                                anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: "Slower, cleaner stems"
                                color: cMuted; font.pixelSize: 10
                                anchors.horizontalCenter: parent.horizontalCenter }
                        }
                        MouseArea { id: qualH; anchors.fill: parent
                            hoverEnabled: true
                            onClicked: controller.setQualityMode("quality") }
                    }
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════
    // TOP BAR (compact for 5")
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        id: topBar
        anchors.top: parent.top
        width: parent.width; height: 32
        color: cPanel

        RowLayout {
            anchors.fill: parent; anchors.margins: 4; spacing: 6

            Rectangle {
                width: 60; height: 24; radius: 4
                color: loadM.containsMouse ? cAccent : cCard
                Text { anchors.centerIn: parent; text: "Load"
                    color: cText; font.pixelSize: 11; font.bold: true }
                MouseArea { id: loadM; anchors.fill: parent
                    hoverEnabled: true; onClicked: fileDialog.open() }
            }
            Rectangle {
                width: 60; height: 24; radius: 4
                color: stopM.containsMouse ? cRed : cCard
                Text { anchors.centerIn: parent; text: "Stop"
                    color: cText; font.pixelSize: 11; font.bold: true }
                MouseArea { id: stopM; anchors.fill: parent
                    hoverEnabled: true; onClicked: controller.stopAll() }
            }
            Rectangle {
                width: 28; height: 24; radius: 4
                color: showSettings ? cAccent : (setM.containsMouse ? cCard : "transparent")
                border.color: cBorder
                Text { anchors.centerIn: parent; text: "⚙"
                    color: cText; font.pixelSize: 13 }
                MouseArea { id: setM; anchors.fill: parent
                    hoverEnabled: true; onClicked: showSettings = !showSettings }
            }

            // Mode badge
            Rectangle {
                width: 56; height: 24; radius: 12
                color: controller.qualityMode === "fast" ? "#1A2A1A" : "#1A1A30"
                border.color: controller.qualityMode === "fast" ? cGreen : cAccent
                Text { anchors.centerIn: parent
                    text: controller.qualityMode === "fast" ? "⚡Fast" : "✦Qual"
                    color: controller.qualityMode === "fast" ? cGreen : cAccent
                    font.pixelSize: 10; font.bold: true }
            }

            Item { Layout.fillWidth: true }

            // Track | BPM | KEY
            Text {
                text: (controller.trackName || "No track")
                    + (controller.bpm > 0 ? "  •  " + controller.bpm.toFixed(1) + " BPM" : "")
                    + (controller.trackKey ? "  •  " + controller.trackKey : "")
                color: cText; font.pixelSize: 11
            }
        }
    }

    // ════════════════════════════════════════════════════════════════
    // EDITOR STRIP (top, always visible)
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        id: editor
        anchors.top: topBar.bottom
        width: parent.width; height: 150
        color: cPanel
        visible: !showSettings

        // Header row: pad number + sample name + duration
        Row {
            id: edHeader
            anchors.top: parent.top; anchors.left: parent.left
            anchors.right: parent.right; anchors.margins: 6
            spacing: 8; height: 18

            Rectangle {
                width: 32; height: 18; radius: 4
                color: controller.currentPadIndex >= 0 ? cAccent : cBorder
                Text { anchors.centerIn: parent
                    text: controller.currentPadIndex >= 0
                        ? "P" + (controller.currentPadIndex + 1)
                        : "—"
                    color: "white"; font.pixelSize: 10; font.bold: true }
            }
            Text {
                text: controller.currentSampleName || "Tap a pad to edit"
                color: controller.currentSampleName ? cText : cMuted
                font.pixelSize: 12; font.bold: controller.currentSampleName !== ""
                anchors.verticalCenter: parent.verticalCenter
            }
            Item { width: 1; height: 1 }
            Text {
                visible: controller.currentSampleName !== ""
                text: {
                    var dur = controller.currentStemDurationSec
                    var s = controller.currentSampleStartFrac * dur
                    var e = controller.currentSampleEndFrac * dur
                    return (e - s).toFixed(2) + "s"
                }
                color: cMuted; font.pixelSize: 11
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // ─── Waveform canvas + draggable markers ───────────────────
        Rectangle {
            id: wfBg
            anchors.top: edHeader.bottom; anchors.topMargin: 4
            anchors.left: parent.left; anchors.right: parent.right
            anchors.bottom: parent.bottom; anchors.margins: 6
            color: cBg; radius: 4
            border.color: cBorder; border.width: 1
            clip: true

            // Waveform peaks
            Canvas {
                id: wfCanvas
                anchors.fill: parent

                property var peaks: controller.currentPeaks
                onPeaksChanged: requestPaint()
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()

                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    if (!peaks || peaks.length < 2) {
                        ctx.fillStyle = "#7878A0"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.fillText("Load a track, tap a pad to edit",
                            width/2, height/2)
                        return
                    }
                    var nBins = peaks.length / 2
                    var mid = height / 2
                    var halfH = height / 2 - 2
                    var colW = width / nBins
                    ctx.fillStyle = "#5A7AB8"
                    for (var i = 0; i < nBins; i++) {
                        var mn = peaks[i*2]
                        var mx = peaks[i*2+1]
                        var y1 = mid - mx * halfH
                        var y2 = mid - mn * halfH
                        var h = Math.max(1, y2 - y1)
                        ctx.fillRect(i * colW, y1, Math.max(1, colW - 0.5), h)
                    }
                    // Center line
                    ctx.fillStyle = "#2E2E3A"
                    ctx.fillRect(0, mid - 0.5, width, 1)
                }
            }

            // Region highlight (between start/end markers)
            Rectangle {
                visible: controller.currentSampleName !== ""
                x: wfBg.width * controller.currentSampleStartFrac
                width: wfBg.width * (controller.currentSampleEndFrac
                                      - controller.currentSampleStartFrac)
                y: 0; height: wfBg.height
                color: cAccent
                opacity: 0.18
            }

            // START marker
            Rectangle {
                id: startMarker
                visible: controller.currentSampleName !== ""
                width: 14; height: wfBg.height
                color: "transparent"
                property real frac: controller.currentSampleStartFrac
                x: wfBg.width * frac - width / 2
                Rectangle {
                    anchors.fill: parent
                    color: parent.parent ? cGreen : cGreen
                    opacity: startMA.drag.active ? 0.35 : 0
                }
                Rectangle {
                    x: parent.width / 2 - 1; width: 2
                    height: parent.height; color: cGreen
                }
                Rectangle {
                    anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter
                    width: 12; height: 12; radius: 2; color: cGreen
                    Text { anchors.centerIn: parent; text: "S"
                        color: "white"; font.pixelSize: 8; font.bold: true }
                }
                MouseArea {
                    id: startMA
                    anchors.fill: parent
                    drag.target: startMarker
                    drag.axis: Drag.XAxis
                    drag.minimumX: -startMarker.width / 2
                    drag.maximumX: wfBg.width - startMarker.width / 2
                    onPositionChanged: if (drag.active) {
                        var newFrac = (startMarker.x + startMarker.width/2) / wfBg.width
                        controller.setCurrentSampleRegion(newFrac,
                            controller.currentSampleEndFrac)
                    }
                }
            }

            // END marker
            Rectangle {
                id: endMarker
                visible: controller.currentSampleName !== ""
                width: 14; height: wfBg.height
                color: "transparent"
                property real frac: controller.currentSampleEndFrac
                x: wfBg.width * frac - width / 2
                Rectangle {
                    x: parent.width / 2 - 1; width: 2
                    height: parent.height; color: cOrange
                }
                Rectangle {
                    anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter
                    width: 12; height: 12; radius: 2; color: cOrange
                    Text { anchors.centerIn: parent; text: "E"
                        color: "white"; font.pixelSize: 8; font.bold: true }
                }
                MouseArea {
                    anchors.fill: parent
                    drag.target: endMarker
                    drag.axis: Drag.XAxis
                    drag.minimumX: -endMarker.width / 2
                    drag.maximumX: wfBg.width - endMarker.width / 2
                    onPositionChanged: if (drag.active) {
                        var newFrac = (endMarker.x + endMarker.width/2) / wfBg.width
                        controller.setCurrentSampleRegion(
                            controller.currentSampleStartFrac, newFrac)
                    }
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════
    // PAD GRID (bottom)
    // ════════════════════════════════════════════════════════════════
    GridView {
        id: padGrid
        anchors.top: editor.bottom
        anchors.bottom: bottomBar.top
        anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: 4
        interactive: false
        visible: !showSettings

        property int cols: Math.max(1, Math.round(Math.sqrt(controller.gridSize)))
        cellWidth: width / cols
        cellHeight: height / cols

        model: controller.padModel

        delegate: Item {
            width: padGrid.cellWidth; height: padGrid.cellHeight

            Timer { id: holdT; interval: 80; repeat: true; running: false
                onTriggered: controller.padHoldTick(model.padIndex) }

            Rectangle {
                anchors.fill: parent; anchors.margins: 3; radius: 6
                color: hasSample ? model.color : "#1C1C24"
                opacity: active ? 1.0 : (hasSample ? 0.82 : 0.4)
                border.color: active ? "#FFFFFF"
                    : (model.padIndex === controller.currentPadIndex ? cAccent : "#00000040")
                border.width: active ? 2
                    : (model.padIndex === controller.currentPadIndex ? 2 : 1)

                Text {
                    anchors.top: parent.top; anchors.left: parent.left
                    anchors.margins: 4
                    text: (model.padIndex + 1).toString().padStart(2, "0")
                    color: "#00000060"; font.pixelSize: 9; font.bold: true
                }
                Text {
                    anchors.bottom: parent.bottom; anchors.left: parent.left
                    anchors.right: parent.right; anchors.margins: 4
                    text: model.label; color: "#FFFFFF"; font.pixelSize: 9
                    font.bold: true; elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter
                }

                // Mode badge (top-right) — tap to cycle OS↔LOOP
                Rectangle {
                    id: mBadge; visible: hasSample
                    anchors.top: parent.top; anchors.right: parent.right
                    anchors.margins: 3
                    width: mT.width + 8; height: 13; radius: 6
                    color: model.mode === "loop" ? cGreen : "#00000070"
                    Text { id: mT; anchors.centerIn: parent
                        text: model.mode === "one_shot" ? "OS" : "LOOP"
                        color: "white"; font.pixelSize: 7; font.bold: true }
                    MouseArea { anchors.fill: parent
                        onPressed: function(m) {
                            controller.cyclePadMode(model.padIndex); m.accepted=true } }
                }

                MouseArea {
                    anchors.fill: parent
                    onPressed: function(mouse) {
                        if (mBadge.visible) {
                            var p = mapToItem(mBadge, mouse.x, mouse.y)
                            if (p.x>=0 && p.x<=mBadge.width &&
                                p.y>=0 && p.y<=mBadge.height) {
                                mouse.accepted = false; return } }
                        controller.triggerPad(model.padIndex)
                        holdT.start()
                    }
                    onReleased: { holdT.stop(); controller.releasePad(model.padIndex) }
                    onCanceled: { holdT.stop(); controller.releasePad(model.padIndex) }
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════
    // STATUS BAR
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        id: bottomBar
        anchors.bottom: parent.bottom
        width: parent.width; height: 22
        color: cPanel
        Text {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 6
            text: controller.status; color: cMuted; font.pixelSize: 10
        }
        Text {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            anchors.rightMargin: 6
            text: controller.latencyMs + " ms"
            color: cBorder; font.pixelSize: 9
        }
    }

    // ════════════════════════════════════════════════════════════════
    // SETTINGS OVERLAY (placeholder — keeps previous content accessible
    // via the gear icon, but for now compact and minimal so it fits)
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        anchors.fill: parent
        color: cBg
        visible: showSettings
        z: 10

        Column {
            anchors.fill: parent; anchors.margins: 16; spacing: 10
            Text { text: "Settings"; color: cText
                font.pixelSize: 18; font.bold: true }
            Text { text: "Use ⚙ again to close. Full settings panel in next update."
                color: cMuted; font.pixelSize: 11 }
            Text { text: "Mode: " + (controller.qualityMode || "?")
                color: cAccent; font.pixelSize: 13 }

            Rectangle {
                width: 180; height: 32; radius: 6
                color: cRed; opacity: rstM.containsMouse ? 1.0 : 0.8
                Text { anchors.centerIn: parent; text: "Reset Mode Choice"
                    color: "white"; font.pixelSize: 12; font.bold: true }
                MouseArea { id: rstM; anchors.fill: parent; hoverEnabled: true
                    onClicked: { controller.resetQualityMode(); showSettings = false } }
            }
        }
    }
}
