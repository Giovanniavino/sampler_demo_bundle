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
    property int  settingsTab: 0  // 0=Slicing 1=PadLayout 2=Playback 3=Info

    FileDialog {
        id: fileDialog
        nameFilters: ["Audio (*.mp3 *.wav *.flac *.ogg *.m4a)"]
        onAccepted: controller.loadTrack(selectedFile.toString())
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
    // Re-usable mini button component
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
                    hoverEnabled: true
                    onClicked: { showSettings = !showSettings; showSampleEdit = false } }
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

            Text {
                text: (controller.trackName || "No track")
                    + (controller.bpm > 0 ? "  •  " + controller.bpm.toFixed(1) + " BPM" : "")
                    + (controller.trackKey ? "  •  " + controller.trackKey : "")
                color: cText; font.pixelSize: 11
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

        // Header: pad badge + sample name + duration + toolbar
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
                width: 220
            }
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

            Item { width: 8; height: 1 }

            // ── Toolbar: zoom out / zoom in / fit / snap / edit ──────
            MiniBtn {
                anchors.verticalCenter: parent.verticalCenter
                label: "−"; selColor: cBorder
                enabled: controller.currentSampleName !== ""
                opacity: enabled ? 1.0 : 0.4
                onClicked: {
                    // Zoom out 2× around the centre of current zoom
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
                    // Zoom in to the current sample region with 10% padding
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
                label: "▶ Preview"
                selColor: cGreen
                enabled: controller.currentSampleName !== ""
                opacity: enabled ? 1.0 : 0.4
                onClicked: controller.previewCurrentSample()
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

            // JS helper: snap a normalized fraction to nearest beat if enabled
            function snapFrac(f) {
                if (!controller.snapToBeats) return f
                var beats = controller.currentSampleBeats
                if (!beats || beats.length === 0) return f
                var best = f, bestD = 1.0
                for (var i = 0; i < beats.length; i++) {
                    var d = Math.abs(beats[i] - f)
                    if (d < bestD) { bestD = d; best = beats[i] }
                }
                // Snap only if within ~3% of total duration
                return bestD < 0.03 ? best : f
            }

            // Convert visible-x coords to absolute frac and vice versa
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

                    // Beat ticks (when snap is on)
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

            // START marker
            Rectangle {
                id: startMarker
                visible: controller.currentSampleName !== ""
                width: 14; height: wfBg.height
                color: "transparent"
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
                        controller.setCurrentSampleRegion(
                            f, controller.currentSampleEndFrac)
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
                }
            }

            // ── Pinch-to-zoom (touchscreen) ──────────────────────────
            PinchArea {
                anchors.fill: parent
                mouseEnabled: false   // don't steal mouse from marker drags
                property real _z0: 0
                property real _z1: 1
                onPinchStarted: {
                    _z0 = controller.zoomStart
                    _z1 = controller.zoomEnd
                }
                onPinchUpdated: {
                    var origSpan = _z1 - _z0
                    // Centre of pinch in absolute frac (using start snapshot)
                    var cx = _z0 + (pinch.center.x / wfBg.width) * origSpan
                    var newSpan = Math.max(0.02,
                        Math.min(1.0, origSpan / Math.max(0.01, pinch.scale)))
                    var ns = cx - newSpan / 2
                    var ne = cx + newSpan / 2
                    // Clamp & shift to keep inside [0,1]
                    if (ns < 0.0) { ne = Math.min(1.0, ne - ns); ns = 0.0 }
                    if (ne > 1.0) { ns = Math.max(0.0, ns - (ne - 1.0)); ne = 1.0 }
                    controller.setWaveformZoom(ns, ne)
                }
            }

            // ── Wheel: Ctrl+scroll = zoom, plain scroll = pan ─────────
            WheelHandler {
                target: null
                grabPermissions: PointerHandler.CanTakeOverFromAnything
                onWheel: function(event) {
                    var z0   = controller.zoomStart
                    var z1   = controller.zoomEnd
                    var span = z1 - z0
                    if (event.modifiers & Qt.ControlModifier) {
                        // Zoom centred on cursor position
                        var cx = z0 + (event.x / wfBg.width) * span
                        var factor = event.angleDelta.y > 0 ? 0.75 : 1.33
                        var ns = cx - (cx - z0) * factor
                        var ne = cx + (z1 - cx) * factor
                        if (ns < 0.0) { ne = Math.min(1.0, ne - ns); ns = 0.0 }
                        if (ne > 1.0) { ns = Math.max(0.0, ns - (ne - 1.0)); ne = 1.0 }
                        if (ne - ns >= 0.02) controller.setWaveformZoom(ns, ne)
                    } else {
                        // Pan: horizontal scroll preferred, fall back to vertical
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
    // PAD GRID — scrollable when gridSize > what fits
    // ════════════════════════════════════════════════════════════════
    Item {
        id: padArea
        anchors.top: editor.bottom
        anchors.bottom: bottomBar.top
        anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: 4
        visible: !showSettings && !showSampleEdit

        // Column count: 4 for ≤16, 5 for 17–25, 6 above that
        property int cols: controller.gridSize <= 16 ? 4
                            : (controller.gridSize <= 25 ? 5 : 6)
        property int rowsNeeded: Math.ceil(controller.gridSize / cols)
        property real cellW: width / cols
        // Cell height: ideal fit if it leaves a square-ish ratio,
        // otherwise use a comfortable minimum and let the grid scroll.
        property real cellH: {
            var idealH = height / rowsNeeded
            // Don't let cells get taller than wide (looks weird)
            var maxH = cellW
            // Keep usable touch target
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
    // SAMPLE EDIT OVERLAY — gain / pitch / stretch / reverse / fades
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        anchors.fill: parent
        color: cBg; visible: showSampleEdit; z: 9

        Column {
            anchors.fill: parent; anchors.margins: 12; spacing: 8

            // Header row
            Row {
                width: parent.width; spacing: 8
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
                    elide: Text.ElideRight; width: 300 }
                Item { width: 1; height: 1; Layout.fillWidth: true }
                MiniBtn {
                    label: "▶ Preview"; selColor: cGreen
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: controller.previewCurrentSample()
                }
                MiniBtn {
                    label: "Reset"; selColor: cOrange
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: controller.resetCurrentSample()
                }
                MiniBtn {
                    label: "Close ✕"; selColor: cBorder
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: showSampleEdit = false
                }
            }

            Rectangle { width: parent.width; height: 1; color: cBorder }

            // Sliders area
            GridLayout {
                width: parent.width
                columns: 2
                columnSpacing: 24
                rowSpacing: 10

                // Gain
                Column {
                    Layout.fillWidth: true; spacing: 4
                    Row { width: parent.width
                        Text { text: "Gain"; color: cText
                            font.pixelSize: 12; font.bold: true }
                        Item { width: 1; height: 1
                            anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            anchors.right: parent.right
                            text: controller.currentSampleGainDb.toFixed(1) + " dB"
                            color: cMuted; font.pixelSize: 11
                        }
                    }
                    Slider {
                        width: parent.width
                        from: -24; to: 12; stepSize: 0.1
                        value: controller.currentSampleGainDb
                        onMoved: controller.setCurrentSampleGain(value)
                    }
                }
                // Pitch
                Column {
                    Layout.fillWidth: true; spacing: 4
                    Row { width: parent.width
                        Text { text: "Pitch"; color: cText
                            font.pixelSize: 12; font.bold: true }
                        Text {
                            anchors.right: parent.right
                            text: (controller.currentSamplePitchSemitones >= 0 ? "+" : "")
                                + controller.currentSamplePitchSemitones.toFixed(1) + " st"
                            color: cMuted; font.pixelSize: 11
                        }
                    }
                    Slider {
                        width: parent.width
                        from: -12; to: 12; stepSize: 0.5
                        value: controller.currentSamplePitchSemitones
                        onMoved: controller.setCurrentSamplePitch(value)
                    }
                }
                // Time stretch
                Column {
                    Layout.fillWidth: true; spacing: 4
                    Row { width: parent.width
                        Text { text: "Time Stretch"; color: cText
                            font.pixelSize: 12; font.bold: true }
                        Text {
                            anchors.right: parent.right
                            text: controller.currentSampleTimeStretch.toFixed(2) + "×"
                            color: cMuted; font.pixelSize: 11
                        }
                    }
                    Slider {
                        width: parent.width
                        from: 0.5; to: 2.0; stepSize: 0.01
                        value: controller.currentSampleTimeStretch
                        onMoved: controller.setCurrentSampleTimeStretch(value)
                    }
                }
                // Reverse toggle
                Column {
                    Layout.fillWidth: true; spacing: 4
                    Text { text: "Reverse"; color: cText
                        font.pixelSize: 12; font.bold: true }
                    Row { spacing: 8
                        Switch {
                            checked: controller.currentSampleReverse
                            onToggled: controller.setCurrentSampleReverse(checked)
                        }
                        Text {
                            text: controller.currentSampleReverse ? "ON" : "OFF"
                            color: controller.currentSampleReverse ? cGreen : cMuted
                            font.pixelSize: 11; font.bold: true
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
                // Fade in
                Column {
                    Layout.fillWidth: true; spacing: 4
                    Row { width: parent.width
                        Text { text: "Fade In"; color: cText
                            font.pixelSize: 12; font.bold: true }
                        Text {
                            anchors.right: parent.right
                            text: controller.currentSampleFadeInMs.toFixed(0) + " ms"
                            color: cMuted; font.pixelSize: 11
                        }
                    }
                    Slider {
                        width: parent.width
                        from: 0; to: 500; stepSize: 1
                        value: controller.currentSampleFadeInMs
                        onMoved: controller.setCurrentSampleFadeInMs(value)
                    }
                }
                // Fade out
                Column {
                    Layout.fillWidth: true; spacing: 4
                    Row { width: parent.width
                        Text { text: "Fade Out"; color: cText
                            font.pixelSize: 12; font.bold: true }
                        Text {
                            anchors.right: parent.right
                            text: controller.currentSampleFadeOutMs.toFixed(0) + " ms"
                            color: cMuted; font.pixelSize: 11
                        }
                    }
                    Slider {
                        width: parent.width
                        from: 0; to: 500; stepSize: 1
                        value: controller.currentSampleFadeOutMs
                        onMoved: controller.setCurrentSampleFadeOutMs(value)
                    }
                }
            }

            Text {
                width: parent.width
                text: "Tip: Reset restores the start/end region and all params "
                    + "to the values captured when this pad was first selected."
                color: cMuted; font.pixelSize: 10; wrapMode: Text.WordWrap
            }
        }
    }

    // ════════════════════════════════════════════════════════════════
    // SETTINGS OVERLAY — 4 tabs
    // ════════════════════════════════════════════════════════════════
    Rectangle {
        anchors.fill: parent
        color: cBg; visible: showSettings; z: 10

        // Tab bar
        Row {
            id: tabBar
            anchors.top: parent.top
            anchors.left: parent.left; anchors.right: parent.right
            anchors.margins: 8
            height: 28; spacing: 4

            Repeater {
                model: ["Slicing", "Pad Layout", "Playback", "Info"]
                delegate: Rectangle {
                    width: 110; height: 28; radius: 6
                    color: settingsTab === index ? cAccent : cCard
                    border.color: settingsTab === index ? cAccent : cBorder
                    Text { anchors.centerIn: parent
                        text: modelData; color: cText
                        font.pixelSize: 12
                        font.bold: settingsTab === index }
                    MouseArea { anchors.fill: parent
                        onClicked: settingsTab = index }
                }
            }
            Item { width: 16; height: 1 }
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

        // Tab content (scrollable)
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

                // ──── TAB 0: SLICING ──────────────────────────────────
                Column {
                    visible: settingsTab === 0
                    width: parent.width; spacing: 12

                    // Vocal preset
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
                        // Custom fields
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

                    // Drum preset
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
                                property real realVal: 1.0
                                // Stored as ints in SpinBox; treat as 0.25 steps
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

                    // Loops preset
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

                // ──── TAB 1: PAD LAYOUT ───────────────────────────────
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

                // ──── TAB 2: PLAYBACK ─────────────────────────────────
                Column {
                    visible: settingsTab === 2
                    width: parent.width; spacing: 10

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
                }

                // ──── TAB 3: INFO ─────────────────────────────────────
                Column {
                    visible: settingsTab === 3
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
                        text: "Sampler v4 — settings persist to data/settings.json"
                        color: cBorder; font.pixelSize: 9
                    }
                }
            }
        }
    }
}
