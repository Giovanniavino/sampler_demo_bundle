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
    readonly property color cYellow: "#F1C40F"

    property bool showSettings: false
    property bool showSampleEdit: false
    // 0=Slicing 1=PadLayout 2=Playback 3=MIDI/Analysis 4=Info
    property int  settingsTab: 0

    FileDialog {
        id: fileDialog
        nameFilters: ["Audio (*.mp3 *.wav *.flac *.ogg *.m4a)"]
        onAccepted: controller.loadTrack(selectedFile.toString())
    }

    FolderDialog {
        id: stemsFolderDialog
        title: "Choose folder for stems & samples"
        onAccepted: controller.setStemsOutputDir(selectedFolder.toString())
    }

    // ════════════════════════════════════════════════════════════════
    // FIRST-LAUNCH DIALOG
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
    // Re-usable mini button
    // ════════════════════════════════════════════════════════════════
    component MiniBtn: Rectangle {
        id: mb
        property string label: ""
        property bool   selected: false
        property color  selColor: cAccent
        signal clicked()
        implicitWidth: txt.implicitWidth + 14
        implicitHeight: 22
        radius: 4
        color: selected ? selColor : (ma.containsMouse ? cCard : "#00000000")
        border.color: selected ? selColor : cBorder
        border.width: 1
        Text { id: txt; anchors.centerIn: parent; text: mb.label
            color: cText; font.pixelSize: 10; font.bold: mb.selected }
        MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true
            onClicked: mb.clicked() }
    }

    // ════════════════════════════════════════════════════════════════
    // TOP BAR
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        id: topBar
        anchors.top: parent.top
        width: parent.width; height: 56
        color: cPanel

        Column {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 2

            // Row 1: Load, Stop, Settings, Mode, Track info, Metronome
            RowLayout {
                width: parent.width
                spacing: 6

                Rectangle {
                    width: 60; height: 24; radius: 4
                    color: loadM.containsMouse ? cAccent : cCard
                    Text { anchors.centerIn: parent; text: "Load"
                        color: cText; font.pixelSize: 11; font.bold: true }
                    MouseArea { id: loadM; anchors.fill: parent
                        hoverEnabled: true; onClicked: fileDialog.open() }
                }
                Rectangle {
                    width: 28; height: 24; radius: 4
                    color: showSettings ? cAccent
                        : (setM.containsMouse ? cCard : "transparent")
                    border.color: cBorder
                    Text { anchors.centerIn: parent; text: "⚙"
                        color: cText; font.pixelSize: 13 }
                    MouseArea { id: setM; anchors.fill: parent
                        hoverEnabled: true
                        onClicked: { showSettings = !showSettings
                            showSampleEdit = false } }
                }
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

                // Metronome blink indicator
                Rectangle {
                    visible: controller.metronomeEnabled
                        || controller.isCountIn
                        || controller.isRecording
                    width: 14; height: 14; radius: 7
                    color: controller.isDownbeat ? cYellow : cAccent
                    opacity: controller.currentBeat % 1 === 0
                        ? (beatPulse.running ? 1.0 : 0.3) : 0.3
                    SequentialAnimation on opacity {
                        id: beatPulse
                        running: false
                        NumberAnimation { from: 0.3; to: 1.0; duration: 50 }
                        NumberAnimation { from: 1.0; to: 0.3; duration: 250 }
                    }
                    Connections {
                        target: controller
                        function onBeatTick() { beatPulse.start() }
                    }
                }

                Text {
                    text: {
                        var name = controller.trackName || "No track"
                        var bpm = controller.detectedBpm > 0
                            ? controller.detectedBpm.toFixed(2) + " BPM"
                            : (controller.bpm > 0
                                ? controller.bpm.toFixed(1) + " BPM" : "")
                        var ts = controller.detectedTimeSignature
                            && controller.detectedBpm > 0
                            ? " (" + controller.detectedTimeSignature + ")" : ""
                        var key = controller.detectedKeyEnglish
                            || controller.trackKey || ""
                        return name
                            + (bpm ? "  •  " + bpm + ts : "")
                            + (key ? "  •  " + key : "")
                    }
                    color: cText; font.pixelSize: 11
                }
            }

            // Row 2: Transport (Metronome, Rec, Back, Play, Pause, Forward, Stop)
            RowLayout {
                width: parent.width
                spacing: 4

                Rectangle {
                    width: 28; height: 22; radius: 4
                    color: controller.metronomeEnabled ? cYellow : cCard
                    border.color: cBorder
                    Text { anchors.centerIn: parent; text: "♩"
                        color: controller.metronomeEnabled ? cBg : cText
                        font.pixelSize: 14; font.bold: true }
                    MouseArea { anchors.fill: parent
                        onClicked: controller.toggleMetronome() }
                }

                Rectangle {
                    width: 28; height: 22; radius: 4
                    color: controller.isRecording ? cRed
                        : (controller.isRecordArmed ? cOrange : cCard)
                    border.color: controller.isRecording ? cRed : cBorder
                    Text { anchors.centerIn: parent; text: "●"
                        color: controller.isRecording
                            || controller.isRecordArmed ? "white" : cRed
                        font.pixelSize: 13; font.bold: true }
                    MouseArea { anchors.fill: parent
                        onClicked: {
                            if (controller.isRecording) controller.stopRecord()
                            else controller.armRecord()
                        }
                    }
                }

                Rectangle {
                    width: 28; height: 22; radius: 4
                    color: backM.containsMouse ? cAccent : cCard
                    border.color: cBorder
                    Text { anchors.centerIn: parent; text: "⏮"
                        color: cText; font.pixelSize: 12 }
                    MouseArea { id: backM; anchors.fill: parent
                        hoverEnabled: true
                        onClicked: controller.seekToStart() }
                }
                Rectangle {
                    width: 28; height: 22; radius: 4
                    color: prevM.containsMouse ? cAccent : cCard
                    border.color: cBorder
                    Text { anchors.centerIn: parent; text: "⏪"
                        color: cText; font.pixelSize: 12 }
                    MouseArea { id: prevM; anchors.fill: parent
                        hoverEnabled: true
                        onClicked: controller.seekBackward() }
                }
                Rectangle {
                    width: 32; height: 22; radius: 4
                    color: controller.isPlayingSequence ? cGreen
                        : (playM.containsMouse ? cAccent : cCard)
                    border.color: cBorder
                    Text { anchors.centerIn: parent
                        text: controller.isPlayingSequence ? "⏸" : "▶"
                        color: controller.isPlayingSequence ? cBg : cText
                        font.pixelSize: 14; font.bold: true }
                    MouseArea { id: playM; anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            if (controller.isPlayingSequence)
                                controller.pauseSequence()
                            else
                                controller.playSequence()
                        }
                    }
                }
                Rectangle {
                    width: 28; height: 22; radius: 4
                    color: nextM.containsMouse ? cAccent : cCard
                    border.color: cBorder
                    Text { anchors.centerIn: parent; text: "⏩"
                        color: cText; font.pixelSize: 12 }
                    MouseArea { id: nextM; anchors.fill: parent
                        hoverEnabled: true
                        onClicked: controller.seekForward() }
                }
                Rectangle {
                    width: 28; height: 22; radius: 4
                    color: stopM.containsMouse ? cRed : cCard
                    border.color: cBorder
                    Text { anchors.centerIn: parent; text: "⏹"
                        color: cText; font.pixelSize: 12 }
                    MouseArea { id: stopM; anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            controller.stopSequence()
                            controller.stopAll()
                        }
                    }
                }

                Item { width: 8; height: 1 }

                // Recording event counter
                Rectangle {
                    visible: controller.recordedEventCount > 0
                    width: cntT.width + 16; height: 22; radius: 11
                    color: cCard
                    border.color: controller.isRecording ? cRed : cBorder
                    Text { id: cntT; anchors.centerIn: parent
                        text: "● " + controller.recordedEventCount + " events"
                        color: controller.isRecording ? cRed : cMuted
                        font.pixelSize: 9; font.bold: true }
                    MouseArea { anchors.fill: parent
                        onClicked: controller.clearSequence() }
                }

                Item { Layout.fillWidth: true }

                // Quantize indicator
                Rectangle {
                    visible: controller.quantizePercent > 0
                    width: qT.width + 14; height: 22; radius: 11
                    color: "#1A2A1A"
                    border.color: cGreen
                    Text { id: qT; anchors.centerIn: parent
                        text: "Q " + controller.quantizePercent.toFixed(0) + "%"
                        color: cGreen
                        font.pixelSize: 9; font.bold: true }
                }
            }
        }

        // Keyboard focus + shortcut handling
        Item {
            anchors.fill: parent
            focus: true
            Keys.onPressed: function(event) {
                if (event.isAutoRepeat) return
                // Transport shortcuts
                if (event.key === Qt.Key_Space) {
                    if (controller.isPlayingSequence)
                        controller.pauseSequence()
                    else
                        controller.playSequence()
                    event.accepted = true
                    return
                }
                if (event.key === Qt.Key_R && (event.modifiers & Qt.ControlModifier)) {
                    if (controller.isRecording) controller.stopRecord()
                    else controller.armRecord()
                    event.accepted = true
                    return
                }
                if (event.key === Qt.Key_M && (event.modifiers & Qt.ControlModifier)) {
                    controller.toggleMetronome()
                    event.accepted = true
                    return
                }
                // Pad shortcuts
                if (event.text && event.text.length === 1) {
                    var padIdx = controller.keyToPadIndex(event.text)
                    if (padIdx >= 0) {
                        controller.triggerPad(padIdx)
                        event.accepted = true
                    }
                }
            }
            Keys.onReleased: function(event) {
                if (event.isAutoRepeat) return
                if (event.text && event.text.length === 1) {
                    var padIdx = controller.keyToPadIndex(event.text)
                    if (padIdx >= 0) {
                        controller.releasePad(padIdx)
                        event.accepted = true
                    }
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════
    // EDITOR STRIP — waveform + zoom/snap/edit toolbar
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        id: editor
        anchors.top: topBar.bottom
        width: parent.width; height: 150
        color: cPanel
        visible: !showSettings && !showSampleEdit

        Row {
            id: edHeader
            anchors.top: parent.top; anchors.left: parent.left
            anchors.right: parent.right; anchors.margins: 6
            spacing: 6; height: 20

            Rectangle {
                width: 32; height: 18; radius: 4
                color: controller.currentPadIndex >= 0 ? cAccent : cBorder
                anchors.verticalCenter: parent.verticalCenter
                Text { anchors.centerIn: parent
                    text: controller.currentPadIndex >= 0
                        ? "P" + (controller.currentPadIndex + 1) : "—"
                    color: "white"; font.pixelSize: 10; font.bold: true }
            }
            Text {
                text: controller.currentSampleName || "Tap a pad to edit"
                color: controller.currentSampleName ? cText : cMuted
                font.pixelSize: 12; font.bold: controller.currentSampleName !== ""
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                width: 180
            }
            Text {
                visible: controller.currentSampleName !== ""
                text: controller.currentSampleDurationSec.toFixed(2) + "s"
                color: cMuted; font.pixelSize: 11
                anchors.verticalCenter: parent.verticalCenter
            }

            Item { width: 6; height: 1 }

            // Zoom controls
            MiniBtn {
                anchors.verticalCenter: parent.verticalCenter
                label: "−"; selColor: cBorder
                enabled: controller.currentSampleName !== ""
                opacity: enabled ? 1.0 : 0.4
                onClicked: {
                    var z0 = controller.zoomStart
                    var z1 = controller.zoomEnd
                    var c = (z0 + z1) / 2
                    var w = (z1 - z0)
                    var nw = Math.min(1.0, w * 2)
                    controller.setWaveformZoom(
                        Math.max(0.0, c - nw / 2),
                        Math.min(1.0, c + nw / 2))
                }
            }
            MiniBtn {
                anchors.verticalCenter: parent.verticalCenter
                label: "+"; selColor: cBorder
                enabled: controller.currentSampleName !== ""
                opacity: enabled ? 1.0 : 0.4
                onClicked: {
                    var s = controller.currentSampleStartFrac
                    var e = controller.currentSampleEndFrac
                    var pad = Math.max(0.02, (e - s) * 0.15)
                    controller.setWaveformZoom(
                        Math.max(0.0, s - pad),
                        Math.min(1.0, e + pad))
                }
            }
            MiniBtn {
                anchors.verticalCenter: parent.verticalCenter
                label: "Fit"; selColor: cBorder
                onClicked: controller.resetWaveformZoom()
            }
            MiniBtn {
                anchors.verticalCenter: parent.verticalCenter
                label: "Snap"
                selected: controller.snapToBeats
                selColor: cYellow
                onClicked: controller.setSnapToBeats(!controller.snapToBeats)
            }
            MiniBtn {
                anchors.verticalCenter: parent.verticalCenter
                label: "▶"
                selColor: cGreen
                enabled: controller.currentSampleName !== ""
                opacity: enabled ? 1.0 : 0.4
                onClicked: controller.previewCurrentSample()
            }
            // NEW: Analyze button — runs AI analysis on the current sample
            MiniBtn {
                anchors.verticalCenter: parent.verticalCenter
                label: "🎨 Analyze"
                selColor: cYellow
                enabled: controller.currentSampleName !== ""
                opacity: enabled ? 1.0 : 0.4
                onClicked: controller.analyzeSampleForAnnotations()
            }
            MiniBtn {
                anchors.verticalCenter: parent.verticalCenter
                label: "Edit ▸"; selColor: cAccent
                enabled: controller.currentSampleName !== ""
                opacity: enabled ? 1.0 : 0.4
                onClicked: showSampleEdit = true
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

            function snapFrac(f) {
                if (!controller.snapToBeats) return f
                var beats = controller.currentSampleBeats
                if (!beats || beats.length === 0) return f
                var best = f, bestD = 1.0
                for (var i = 0; i < beats.length; i++) {
                    var d = Math.abs(beats[i] - f)
                    if (d < bestD) { bestD = d; best = beats[i] }
                }
                return bestD < 0.03 ? best : f
            }

            function visToFrac(xPx) {
                var z0 = controller.zoomStart, z1 = controller.zoomEnd
                return z0 + (xPx / width) * (z1 - z0)
            }
            function fracToVis(f) {
                var z0 = controller.zoomStart, z1 = controller.zoomEnd
                var span = Math.max(0.0001, z1 - z0)
                return ((f - z0) / span) * width
            }

            Canvas {
                id: wfCanvas
                anchors.fill: parent

                property var peaks: controller.currentPeaks
                property real zStart: controller.zoomStart
                property real zEnd: controller.zoomEnd
                property var beats: controller.currentSampleBeats
                property bool snap: controller.snapToBeats
                onPeaksChanged: requestPaint()
                onZStartChanged: requestPaint()
                onZEndChanged: requestPaint()
                onBeatsChanged: requestPaint()
                onSnapChanged: requestPaint()
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
                    var startBin = Math.floor(zStart * nBins)
                    var endBin   = Math.ceil(zEnd * nBins)
                    var visBins  = Math.max(1, endBin - startBin)
                    var colW = width / visBins
                    ctx.fillStyle = "#5A7AB8"
                    for (var i = 0; i < visBins; i++) {
                        var srcIdx = startBin + i
                        if (srcIdx < 0 || srcIdx >= nBins) continue
                        var mn = peaks[srcIdx*2]
                        var mx = peaks[srcIdx*2+1]
                        var y1 = mid - mx * halfH
                        var y2 = mid - mn * halfH
                        var h = Math.max(1, y2 - y1)
                        ctx.fillRect(i * colW, y1, Math.max(1, colW - 0.5), h)
                    }
                    ctx.fillStyle = "#2E2E3A"
                    ctx.fillRect(0, mid - 0.5, width, 1)

                    if (snap && beats && beats.length > 0) {
                        ctx.fillStyle = "#F1C40F66"
                        for (var k = 0; k < beats.length; k++) {
                            var bf = beats[k]
                            if (bf < zStart || bf > zEnd) continue
                            var bx = ((bf - zStart) / (zEnd - zStart)) * width
                            ctx.fillRect(bx - 0.5, 0, 1, height)
                        }
                    }
                }
            }

            // NEW: Annotation overlay strip (top edge of waveform)
            Repeater {
                model: controller.annotationModel
                delegate: Rectangle {
                    visible: model.endFrac > controller.zoomStart
                        && model.startFrac < controller.zoomEnd
                    x: wfBg.fracToVis(Math.max(model.startFrac, controller.zoomStart))
                    width: Math.max(2,
                        wfBg.fracToVis(Math.min(model.endFrac, controller.zoomEnd))
                        - wfBg.fracToVis(Math.max(model.startFrac, controller.zoomStart)))
                    // Position CORE annotations at the bottom, others at top
                    y: model.kind === "core" ? wfBg.height - 8 : 0
                    height: 6
                    color: model.color
                    opacity: 0.85
                    radius: 2

                    // Rich tooltip on hover — shows what this annotation is
                    Rectangle {
                        visible: mouseAr.containsMouse
                        x: Math.max(0, Math.min(parent.x + parent.width/2 - width/2,
                                                 wfBg.width - width - 4))
                        y: parent.height + 6
                        width: tooltipCol.width + 12
                        height: tooltipCol.height + 8
                        color: cPanel
                        border.color: parent.color
                        border.width: 2
                        radius: 4
                        z: 99

                        Column {
                            id: tooltipCol
                            anchors.centerIn: parent
                            spacing: 2

                            // Kind badge
                            Text {
                                text: {
                                    switch(model.kind) {
                                        case "phrase": return "🔵 PHRASE"
                                        case "hit": return "🔴 HIT"
                                        case "break": return "⚫ BREAK"
                                        case "core": return "⭐ CORE"
                                        default: return model.kind.toUpperCase()
                                    }
                                }
                                color: cText
                                font.pixelSize: 10
                                font.bold: true
                            }

                            // Label (e.g., "vocal phrase 1")
                            Text {
                                text: model.label
                                color: cMuted
                                font.pixelSize: 9
                            }

                            // Explanation
                            Text {
                                text: {
                                    switch(model.kind) {
                                        case "phrase": 
                                            return "Vocal or melodic phrase\n(sustained sound)"
                                        case "hit":
                                            return "Drum or percussion hit\n(sharp attack)"
                                        case "break":
                                            return "Silence gap\n(pause between sounds)"
                                        case "core":
                                            return "Essence of the phrase\n(most important part)"
                                        default: return ""
                                    }
                                }
                                color: cMuted
                                font.pixelSize: 8
                                lineHeight: 1.2
                            }
                        }
                    }

                    MouseArea {
                        id: mouseAr
                        anchors.fill: parent
                        hoverEnabled: true
                    }
                }
            }

            // Active region highlight
            Rectangle {
                visible: controller.currentSampleName !== ""
                x: wfBg.fracToVis(controller.currentSampleStartFrac)
                width: Math.max(0,
                    wfBg.fracToVis(controller.currentSampleEndFrac)
                    - wfBg.fracToVis(controller.currentSampleStartFrac))
                y: 0; height: wfBg.height
                color: cAccent; opacity: 0.18
            }

            // NEW: Playback cursor (playhead) — moves during playback
            Rectangle {
                id: playhead
                visible: controller.isPlaying
                    && controller.playbackPositionFrac >= controller.zoomStart
                    && controller.playbackPositionFrac <= controller.zoomEnd
                x: wfBg.fracToVis(controller.playbackPositionFrac) - 1
                y: 0
                width: 2
                height: wfBg.height
                color: cYellow
                z: 50

                Rectangle {
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 10; height: 10; radius: 5
                    color: cYellow
                }
            }

            // START marker
            Rectangle {
                id: startMarker
                visible: controller.currentSampleName !== ""
                width: 14; height: wfBg.height
                color: "transparent"
                // Binding restored after drag via Binding element below
                x: wfBg.fracToVis(controller.currentSampleStartFrac) - width / 2
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
                        var px = startMarker.x + startMarker.width / 2
                        var f  = wfBg.snapFrac(wfBg.visToFrac(px))
                        // preview only — no audio re-render during drag
                        controller.setCurrentSampleRegion(
                            f, controller.currentSampleEndFrac)
                    }
                    onReleased: {
                        // commit: re-render audio with the new region
                        controller.commitCurrentSampleRegion()
                    }
                }
            }

            // END marker
            Rectangle {
                id: endMarker
                visible: controller.currentSampleName !== ""
                width: 14; height: wfBg.height
                color: "transparent"
                x: wfBg.fracToVis(controller.currentSampleEndFrac) - width / 2
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
                        var px = endMarker.x + endMarker.width / 2
                        var f  = wfBg.snapFrac(wfBg.visToFrac(px))
                        controller.setCurrentSampleRegion(
                            controller.currentSampleStartFrac, f)
                    }
                    onReleased: {
                        controller.commitCurrentSampleRegion()
                    }
                }
            }

            // Pinch-to-zoom
            PinchHandler {
                target: null
                acceptedDevices: PointerDevice.TouchScreen | PointerDevice.TouchPad
                property real _z0: 0
                property real _z1: 1
                onActiveChanged: if (active) {
                    _z0 = controller.zoomStart
                    _z1 = controller.zoomEnd
                }
                onActiveScaleChanged: if (active) {
                    var origSpan = _z1 - _z0
                    var cx = _z0 + (centroid.position.x / wfBg.width) * origSpan
                    var newSpan = Math.max(0.02,
                        Math.min(1.0, origSpan / Math.max(0.01, activeScale)))
                    var ns = cx - newSpan / 2
                    var ne = cx + newSpan / 2
                    if (ns < 0.0) { ne = Math.min(1.0, ne - ns); ns = 0.0 }
                    if (ne > 1.0) { ns = Math.max(0.0, ns - (ne - 1.0)); ne = 1.0 }
                    controller.setWaveformZoom(ns, ne)
                }
            }

            WheelHandler {
                target: null
                grabPermissions: PointerHandler.CanTakeOverFromAnything
                onWheel: function(event) {
                    var z0   = controller.zoomStart
                    var z1   = controller.zoomEnd
                    var span = z1 - z0
                    if (event.modifiers & Qt.ControlModifier) {
                        var cx = z0 + (event.x / wfBg.width) * span
                        var factor = event.angleDelta.y > 0 ? 0.75 : 1.33
                        var ns = cx - (cx - z0) * factor
                        var ne = cx + (z1 - cx) * factor
                        if (ns < 0.0) { ne = Math.min(1.0, ne - ns); ns = 0.0 }
                        if (ne > 1.0) { ns = Math.max(0.0, ns - (ne - 1.0)); ne = 1.0 }
                        if (ne - ns >= 0.02) controller.setWaveformZoom(ns, ne)
                    } else {
                        var ang = event.angleDelta.x !== 0
                            ? event.angleDelta.x : -event.angleDelta.y
                        var dFrac = (ang / 1200.0) * span * 3
                        var ns2 = Math.max(0.0, Math.min(1.0 - span, z0 + dFrac))
                        controller.setWaveformZoom(ns2, ns2 + span)
                    }
                    event.accepted = true
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════
    // PAD GRID
    // ════════════════════════════════════════════════════════════════
    Item {
        id: padArea
        anchors.top: editor.bottom
        anchors.bottom: bottomBar.top
        anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: 4
        visible: !showSettings && !showSampleEdit

        property int cols: controller.gridSize <= 16 ? 4
                            : (controller.gridSize <= 25 ? 5 : 6)
        property int rowsNeeded: Math.ceil(controller.gridSize / cols)
        property real cellW: width / cols
        property real cellH: {
            var idealH = height / rowsNeeded
            var maxH = cellW
            var minH = 60
            return Math.max(minH, Math.min(idealH, maxH))
        }

        GridView {
            id: padGrid
            anchors.fill: parent
            cellWidth: padArea.cellW
            cellHeight: padArea.cellH
            interactive: contentHeight > height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {
                policy: padGrid.interactive
                    ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                width: 6
            }

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
                        : (model.padIndex === controller.currentPadIndex
                            ? cAccent : "#00000040")
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
                                controller.cyclePadMode(model.padIndex)
                                m.accepted = true } }
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
    // SAMPLE EDIT OVERLAY — scrollable + per-param resets
    // ════════════════════════════════════════════════════════════════

    // Reusable parameter row: slider + value display + reset button
    component ParamRow: Column {
        property string title: ""
        property real value: 0
        property real fromVal: 0
        property real toVal: 1
        property real stepVal: 0.01
        property string valueText: ""
        property color valueColor: cMuted
        property bool applyOnRelease: false  // true for expensive ops (pitch/time)
        property real defaultValue: 0
        signal applyValue(real v)
        signal resetClicked()

        Layout.fillWidth: true
        spacing: 4

        Item {
            width: parent.width
            height: 18
            Text {
                id: titleLabel
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: title; color: cText
                font.pixelSize: 12; font.bold: true
            }
            MiniBtn {
                id: resetBtn
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                label: "↺"
                selColor: cOrange
                onClicked: resetClicked()
            }
            Text {
                anchors.right: resetBtn.left
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                text: valueText
                color: valueColor; font.pixelSize: 11
            }
        }
        Slider {
            id: paramSlider
            width: parent.width
            from: parent.fromVal
            to: parent.toVal
            stepSize: parent.stepVal
            value: parent.value
            onMoved: if (!parent.applyOnRelease) parent.applyValue(value)
            onPressedChanged: if (parent.applyOnRelease && !pressed)
                parent.applyValue(value)
        }
    }

    Rectangle {
        anchors.fill: parent
        color: cBg; visible: showSampleEdit; z: 9

        // Header (sticky)
        Item {
            id: editHeader
            anchors.top: parent.top
            anchors.left: parent.left; anchors.right: parent.right
            anchors.margins: 12
            height: 32

            Row {
                id: editHeaderLeft
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                Text { text: "Sample Editor"; color: cText
                    font.pixelSize: 16; font.bold: true
                    anchors.verticalCenter: parent.verticalCenter }
                Rectangle {
                    width: 32; height: 18; radius: 4
                    color: cAccent
                    anchors.verticalCenter: parent.verticalCenter
                    Text { anchors.centerIn: parent
                        text: controller.currentPadIndex >= 0
                            ? "P" + (controller.currentPadIndex + 1) : "—"
                        color: "white"; font.pixelSize: 10; font.bold: true }
                }
                Text { text: controller.currentSampleName
                    color: cText; font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight; width: 200 }
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                MiniBtn {
                    label: "▶"; selColor: cGreen
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: controller.previewCurrentSample()
                }
                MiniBtn {
                    label: "⏹ Stop"; selColor: cRed
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: if (controller.currentPadIndex >= 0)
                        controller.stopPad(controller.currentPadIndex)
                }
                MiniBtn {
                    label: "Reset All"; selColor: cOrange
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: controller.resetCurrentSample()
                }
                MiniBtn {
                    label: "Close ✕"; selColor: cBorder
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: showSampleEdit = false
                }
            }
        }

        Rectangle {
            anchors.top: editHeader.bottom
            anchors.left: parent.left; anchors.right: parent.right
            anchors.leftMargin: 12; anchors.rightMargin: 12
            height: 1; color: cBorder
        }

        // Scrollable content
        Flickable {
            anchors.top: editHeader.bottom; anchors.topMargin: 8
            anchors.left: parent.left; anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 12; anchors.rightMargin: 12
            anchors.bottomMargin: 12
            clip: true
            contentWidth: width
            contentHeight: paramsCol.height
            ScrollBar.vertical: ScrollBar { width: 6 }

            Column {
                id: paramsCol
                width: parent.width
                spacing: 10

                GridLayout {
                    width: parent.width
                    columns: 2
                    columnSpacing: 24
                    rowSpacing: 10

                    ParamRow {
                        title: "Gain"
                        fromVal: -24; toVal: 12; stepVal: 0.1
                        value: controller.currentSampleGainDb
                        valueText: controller.currentSampleGainDb.toFixed(1) + " dB"
                        defaultValue: 0
                        onApplyValue: controller.setCurrentSampleGain(v)
                        onResetClicked: controller.setCurrentSampleGain(0)
                    }
                    ParamRow {
                        title: "Pitch"
                        fromVal: -12; toVal: 12; stepVal: 0.5
                        value: controller.currentSamplePitchSemitones
                        valueText: (controller.currentSamplePitchSemitones >= 0 ? "+" : "")
                            + controller.currentSamplePitchSemitones.toFixed(1) + " st"
                        applyOnRelease: true  // expensive: only on release
                        defaultValue: 0
                        onApplyValue: controller.setCurrentSamplePitch(v)
                        onResetClicked: controller.setCurrentSamplePitch(0)
                    }
                    ParamRow {
                        title: "Time Stretch"
                        fromVal: 0.5; toVal: 2.0; stepVal: 0.01
                        value: controller.currentSampleTimeStretch
                        valueText: controller.currentSampleTimeStretch.toFixed(2) + "×"
                        applyOnRelease: true  // expensive: only on release
                        defaultValue: 1.0
                        onApplyValue: controller.setCurrentSampleTimeStretch(v)
                        onResetClicked: controller.setCurrentSampleTimeStretch(1.0)
                    }
                    Column {
                        Layout.fillWidth: true; spacing: 4
                        Item {
                            width: parent.width; height: 18
                            Text { text: "Reverse"; color: cText
                                font.pixelSize: 12; font.bold: true
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                text: controller.currentSampleReverse ? "ON" : "OFF"
                                color: controller.currentSampleReverse ? cGreen : cMuted
                                font.pixelSize: 11; font.bold: true
                            }
                        }
                        Switch {
                            checked: controller.currentSampleReverse
                            onToggled: controller.setCurrentSampleReverse(checked)
                        }
                    }
                    ParamRow {
                        title: "Fade In"
                        fromVal: 0; toVal: 500; stepVal: 1
                        value: controller.currentSampleFadeInMs
                        valueText: controller.currentSampleFadeInMs.toFixed(0) + " ms"
                        defaultValue: 0
                        onApplyValue: controller.setCurrentSampleFadeInMs(v)
                        onResetClicked: controller.setCurrentSampleFadeInMs(0)
                    }
                    ParamRow {
                        title: "Fade Out"
                        fromVal: 0; toVal: 500; stepVal: 1
                        value: controller.currentSampleFadeOutMs
                        valueText: controller.currentSampleFadeOutMs.toFixed(0) + " ms"
                        defaultValue: 0
                        onApplyValue: controller.setCurrentSampleFadeOutMs(v)
                        onResetClicked: controller.setCurrentSampleFadeOutMs(0)
                    }
                    // Cutoff — logarithmic mapping
                    Column {
                        Layout.fillWidth: true; spacing: 4
                        Item {
                            width: parent.width; height: 18
                            Text { text: "Cutoff (LowPass)"; color: cText
                                font.pixelSize: 12; font.bold: true
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter }
                            MiniBtn {
                                id: cutResetBtn
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                label: "↺"
                                selColor: cOrange
                                onClicked: controller.setCurrentSampleCutoff(20000)
                            }
                            Text {
                                anchors.right: cutResetBtn.left
                                anchors.rightMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                text: controller.currentSampleCutoffHz >= 19999
                                    ? "OFF"
                                    : controller.currentSampleCutoffHz < 1000
                                        ? controller.currentSampleCutoffHz.toFixed(0) + " Hz"
                                        : (controller.currentSampleCutoffHz / 1000).toFixed(1) + " kHz"
                                color: controller.currentSampleCutoffHz >= 19999
                                    ? cMuted : cAccent
                                font.pixelSize: 11
                                font.bold: controller.currentSampleCutoffHz < 19999
                            }
                        }
                        Slider {
                            width: parent.width
                            from: 0; to: 100; stepSize: 0.5
                            value: {
                                var hz = controller.currentSampleCutoffHz
                                var log20 = Math.log(20)
                                var log20000 = Math.log(20000)
                                return ((Math.log(Math.max(20, hz)) - log20)
                                    / (log20000 - log20)) * 100
                            }
                            onMoved: {
                                var log20 = Math.log(20)
                                var log20000 = Math.log(20000)
                                var hz = Math.exp(log20 + (value / 100) * (log20000 - log20))
                                controller.setCurrentSampleCutoff(hz)
                            }
                        }
                    }
                    ParamRow {
                        title: "Pan"
                        fromVal: -1.0; toVal: 1.0; stepVal: 0.01
                        value: controller.currentSamplePan
                        valueText: {
                            var p = controller.currentSamplePan
                            if (Math.abs(p) < 0.01) return "C"
                            return (p < 0 ? "L " : "R ")
                                + Math.abs(p * 100).toFixed(0)
                        }
                        defaultValue: 0
                        onApplyValue: controller.setCurrentSamplePan(v)
                        onResetClicked: controller.setCurrentSamplePan(0)
                    }
                }

                Rectangle { width: parent.width; height: 1; color: cBorder }

                // Loop Sync to BPM grid
                Column {
                    width: parent.width
                    spacing: 4

                    Item {
                        width: parent.width; height: 16
                        Row {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6
                            Text { text: "Loop Sync to BPM"; color: cText
                                font.pixelSize: 12; font.bold: true
                                anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                text: controller.currentSampleEffectiveBpm > 0
                                    ? "@ " + controller.currentSampleEffectiveBpm.toFixed(1) + " BPM"
                                    : "(BPM unknown)"
                                color: controller.currentSampleEffectiveBpm > 0
                                    ? cMuted : cOrange
                                font.pixelSize: 10
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: controller.currentSampleLoopBeats > 0
                                ? "🔒 " + controller.currentSampleLoopBeats + " beats"
                                : "Free-running"
                            color: controller.currentSampleLoopBeats > 0
                                ? cGreen : cMuted
                            font.pixelSize: 10; font.bold: true
                        }
                    }

                    Row { spacing: 4; width: parent.width
                        Repeater {
                            model: [
                                { label: "OFF", val: 0 },
                                { label: "1", val: 1 },
                                { label: "2", val: 2 },
                                { label: "4", val: 4 },
                                { label: "8", val: 8 },
                                { label: "16", val: 16 },
                                { label: "32", val: 32 }
                            ]
                            delegate: MiniBtn {
                                label: modelData.label
                                selected: controller.currentSampleLoopBeats === modelData.val
                                selColor: modelData.val === 0 ? cBorder : cGreen
                                onClicked: controller.setCurrentSampleLoopBeats(modelData.val)
                            }
                        }
                        Item { width: 8; height: 1 }
                        MiniBtn {
                            label: "🎯 Auto"
                            selColor: cAccent
                            enabled: controller.currentSampleEffectiveBpm > 0
                            opacity: enabled ? 1.0 : 0.4
                            onClicked: controller.autoSyncCurrentSampleLoop()
                        }
                    }

                    Text {
                        text: "Useful only for continuous loops (LOOP mode). "
                            + "Keeps the wrap point musically accurate over long playback. "
                            + "If you don't loop, leave OFF."
                        color: cMuted; font.pixelSize: 9
                        wrapMode: Text.WordWrap; width: parent.width
                    }
                }

                Text {
                    width: parent.width
                    text: "Tip: Tap '↺' next to a parameter to reset just that one. "
                        + "'Reset All' restores everything (including start/end region)."
                    color: cMuted; font.pixelSize: 9
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════
    // SETTINGS OVERLAY — 5 tabs
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        anchors.fill: parent
        color: cBg; visible: showSettings; z: 10

        Row {
            id: tabBar
            anchors.top: parent.top
            anchors.left: parent.left; anchors.right: parent.right
            anchors.margins: 8
            height: 28; spacing: 4

            Repeater {
                model: ["Slicing", "Pad Layout", "Playback", "MIDI/AI", "Info"]
                delegate: Rectangle {
                    width: 95; height: 28; radius: 6
                    color: settingsTab === index ? cAccent : cCard
                    border.color: settingsTab === index ? cAccent : cBorder
                    Text { anchors.centerIn: parent
                        text: modelData; color: cText
                        font.pixelSize: 11
                        font.bold: settingsTab === index }
                    MouseArea { anchors.fill: parent
                        onClicked: settingsTab = index }
                }
            }
            Item { width: 8; height: 1 }
            Rectangle {
                width: 32; height: 28; radius: 6
                color: closeM.containsMouse ? cRed : cCard
                border.color: cBorder
                Text { anchors.centerIn: parent; text: "✕"
                    color: cText; font.pixelSize: 13 }
                MouseArea { id: closeM; anchors.fill: parent
                    hoverEnabled: true
                    onClicked: showSettings = false }
            }
        }

        Flickable {
            anchors.top: tabBar.bottom; anchors.topMargin: 6
            anchors.left: parent.left; anchors.right: parent.right
            anchors.bottom: parent.bottom; anchors.margins: 8
            clip: true
            contentWidth: width
            contentHeight: tabContent.height
            ScrollBar.vertical: ScrollBar { width: 6 }

            Column {
                id: tabContent
                width: parent.width
                spacing: 10

                // ──── TAB 0: SLICING ────
                Column {
                    visible: settingsTab === 0
                    width: parent.width; spacing: 12

                    Column { width: parent.width; spacing: 4
                        Text { text: "Vocal Phrases"; color: cText
                            font.pixelSize: 13; font.bold: true }
                        Text { text: "How long the vocal phrases extracted from "
                            + "the vocal stem should be."
                            color: cMuted; font.pixelSize: 10
                            wrapMode: Text.WordWrap; width: parent.width }
                        Row { spacing: 4
                            Repeater { model: ["Short", "Medium", "Long", "Custom"]
                                delegate: MiniBtn {
                                    label: modelData
                                    selected: controller.vocalPreset === modelData
                                    onClicked: controller.applyVocalPreset(modelData) }
                            }
                        }
                        GridLayout {
                            visible: controller.vocalPreset === "Custom"
                            width: parent.width
                            columns: 3; rowSpacing: 4; columnSpacing: 6
                            Text { text: "min ms"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "max ms"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "gap ms"; color: cMuted; font.pixelSize: 10 }
                            SpinBox { id: vMin
                                from: 200; to: 30000; stepSize: 100
                                value: controller.minVocalPhraseMs }
                            SpinBox { id: vMax
                                from: 500; to: 30000; stepSize: 100
                                value: controller.maxVocalPhraseMs }
                            SpinBox { id: vGap
                                from: 0; to: 5000; stepSize: 100
                                value: controller.vocalPhraseMinGapMs }
                            Text { text: "max phrases"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "chop ms"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "max chops"; color: cMuted; font.pixelSize: 10 }
                            SpinBox { id: vMaxP
                                from: 1; to: 24; value: controller.maxVocalPhrases }
                            SpinBox { id: vChop
                                from: 100; to: 5000; stepSize: 100
                                value: controller.vocalChopLengthMs }
                            SpinBox { id: vMaxC
                                from: 1; to: 24; value: controller.maxVocalChops }
                            MiniBtn {
                                Layout.columnSpan: 3
                                label: "Apply Custom"
                                selected: true
                                onClicked: controller.applyVocalCustom(
                                    vMin.value, vMax.value, vGap.value,
                                    vMaxP.value, vChop.value, vMaxC.value)
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    Column { width: parent.width; spacing: 4
                        Text { text: "Drum Hits"; color: cText
                            font.pixelSize: 13; font.bold: true }
                        Text { text: "How long each drum hit slice is and how "
                            + "many to extract."
                            color: cMuted; font.pixelSize: 10
                            wrapMode: Text.WordWrap; width: parent.width }
                        Row { spacing: 4
                            Repeater { model: ["Punchy", "Standard", "Full", "Custom"]
                                delegate: MiniBtn {
                                    label: modelData
                                    selected: controller.drumPreset === modelData
                                    onClicked: controller.applyDrumPreset(modelData) }
                            }
                        }
                        GridLayout {
                            visible: controller.drumPreset === "Custom"
                            width: parent.width
                            columns: 3; rowSpacing: 4; columnSpacing: 6
                            Text { text: "hit ms"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "max hits"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "spacing beats"; color: cMuted; font.pixelSize: 10 }
                            SpinBox { id: dHit
                                from: 50; to: 2000; stepSize: 50
                                value: controller.drumHitLengthMs }
                            SpinBox { id: dMax
                                from: 1; to: 32; value: controller.maxDrumHits }
                            SpinBox { id: dSpc
                                from: 0; to: 16
                                value: Math.round(controller.drumHitMinSpacingBeats * 4)
                                textFromValue: function(v) { return (v/4).toFixed(2) }
                            }
                            MiniBtn {
                                Layout.columnSpan: 3
                                label: "Apply Custom"; selected: true
                                onClicked: controller.applyDrumCustom(
                                    dHit.value, dMax.value, dSpc.value / 4.0)
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    Column { width: parent.width; spacing: 4
                        Text { text: "Loops"; color: cText
                            font.pixelSize: 13; font.bold: true }
                        Text { text: "How long the drum/bass/melody loops are, in bars."
                            color: cMuted; font.pixelSize: 10
                            wrapMode: Text.WordWrap; width: parent.width }
                        Row { spacing: 4
                            Repeater { model: ["Tight", "Standard", "Spacious", "Custom"]
                                delegate: MiniBtn {
                                    label: modelData
                                    selected: controller.loopPreset === modelData
                                    onClicked: controller.applyLoopPreset(modelData) }
                            }
                        }
                        GridLayout {
                            visible: controller.loopPreset === "Custom"
                            width: parent.width
                            columns: 4; rowSpacing: 4; columnSpacing: 6
                            Text { text: "n loops"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "drum bars"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "bass bars"; color: cMuted; font.pixelSize: 10 }
                            Text { text: "melody bars"; color: cMuted; font.pixelSize: 10 }
                            SpinBox { id: lN; from: 1; to: 12
                                value: controller.nLoopsPerStem }
                            SpinBox { id: lD; from: 1; to: 16
                                value: controller.drumLoopBars }
                            SpinBox { id: lB; from: 1; to: 16
                                value: controller.bassLoopBars }
                            SpinBox { id: lM; from: 1; to: 32
                                value: controller.melodyPhraseBars }
                            MiniBtn {
                                Layout.columnSpan: 4
                                label: "Apply Custom"; selected: true
                                onClicked: controller.applyLoopCustom(
                                    lN.value, lD.value, lB.value, lM.value)
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    MiniBtn {
                        label: "Reslice Now"
                        selected: true; selColor: cGreen
                        onClicked: controller.reslice()
                    }
                }

                // ──── TAB 1: PAD LAYOUT ────
                Column {
                    visible: settingsTab === 1
                    width: parent.width; spacing: 10

                    Text { text: "Pad Layout"; color: cText
                        font.pixelSize: 13; font.bold: true }
                    Text { text: "How many pads of each category to assign. "
                        + "Total must equal Grid Size."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width }

                    GridLayout {
                        width: parent.width
                        columns: 2; rowSpacing: 6; columnSpacing: 12

                        Text { text: "Drum hits"; color: cText; font.pixelSize: 11 }
                        SpinBox { id: pDH; from: 0; to: 32
                            value: controller.padsDrumHit }

                        Text { text: "Drum loops"; color: cText; font.pixelSize: 11 }
                        SpinBox { id: pDL; from: 0; to: 32
                            value: controller.padsDrumLoop }

                        Text { text: "Vocal chops"; color: cText; font.pixelSize: 11 }
                        SpinBox { id: pVC; from: 0; to: 32
                            value: controller.padsVocalChop }

                        Text { text: "Vocal phrases"; color: cText; font.pixelSize: 11 }
                        SpinBox { id: pVP; from: 0; to: 32
                            value: controller.padsVocalPhrase }

                        Text { text: "Melodic phrases"; color: cText; font.pixelSize: 11 }
                        SpinBox { id: pMel; from: 0; to: 32
                            value: controller.padsMelody }

                        Text { text: "Bass loops"; color: cText; font.pixelSize: 11 }
                        SpinBox { id: pBL; from: 0; to: 32
                            value: controller.padsBassLoop }

                        Text { text: "Grid size"; color: cText
                            font.pixelSize: 11; font.bold: true }
                        SpinBox { id: pGS; from: 4; to: 36
                            value: controller.gridSize }
                    }

                    Text {
                        property int sum: pDH.value + pDL.value + pVC.value
                            + pVP.value + pMel.value + pBL.value
                        text: "Sum: " + sum
                            + (sum === pGS.value
                                ? " ✓"
                                : "  (≠ Grid Size " + pGS.value + ")")
                        color: sum === pGS.value ? cGreen : cOrange
                        font.pixelSize: 11
                    }

                    MiniBtn {
                        label: "Apply Layout"
                        selected: true; selColor: cGreen
                        onClicked: controller.applyPadLayout(
                            pDH.value, pDL.value, pVC.value, pVP.value,
                            pMel.value, pBL.value, pGS.value)
                    }
                }

                // ──── TAB 2: PLAYBACK ────
                Column {
                    visible: settingsTab === 2
                    width: parent.width; spacing: 10

                    // NEW: Stems & Samples Output Folder
                    Text { text: "Output Folder (Stems & Samples)"; color: cText
                        font.pixelSize: 13; font.bold: true }
                    Text {
                        text: "Where separated stems are saved for each track. "
                            + "Folder names use the track name, not random IDs."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    Row { spacing: 8; width: parent.width
                        Rectangle {
                            width: parent.width - 200
                            height: 28; radius: 4
                            color: cCard
                            border.color: cBorder
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                anchors.fill: parent
                                anchors.margins: 8
                                verticalAlignment: Text.AlignVCenter
                                text: "📁 " + controller.stemsOutputDirDisplay
                                color: controller.stemsOutputDir === ""
                                    ? cMuted : cText
                                font.pixelSize: 10
                                elide: Text.ElideMiddle
                                font.italic: controller.stemsOutputDir === ""
                            }
                        }
                        MiniBtn {
                            label: "📂 Browse..."
                            selected: true; selColor: cAccent
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: stemsFolderDialog.open()
                        }
                        MiniBtn {
                            label: "↺ Reset"
                            selColor: cOrange
                            enabled: controller.stemsOutputDir !== ""
                            opacity: enabled ? 1.0 : 0.4
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: controller.setStemsOutputDir("")
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    // NEW: Audio Output Device Selection
                    Text { text: "Audio Output"; color: cText
                        font.pixelSize: 13; font.bold: true }
                    Text {
                        text: "Choose where to send audio: speakers, headphones, "
                            + "or external interface. Changing this restarts the engine."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    Row { spacing: 8; width: parent.width
                        Text { text: "Current:"; color: cMuted
                            font.pixelSize: 11
                            anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            text: controller.currentOutputDevice
                            color: cAccent; font.pixelSize: 12; font.bold: true
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            width: parent.width - 280
                        }
                        MiniBtn {
                            label: "🔍 Refresh List"
                            selected: true; selColor: cAccent
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: controller.refreshOutputDevices()
                        }
                    }

                    // Device list (visible after refresh)
                    Rectangle {
                        width: parent.width
                        height: Math.min(120, devList.contentHeight + 8)
                        color: cCard; radius: 6
                        border.color: cBorder; border.width: 1
                        visible: devList.count > 0

                        ListView {
                            id: devList
                            anchors.fill: parent; anchors.margins: 4
                            model: controller.outputDevices
                            clip: true
                            spacing: 2

                            delegate: Rectangle {
                                width: devList.width; height: 28; radius: 4
                                property bool isCurrent: modelData.name === controller.currentOutputDevice
                                color: isCurrent ? cAccent
                                    : (devMA.containsMouse ? cPanel : "transparent")
                                Row {
                                    anchors.fill: parent; anchors.margins: 6
                                    spacing: 8
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: isCurrent ? "●" : "○"
                                        color: isCurrent ? "white" : cMuted
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modelData.name
                                        color: isCurrent ? "white" : cText
                                        font.pixelSize: 11
                                        font.bold: isCurrent
                                        elide: Text.ElideRight
                                        width: devList.width - 200
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modelData.channels + "ch · "
                                            + modelData.default_samplerate.toFixed(0) + " Hz"
                                            + (modelData.is_default ? " · system default" : "")
                                        color: isCurrent ? "#FFFFFFAA" : cMuted
                                        font.pixelSize: 9
                                    }
                                }
                                MouseArea {
                                    id: devMA
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    onClicked: controller.setOutputDevice(modelData.name)
                                }
                            }
                        }
                    }

                    Text {
                        visible: devList.count === 0
                        text: "Tap '🔍 Refresh List' to scan available devices."
                        color: cMuted; font.pixelSize: 10; font.italic: true
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    Text { text: "Audio Engine"; color: cText
                        font.pixelSize: 13; font.bold: true }

                    Row { spacing: 12
                        Column { spacing: 4
                            Text { text: "Sample rate"; color: cMuted
                                font.pixelSize: 10 }
                            ComboBox { id: cbSR
                                width: 120
                                model: [22050, 44100, 48000, 96000]
                                currentIndex: model.indexOf(controller.sampleRate)
                            }
                        }
                        Column { spacing: 4
                            Text { text: "Block size"; color: cMuted
                                font.pixelSize: 10 }
                            ComboBox { id: cbBS
                                width: 120
                                model: [128, 256, 512, 1024, 2048]
                                currentIndex: model.indexOf(controller.blockSize)
                            }
                        }
                        Column { spacing: 4
                            Text { text: "Latency"; color: cMuted
                                font.pixelSize: 10 }
                            Text { text: controller.latencyMs + " ms"
                                color: cAccent; font.pixelSize: 14; font.bold: true }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    Text { text: "Behaviour"; color: cText
                        font.pixelSize: 13; font.bold: true }

                    Row { spacing: 6
                        Switch { id: swPH; checked: controller.pressHoldLoop }
                        Column { spacing: 0
                            anchors.verticalCenter: parent.verticalCenter
                            Text { text: "Press-hold loop"; color: cText
                                font.pixelSize: 11; font.bold: true }
                            Text { text: "Re-trigger sample when held after end."
                                color: cMuted; font.pixelSize: 9 }
                        }
                    }
                    Row { spacing: 6
                        Switch { id: swAN; checked: controller.autoNormalizeStems }
                        Column { spacing: 0
                            anchors.verticalCenter: parent.verticalCenter
                            Text { text: "Auto-normalize stems"; color: cText
                                font.pixelSize: 11; font.bold: true }
                            Text { text: "Bring each stem to −3 dBFS peak."
                                color: cMuted; font.pixelSize: 9 }
                        }
                    }
                    Row { spacing: 6
                        Switch { id: swAC; checked: controller.autoChokeDrums }
                        Column { spacing: 0
                            anchors.verticalCenter: parent.verticalCenter
                            Text { text: "Auto-choke drums"; color: cText
                                font.pixelSize: 11; font.bold: true }
                            Text { text: "New drum hit cuts the previous one."
                                color: cMuted; font.pixelSize: 9 }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    Text { text: "Noise Reduction"; color: cText
                        font.pixelSize: 13; font.bold: true }
                    Text {
                        text: "Stronger NR sounds darker. Default light/off is safe."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    Row { spacing: 12
                        Column { spacing: 4
                            Text { text: "Pre-separation"; color: cMuted
                                font.pixelSize: 10 }
                            ComboBox { id: cbNRPre
                                width: 110
                                model: ["off", "light", "strong"]
                                currentIndex: model.indexOf(controller.nrLevelPre)
                            }
                        }
                        Column { spacing: 4
                            Text { text: "Post-stem"; color: cMuted
                                font.pixelSize: 10 }
                            ComboBox { id: cbNRPost
                                width: 110
                                model: ["off", "light", "strong"]
                                currentIndex: model.indexOf(controller.nrLevelPost)
                            }
                        }
                    }

                    MiniBtn {
                        label: "Apply Playback Settings"
                        selected: true; selColor: cGreen
                        onClicked: controller.applyPlaybackSettings(
                            cbBS.currentValue !== undefined
                                ? cbBS.currentValue
                                : cbBS.model[cbBS.currentIndex],
                            cbSR.currentValue !== undefined
                                ? cbSR.currentValue
                                : cbSR.model[cbSR.currentIndex],
                            swPH.checked, swAN.checked, swAC.checked,
                            cbNRPre.currentText, cbNRPost.currentText)
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    // NEW: Global pitch
                    Text { text: "Global Pitch"; color: cText
                        font.pixelSize: 13; font.bold: true }
                    Text {
                        text: "Pitch shift applied to ALL samples in the project. "
                            + "Re-rendering happens immediately when you move the slider."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }
                    Row { spacing: 8; width: parent.width
                        Slider {
                            id: gpSlider
                            width: parent.width - 100
                            from: -12; to: 12; stepSize: 0.5
                            value: controller.globalPitchSemitones
                            onPressedChanged: if (!pressed) controller.setGlobalPitch(value)
                        }
                        Text {
                            text: (gpSlider.value >= 0 ? "+" : "")
                                + gpSlider.value.toFixed(1) + " st"
                            color: Math.abs(gpSlider.value) > 0.5 ? cAccent : cMuted
                            font.pixelSize: 12; font.bold: true
                            width: 60
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        MiniBtn {
                            label: "0"
                            selColor: cBorder
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: controller.setGlobalPitch(0.0)
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    // ── NEW: Metronome & Recording ──
                    Text { text: "Metronome & Recording"; color: cText
                        font.pixelSize: 13; font.bold: true }
                    Text {
                        text: "Metronome syncs to detected BPM. Count-in plays before "
                            + "recording starts. Quantize snaps recorded events to beat."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    // Count-in bars
                    Row { spacing: 8; width: parent.width
                        Text { text: "Count-in (bars):"; color: cText
                            font.pixelSize: 11
                            anchors.verticalCenter: parent.verticalCenter }
                        Repeater {
                            model: [0, 1, 2, 4]
                            delegate: MiniBtn {
                                label: modelData === 0 ? "OFF" : modelData.toString()
                                selected: controller.metronomeCountInBars === modelData
                                selColor: modelData === 0 ? cBorder : cAccent
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: controller.setCountInBars(modelData)
                            }
                        }
                    }

                    // Quantize
                    Row { spacing: 8; width: parent.width
                        Text { text: "Quantize:"; color: cText
                            font.pixelSize: 11
                            anchors.verticalCenter: parent.verticalCenter
                            width: 80 }
                        Slider {
                            id: qSlider
                            width: parent.width - 200
                            from: 0; to: 100; stepSize: 5
                            value: controller.quantizePercent
                            onMoved: controller.setQuantizePercent(value)
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: qSlider.value === 0
                                ? "OFF" : qSlider.value.toFixed(0) + "%"
                            color: qSlider.value === 0 ? cMuted : cGreen
                            font.pixelSize: 11; font.bold: qSlider.value > 0
                            width: 50
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Text {
                        text: "0% = raw timing (exactly as you played).  "
                            + "100% = snap every event to nearest beat."
                        color: cMuted; font.pixelSize: 9
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    // Keyboard shortcuts cheatsheet
                    Rectangle {
                        width: parent.width; radius: 4
                        color: cCard; border.color: cBorder; border.width: 1
                        height: ksCol.height + 16

                        Column {
                            id: ksCol
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 3
                            Text { text: "Keyboard Shortcuts"
                                color: cText; font.pixelSize: 11; font.bold: true }
                            Text { text: "• Pads: 1 2 3 4 | Q W E R | A S D F | Z X C V"
                                color: cMuted; font.pixelSize: 9 }
                            Text { text: "• Space = Play / Pause"
                                color: cMuted; font.pixelSize: 9 }
                            Text { text: "• Ctrl+R = Record / Stop record"
                                color: cMuted; font.pixelSize: 9 }
                            Text { text: "• Ctrl+M = Toggle metronome"
                                color: cMuted; font.pixelSize: 9 }
                        }
                    }
                }

                // ──── TAB 3: MIDI / AI ANALYSIS (NEW) ────
                Column {
                    visible: settingsTab === 3
                    width: parent.width; spacing: 12

                    // MIDI Keyboard Detection
                    Text { text: "MIDI Keyboard"; color: cText
                        font.pixelSize: 14; font.bold: true }
                    Text {
                        text: "Auto-detect connected MIDI keyboards and "
                            + "classify them by key count."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    Row { spacing: 8
                        MiniBtn {
                            label: "🔍 Detect MIDI Keyboards"
                            selected: true; selColor: cAccent
                            onClicked: controller.detectMidiKeyboards()
                        }
                    }

                    // List of detected keyboards
                    Rectangle {
                        width: parent.width
                        height: Math.min(120, kbList.contentHeight + 8)
                        color: cCard; radius: 6
                        border.color: cBorder; border.width: 1
                        visible: kbList.count > 0

                        ListView {
                            id: kbList
                            anchors.fill: parent; anchors.margins: 4
                            model: controller.midiKeyboardModel
                            clip: true
                            spacing: 2

                            delegate: Rectangle {
                                width: kbList.width; height: 28; radius: 4
                                color: model.isSelected ? cAccent : "transparent"
                                Row {
                                    anchors.fill: parent; anchors.margins: 6
                                    spacing: 8
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: model.isSelected ? "●" : "○"
                                        color: model.isSelected ? "white" : cMuted
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: model.displayName
                                        color: model.isSelected ? "white" : cText
                                        font.pixelSize: 11
                                        font.bold: model.isSelected
                                    }
                                    Item { width: 1; height: 1 }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "(" + model.portName + ")"
                                        color: model.isSelected ? "#FFFFFFAA" : cMuted
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: controller.selectMidiKeyboard(index)
                                }
                            }
                        }
                    }

                    Text {
                        visible: kbList.count === 0
                        text: "No MIDI keyboards detected. Tap '🔍 Detect' to scan."
                        color: cMuted; font.pixelSize: 10; font.italic: true
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    // BPM & Key Detection
                    Text { text: "BPM & Key Detection"; color: cText
                        font.pixelSize: 14; font.bold: true }
                    Text {
                        text: "Fractional BPM, time signature, and musical key "
                            + "with bilingual labels (EN / IT)."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    Row { spacing: 8
                        MiniBtn {
                            label: "🎵 Detect BPM & Key"
                            selected: true; selColor: cAccent
                            onClicked: controller.detectBpmOfCurrentSource()
                        }
                    }

                    // Detection results
                    GridLayout {
                        visible: controller.detectedBpm > 0
                        width: parent.width
                        columns: 2; rowSpacing: 6; columnSpacing: 16

                        Text { text: "BPM:"; color: cMuted; font.pixelSize: 11 }
                        Text { text: controller.detectedBpm.toFixed(2)
                            color: cAccent; font.pixelSize: 14; font.bold: true }

                        Text { text: "Time signature:"; color: cMuted; font.pixelSize: 11 }
                        Text { text: controller.detectedTimeSignature
                            color: cText; font.pixelSize: 12; font.bold: true }

                        Text { text: "Confidence:"; color: cMuted; font.pixelSize: 11 }
                        Row { spacing: 6
                            Text {
                                text: (controller.bpmConfidence * 100).toFixed(0) + "%"
                                color: controller.bpmConfidence > 0.7
                                    ? cGreen : (controller.bpmConfidence > 0.4
                                        ? cOrange : cRed)
                                font.pixelSize: 12; font.bold: true
                            }
                            Rectangle {
                                width: 80; height: 8; radius: 3
                                color: cBorder
                                anchors.verticalCenter: parent.verticalCenter
                                Rectangle {
                                    width: parent.width * controller.bpmConfidence
                                    height: parent.height; radius: 3
                                    color: controller.bpmConfidence > 0.7
                                        ? cGreen : (controller.bpmConfidence > 0.4
                                            ? cOrange : cRed)
                                }
                            }
                        }

                        Text { text: "Key (English):"; color: cMuted; font.pixelSize: 11 }
                        Text { text: controller.detectedKeyEnglish || "—"
                            color: cText; font.pixelSize: 12; font.bold: true }

                        Text { text: "Tonalità (IT):"; color: cMuted; font.pixelSize: 11 }
                        Text { text: controller.detectedKeyItalian || "—"
                            color: cText; font.pixelSize: 12; font.bold: true }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    // Sample Analysis — Detailed explanation
                    Text { text: "Sample AI Analysis"; color: cText
                        font.pixelSize: 14; font.bold: true }
                    Text {
                        text: "Tap '🎨 Analyze' on the waveform toolbar. The AI "
                            + "automatically detects what's in your sample and "
                            + "marks it with colors. Hover over the colored bars "
                            + "to see what each part is."
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    // What each color means
                    Text { text: "What the colors mean:"; color: cText
                        font.pixelSize: 12; font.bold: true }

                    Column {
                        width: parent.width; spacing: 6

                        // PHRASE
                        Column { spacing: 3; width: parent.width
                            Row { spacing: 8
                                Rectangle { width: 20; height: 10; radius: 2
                                    color: "#3D8EF0" }
                                Text { text: "🔵 PHRASE (BLUE)"
                                    color: cText; font.pixelSize: 11; font.bold: true
                                    anchors.verticalCenter: parent.verticalCenter }
                            }
                            Text {
                                text: "A sustained vocal or melodic sound. "
                                    + "Example: someone singing \"hello\" "
                                    + "(1–2 seconds of continuous voice)."
                                color: cMuted; font.pixelSize: 9; wrapMode: Text.WordWrap
                                width: parent.width
                                leftPadding: 28
                            }
                        }

                        // HIT
                        Column { spacing: 3; width: parent.width
                            Row { spacing: 8
                                Rectangle { width: 20; height: 10; radius: 2
                                    color: "#E74C3C" }
                                Text { text: "🔴 HIT (RED)"
                                    color: cText; font.pixelSize: 11; font.bold: true
                                    anchors.verticalCenter: parent.verticalCenter }
                            }
                            Text {
                                text: "A sharp, quick percussion sound. "
                                    + "Example: a drum kick, snare, or hand clap "
                                    + "(very short, sharp attack)."
                                color: cMuted; font.pixelSize: 9; wrapMode: Text.WordWrap
                                width: parent.width
                                leftPadding: 28
                            }
                        }

                        // BREAK
                        Column { spacing: 3; width: parent.width
                            Row { spacing: 8
                                Rectangle { width: 20; height: 10; radius: 2
                                    color: "#7878A0" }
                                Text { text: "⚫ BREAK (GRAY)"
                                    color: cText; font.pixelSize: 11; font.bold: true
                                    anchors.verticalCenter: parent.verticalCenter }
                            }
                            Text {
                                text: "Silence or quiet space between sounds. "
                                    + "Example: the pause between two words "
                                    + "(helps separate different parts)."
                                color: cMuted; font.pixelSize: 9; wrapMode: Text.WordWrap
                                width: parent.width
                                leftPadding: 28
                            }
                        }

                        // CORE
                        Column { spacing: 3; width: parent.width
                            Row { spacing: 8
                                Rectangle { width: 20; height: 10; radius: 2
                                    color: "#F1C40F" }
                                Text { text: "⭐ CORE (YELLOW)"
                                    color: cText; font.pixelSize: 11; font.bold: true
                                    anchors.verticalCenter: parent.verticalCenter }
                            }
                            Text {
                                text: "The \"heart\" of a phrase — the most "
                                    + "important 0.5–2 seconds. This is the "
                                    + "most energetic or interesting part you'd "
                                    + "want to loop or isolate."
                                color: cMuted; font.pixelSize: 9; wrapMode: Text.WordWrap
                                width: parent.width
                                leftPadding: 28
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    // Example scenario
                    Text { text: "Example: \"On the Corner\""; color: cText
                        font.pixelSize: 12; font.bold: true }
                    Text {
                        text: "If you load a vocal sample that says "
                            + "\"I am ready... on the corner... I am drinking\", "
                            + "the AI detects:"
                        color: cMuted; font.pixelSize: 10
                        wrapMode: Text.WordWrap; width: parent.width
                    }

                    Column {
                        width: parent.width; spacing: 3

                        Row { spacing: 6
                            Rectangle { width: 12; height: 6; radius: 1; color: "#3D8EF0" }
                            Text { text: "\"I am ready\" (BLUE PHRASE)"
                                color: cText; font.pixelSize: 10 }
                        }
                        Row { spacing: 6
                            Rectangle { width: 12; height: 6; radius: 1; color: "#F1C40F" }
                            Text { text: "Its core part highlighted (YELLOW)"
                                color: cText; font.pixelSize: 10 }
                        }
                        Row { spacing: 6
                            Rectangle { width: 12; height: 6; radius: 1; color: "#E74C3C" }
                            Text { text: "\"on the corner\" (RED HIT — sharp)"
                                color: cText; font.pixelSize: 10 }
                        }
                        Row { spacing: 6
                            Rectangle { width: 12; height: 6; radius: 1; color: "#3D8EF0" }
                            Text { text: "\"I am drinking\" (BLUE PHRASE)"
                                color: cText; font.pixelSize: 10 }
                        }
                    }

                    Text {
                        text: "You can then assign each colored section to different pads "
                            + "and layer them, or just use the CORE part as a loop."
                        color: cMuted; font.pixelSize: 9; wrapMode: Text.WordWrap
                        width: parent.width
                    }
                }

                // ──── TAB 4: INFO ────
                Column {
                    visible: settingsTab === 4
                    width: parent.width; spacing: 10

                    Text { text: "Processing Mode"; color: cText
                        font.pixelSize: 13; font.bold: true }
                    Row { spacing: 8
                        Rectangle {
                            width: 70; height: 28; radius: 14
                            color: controller.qualityMode === "fast"
                                ? "#1A2A1A" : "#1A1A30"
                            border.color: controller.qualityMode === "fast"
                                ? cGreen : cAccent
                            Text { anchors.centerIn: parent
                                text: controller.qualityMode === "fast"
                                    ? "⚡ Fast" : "✦ Quality"
                                color: controller.qualityMode === "fast"
                                    ? cGreen : cAccent
                                font.pixelSize: 11; font.bold: true }
                        }
                        Text {
                            text: controller.qualityMode === "fast"
                                ? "htdemucs — quicker separation"
                                : "htdemucs_ft — cleaner stems, slower"
                            color: cMuted; font.pixelSize: 11
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }

                    MiniBtn {
                        label: "Reset Mode Choice"
                        selected: true; selColor: cRed
                        onClicked: { controller.resetQualityMode()
                            showSettings = false }
                    }

                    Text {
                        text: "Sampler v5 — settings persist to data/settings.json"
                        color: cBorder; font.pixelSize: 9
                    }
                }
            }
        }
    }
}
