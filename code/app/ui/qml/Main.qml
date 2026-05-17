import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs

ApplicationWindow {
    id: root
    width: 1024; height: 600
    visible: true
    title: "Sampler"
    color: "#0F0F12"

    // ── Palette ──────────────────────────────────────────────────────────
    readonly property color cBg:       "#0F0F12"
    readonly property color cPanel:    "#1A1A22"
    readonly property color cCard:     "#24242E"
    readonly property color cBorder:   "#2E2E3A"
    readonly property color cAccent:   "#3D8EF0"
    readonly property color cText:     "#E8E8F0"
    readonly property color cMuted:    "#7878A0"
    readonly property color cGreen:    "#1ABC9C"
    readonly property color cPurple:   "#9B59B6"
    readonly property color cOrange:   "#E67E22"

    // ── State ─────────────────────────────────────────────────────────────
    property bool showSettings:    false
    property bool showSampleEditor: false
    property int  editorPadIndex:   -1
    property string editorSampleName: ""
    property real   editorGainDb:   0.0
    property real   editorFadeInMs: 3.0
    property real   editorFadeOutMs: 6.0

    // Wire sample editor open signal
    Connections {
        target: controller
        function onSampleEditorOpen(padIdx, name, gain, fadeIn, fadeOut) {
            editorPadIndex    = padIdx
            editorSampleName  = name
            editorGainDb      = gain
            editorFadeInMs    = fadeIn
            editorFadeOutMs   = fadeOut
            showSampleEditor  = true
        }
    }

    FileDialog {
        id: fileDialog
        title: "Choose an audio track"
        nameFilters: ["Audio (*.mp3 *.wav *.flac *.ogg *.m4a)"]
        onAccepted: controller.loadTrack(selectedFile.toString())
    }

    // ── Top bar ──────────────────────────────────────────────────────────
    Rectangle {
        id: topBar
        anchors.top: parent.top
        width: parent.width; height: 56
        color: cPanel

        RowLayout {
            anchors.fill: parent; anchors.margins: 10; spacing: 8

            // Load
            Rectangle {
                width: 80; height: 36; radius: 6
                color: loadMouse.containsMouse ? cAccent : cCard
                border.color: cBorder; border.width: 1
                Text { anchors.centerIn: parent; text: "Load"
                    color: cText; font.pixelSize: 13; font.bold: true }
                MouseArea { id: loadMouse; anchors.fill: parent
                    hoverEnabled: true; onClicked: fileDialog.open() }
            }

            // Stop All
            Rectangle {
                width: 80; height: 36; radius: 6
                color: stopMouse.containsMouse ? "#C0392B" : cCard
                border.color: cBorder; border.width: 1
                Text { anchors.centerIn: parent; text: "Stop All"
                    color: cText; font.pixelSize: 13; font.bold: true }
                MouseArea { id: stopMouse; anchors.fill: parent
                    hoverEnabled: true; onClicked: controller.stopAll() }
            }

            // Settings toggle
            Rectangle {
                width: 36; height: 36; radius: 6
                color: showSettings ? cAccent : (setMouse.containsMouse ? cCard : "transparent")
                border.color: showSettings ? cAccent : cBorder; border.width: 1
                Text { anchors.centerIn: parent; text: "⚙"
                    color: cText; font.pixelSize: 16 }
                MouseArea { id: setMouse; anchors.fill: parent
                    hoverEnabled: true; onClicked: showSettings = !showSettings }
            }

            Item { Layout.fillWidth: true }

            // Track + BPM
            Column {
                spacing: 1; Layout.alignment: Qt.AlignRight
                Text { text: controller.trackName || "No track loaded"
                    color: cText; font.pixelSize: 14; font.bold: true
                    horizontalAlignment: Text.AlignRight }
                Text { text: controller.bpm > 0 ? controller.bpm.toFixed(1) + " BPM" : ""
                    color: cMuted; font.pixelSize: 11
                    horizontalAlignment: Text.AlignRight }
            }
        }
    }

    // ── Settings panel ───────────────────────────────────────────────────
    Rectangle {
        id: settingsPanel
        anchors.top: topBar.bottom
        width: parent.width; height: parent.height - topBar.height - bottomBar.height
        color: cBg
        visible: showSettings
        z: 10

        // Tab bar
        TabBar {
            id: settingsTabBar
            anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
            height: 38; background: Rectangle { color: cPanel }

            TabButton {
                text: "Slicing"
                contentItem: Text { text: parent.text; color: cText
                    font.pixelSize: 12; font.bold: settingsTabBar.currentIndex === 0
                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle {
                    color: settingsTabBar.currentIndex === 0 ? cCard : cPanel
                    border.color: settingsTabBar.currentIndex === 0 ? cAccent : "transparent"
                    border.width: 0; Rectangle { height: 2; color: cAccent
                        anchors.bottom: parent.bottom; width: parent.width
                        visible: settingsTabBar.currentIndex === 0 } }
            }
            TabButton {
                text: "Pad Layout"
                contentItem: Text { text: parent.text; color: cText
                    font.pixelSize: 12; font.bold: settingsTabBar.currentIndex === 1
                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle {
                    color: settingsTabBar.currentIndex === 1 ? cCard : cPanel
                    Rectangle { height: 2; color: cAccent; anchors.bottom: parent.bottom
                        width: parent.width; visible: settingsTabBar.currentIndex === 1 } }
            }
            TabButton {
                text: "Playback"
                contentItem: Text { text: parent.text; color: cText
                    font.pixelSize: 12; font.bold: settingsTabBar.currentIndex === 2
                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle {
                    color: settingsTabBar.currentIndex === 2 ? cCard : cPanel
                    Rectangle { height: 2; color: cAccent; anchors.bottom: parent.bottom
                        width: parent.width; visible: settingsTabBar.currentIndex === 2 } }
            }
        }

        StackLayout {
            currentIndex: settingsTabBar.currentIndex
            anchors.top: settingsTabBar.bottom; anchors.bottom: applyRow.top
            anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 12

            // ---- TAB 0: Slicing ----------------------------------------
            ScrollView {
                clip: true
                GridLayout {
                    columns: 4; columnSpacing: 16; rowSpacing: 10
                    width: parent.width

                    // Section header helper
                    function hdr(t) { return t }

                    // VOCAL PHRASES
                    Text { text: "── VOCAL PHRASES ──"; color: cMuted
                        font.pixelSize: 10; Layout.columnSpan: 4 }

                    Text { text: "Min length (ms)"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spMinVocalMs; from: 200; to: 10000; stepSize: 100
                        value: controller.minVocalPhraseMs
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Max length (ms)"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spMaxVocalMs; from: 1000; to: 30000; stepSize: 500
                        value: controller.maxVocalPhraseMs
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Min gap (ms)"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spVocalGap; from: 100; to: 2000; stepSize: 50
                        value: controller.vocalPhraseMinGapMs
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Max phrases"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spMaxPhrases; from: 1; to: 16; value: controller.maxVocalPhrases
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    // VOCAL CHOPS
                    Text { text: "── VOCAL CHOPS ──"; color: cMuted
                        font.pixelSize: 10; Layout.columnSpan: 4 }

                    Text { text: "Chop length (ms)"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spChopLen; from: 200; to: 4000; stepSize: 100
                        value: controller.vocalChopLengthMs
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Max chops"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spMaxChops; from: 1; to: 16; value: controller.maxVocalChops
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    // DRUM HITS
                    Text { text: "── DRUM HITS ──"; color: cMuted
                        font.pixelSize: 10; Layout.columnSpan: 4 }

                    Text { text: "Hit length (ms)"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spDrumHitLen; from: 50; to: 2000; stepSize: 50
                        value: controller.drumHitLengthMs
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Max hits"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spMaxHits; from: 1; to: 32; value: controller.maxDrumHits
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    // LOOPS
                    Text { text: "── LOOPS ──"; color: cMuted
                        font.pixelSize: 10; Layout.columnSpan: 4 }

                    Text { text: "Loops per stem"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spLoopsPerStem; from: 1; to: 8; value: controller.nLoopsPerStem
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Drum loop bars"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spDrumBars; from: 1; to: 8; value: controller.drumLoopBars
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Bass loop bars"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spBassBars; from: 1; to: 8; value: controller.bassLoopBars
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Melody bars"; color: cText; font.pixelSize: 12 }
                    SpinBox { id: spMelBars; from: 1; to: 8; value: controller.melodyPhraseBars
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }
                }
            }

            // ---- TAB 1: Pad Layout -------------------------------------
            Item {
                GridLayout {
                    anchors.centerIn: parent
                    columns: 4; columnSpacing: 20; rowSpacing: 14

                    Text { text: "Category"; color: cMuted; font.pixelSize: 11; font.bold: true }
                    Text { text: "Pads"; color: cMuted; font.pixelSize: 11; font.bold: true }
                    Text { text: "Category"; color: cMuted; font.pixelSize: 11; font.bold: true }
                    Text { text: "Pads"; color: cMuted; font.pixelSize: 11; font.bold: true }

                    Text { text: "Drum Hits"; color: cText; font.pixelSize: 13 }
                    SpinBox { id: plDrumHit; from: 0; to: 16; value: controller.padsDrumHit
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Drum Loops"; color: cText; font.pixelSize: 13 }
                    SpinBox { id: plDrumLoop; from: 0; to: 16; value: controller.padsDrumLoop
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Vocal Chops"; color: cText; font.pixelSize: 13 }
                    SpinBox { id: plVocalChop; from: 0; to: 16; value: controller.padsVocalChop
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Vocal Phrases"; color: cText; font.pixelSize: 13 }
                    SpinBox { id: plVocalPhrase; from: 0; to: 16; value: controller.padsVocalPhrase
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Melody"; color: cText; font.pixelSize: 13 }
                    SpinBox { id: plMelody; from: 0; to: 16; value: controller.padsMelody
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text { text: "Bass Loops"; color: cText; font.pixelSize: 13 }
                    SpinBox { id: plBassLoop; from: 0; to: 16; value: controller.padsBassLoop
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    // Total indicator
                    Item { Layout.columnSpan: 2 }
                    Text { text: "Grid size"; color: cText; font.pixelSize: 13 }
                    SpinBox { id: plGridSize; from: 4; to: 32; stepSize: 4
                        value: controller.gridSize
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    // Live total
                    Text { Layout.columnSpan: 4
                        text: {
                            var total = plDrumHit.value + plDrumLoop.value +
                                        plVocalChop.value + plVocalPhrase.value +
                                        plMelody.value + plBassLoop.value
                            var over = total > plGridSize.value
                            return "Total assigned: " + total + " / " + plGridSize.value +
                                   (over ? "  ⚠ exceeds grid" : "  ✓")
                        }
                        color: {
                            var total = plDrumHit.value + plDrumLoop.value +
                                        plVocalChop.value + plVocalPhrase.value +
                                        plMelody.value + plBassLoop.value
                            return total > plGridSize.value ? cOrange : cGreen
                        }
                        font.pixelSize: 12
                    }
                }
            }

            // ---- TAB 2: Playback ---------------------------------------
            Item {
                GridLayout {
                    anchors.centerIn: parent
                    columns: 2; columnSpacing: 24; rowSpacing: 16

                    Text { text: "Block size"; color: cText; font.pixelSize: 13 }
                    ComboBox {
                        id: cbBlockSize
                        model: [128, 256, 512, 1024]
                        currentIndex: {
                            var v = controller.blockSize
                            for (var i = 0; i < model.length; i++)
                                if (model[i] === v) return i
                            return 2
                        }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 }
                        contentItem: Text { text: cbBlockSize.displayText
                            color: cText; font.pixelSize: 12
                            leftPadding: 8; verticalAlignment: Text.AlignVCenter }
                    }

                    Text { text: "Sample rate"; color: cText; font.pixelSize: 13 }
                    ComboBox {
                        id: cbSampleRate
                        model: [44100, 48000]
                        currentIndex: controller.sampleRate === 48000 ? 1 : 0
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 }
                        contentItem: Text { text: cbSampleRate.displayText
                            color: cText; font.pixelSize: 12
                            leftPadding: 8; verticalAlignment: Text.AlignVCenter }
                    }

                    Text { text: "Est. latency"; color: cMuted; font.pixelSize: 12 }
                    Text {
                        text: (cbBlockSize.currentValue / cbSampleRate.currentValue * 1000).toFixed(1) + " ms"
                        color: cAccent; font.pixelSize: 12; font.bold: true
                    }

                    // Toggles
                    Text { text: "Press-and-hold loop"; color: cText; font.pixelSize: 13 }
                    Switch {
                        id: swHoldLoop; checked: controller.pressHoldLoop
                        indicator: Rectangle {
                            width: 44; height: 22; radius: 11
                            color: parent.checked ? cAccent : cCard
                            border.color: cBorder
                            Rectangle { x: parent.parent.checked ? 24 : 2
                                y: 2; width: 18; height: 18; radius: 9
                                color: cText
                                Behavior on x { NumberAnimation { duration: 120 } } }
                        }
                    }

                    Text { text: "Auto-normalize stems"; color: cText; font.pixelSize: 13 }
                    Switch {
                        id: swNormalize; checked: controller.autoNormalizeStems
                        indicator: Rectangle {
                            width: 44; height: 22; radius: 11
                            color: parent.checked ? cAccent : cCard; border.color: cBorder
                            Rectangle { x: parent.parent.checked ? 24 : 2; y: 2
                                width: 18; height: 18; radius: 9; color: cText
                                Behavior on x { NumberAnimation { duration: 120 } } }
                        }
                    }

                    Text { text: "Auto-choke drums"; color: cText; font.pixelSize: 13 }
                    Switch {
                        id: swChoke; checked: controller.autoChokeDrums
                        indicator: Rectangle {
                            width: 44; height: 22; radius: 11
                            color: parent.checked ? cAccent : cCard; border.color: cBorder
                            Rectangle { x: parent.parent.checked ? 24 : 2; y: 2
                                width: 18; height: 18; radius: 9; color: cText
                                Behavior on x { NumberAnimation { duration: 120 } } }
                        }
                    }
                }
            }
        }

        // Apply / Cancel row
        Rectangle {
            id: applyRow
            anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
            height: 48; color: cPanel
            RowLayout {
                anchors.fill: parent; anchors.margins: 10; spacing: 10
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 90; height: 34; radius: 6
                    color: cancelMouse.containsMouse ? cCard : "transparent"
                    border.color: cBorder
                    Text { anchors.centerIn: parent; text: "Cancel"; color: cMuted; font.pixelSize: 13 }
                    MouseArea { id: cancelMouse; anchors.fill: parent; hoverEnabled: true
                        onClicked: showSettings = false }
                }
                Rectangle {
                    width: 90; height: 34; radius: 6
                    color: applyMouse.containsMouse ? Qt.lighter(cAccent, 1.1) : cAccent
                    Text { anchors.centerIn: parent; text: "Apply"; color: "white"
                        font.pixelSize: 13; font.bold: true }
                    MouseArea {
                        id: applyMouse; anchors.fill: parent; hoverEnabled: true
                        onClicked: {
                            var tab = settingsTabBar.currentIndex
                            if (tab === 0) {
                                controller.applySlicingSettings(
                                    spMinVocalMs.value, spMaxVocalMs.value,
                                    spVocalGap.value, spMaxPhrases.value,
                                    spChopLen.value, spMaxChops.value,
                                    spDrumHitLen.value, spMaxHits.value,
                                    spLoopsPerStem.value, spDrumBars.value,
                                    spBassBars.value, spMelBars.value
                                )
                            } else if (tab === 1) {
                                controller.applyPadLayout(
                                    plDrumHit.value, plDrumLoop.value,
                                    plVocalChop.value, plVocalPhrase.value,
                                    plMelody.value, plBassLoop.value,
                                    plGridSize.value
                                )
                            } else {
                                controller.applyPlaybackSettings(
                                    cbBlockSize.currentValue,
                                    cbSampleRate.currentValue,
                                    swHoldLoop.checked,
                                    swNormalize.checked,
                                    swChoke.checked
                                )
                            }
                            showSettings = false
                        }
                    }
                }
            }
        }
    }

    // ── Sample editor overlay ────────────────────────────────────────────
    Rectangle {
        id: sampleEditor
        visible: showSampleEditor
        anchors.centerIn: parent
        width: 400; height: 280; radius: 12
        color: cCard; border.color: cAccent; border.width: 1
        z: 20

        Column {
            anchors.fill: parent; anchors.margins: 20; spacing: 14

            Text { text: "Sample: " + editorSampleName
                color: cText; font.pixelSize: 14; font.bold: true
                elide: Text.ElideRight; width: parent.width }

            // GAIN fader
            Row {
                spacing: 12; width: parent.width
                Text { text: "Gain"; color: cMuted; font.pixelSize: 12; width: 90
                    verticalAlignment: Text.AlignVCenter; height: 28 }
                Slider {
                    id: slGain; from: -24; to: 12; stepSize: 0.5
                    value: editorGainDb; width: 200
                    background: Rectangle {
                        x: slGain.leftPadding; y: slGain.topPadding + slGain.availableHeight / 2 - 2
                        width: slGain.availableWidth; height: 4; radius: 2
                        color: cBorder
                        Rectangle { width: slGain.visualPosition * parent.width
                            height: parent.height; color: cAccent; radius: 2 }
                    }
                    handle: Rectangle {
                        x: slGain.leftPadding + slGain.visualPosition * slGain.availableWidth - width / 2
                        y: slGain.topPadding + slGain.availableHeight / 2 - height / 2
                        width: 16; height: 16; radius: 8
                        color: cAccent; border.color: "white"; border.width: 1
                    }
                }
                Text { text: slGain.value.toFixed(1) + " dB"
                    color: cAccent; font.pixelSize: 12; width: 60 }
            }

            // FADE IN
            Row {
                spacing: 12; width: parent.width
                Text { text: "Fade In"; color: cMuted; font.pixelSize: 12; width: 90
                    verticalAlignment: Text.AlignVCenter; height: 28 }
                Slider {
                    id: slFadeIn; from: 0; to: 500; stepSize: 1
                    value: editorFadeInMs; width: 200
                    background: Rectangle {
                        x: slFadeIn.leftPadding; y: slFadeIn.topPadding + slFadeIn.availableHeight / 2 - 2
                        width: slFadeIn.availableWidth; height: 4; radius: 2; color: cBorder
                        Rectangle { width: slFadeIn.visualPosition * parent.width
                            height: parent.height; color: cGreen; radius: 2 } }
                    handle: Rectangle {
                        x: slFadeIn.leftPadding + slFadeIn.visualPosition * slFadeIn.availableWidth - 8
                        y: slFadeIn.topPadding + slFadeIn.availableHeight / 2 - 8
                        width: 16; height: 16; radius: 8; color: cGreen
                        border.color: "white"; border.width: 1 } }
                Text { text: slFadeIn.value.toFixed(0) + " ms"
                    color: cGreen; font.pixelSize: 12; width: 60 }
            }

            // FADE OUT
            Row {
                spacing: 12; width: parent.width
                Text { text: "Fade Out"; color: cMuted; font.pixelSize: 12; width: 90
                    verticalAlignment: Text.AlignVCenter; height: 28 }
                Slider {
                    id: slFadeOut; from: 0; to: 500; stepSize: 1
                    value: editorFadeOutMs; width: 200
                    background: Rectangle {
                        x: slFadeOut.leftPadding; y: slFadeOut.topPadding + slFadeOut.availableHeight / 2 - 2
                        width: slFadeOut.availableWidth; height: 4; radius: 2; color: cBorder
                        Rectangle { width: slFadeOut.visualPosition * parent.width
                            height: parent.height; color: cOrange; radius: 2 } }
                    handle: Rectangle {
                        x: slFadeOut.leftPadding + slFadeOut.visualPosition * slFadeOut.availableWidth - 8
                        y: slFadeOut.topPadding + slFadeOut.availableHeight / 2 - 8
                        width: 16; height: 16; radius: 8; color: cOrange
                        border.color: "white"; border.width: 1 } }
                Text { text: slFadeOut.value.toFixed(0) + " ms"
                    color: cOrange; font.pixelSize: 12; width: 60 }
            }

            // Buttons
            Row {
                spacing: 10; anchors.right: parent.right
                Rectangle {
                    width: 80; height: 32; radius: 6; color: cBorder
                    Text { anchors.centerIn: parent; text: "Cancel"
                        color: cMuted; font.pixelSize: 12 }
                    MouseArea { anchors.fill: parent
                        onClicked: showSampleEditor = false }
                }
                Rectangle {
                    width: 80; height: 32; radius: 6; color: cAccent
                    Text { anchors.centerIn: parent; text: "Apply"
                        color: "white"; font.pixelSize: 12; font.bold: true }
                    MouseArea { anchors.fill: parent
                        onClicked: {
                            controller.applySampleEdit(
                                editorPadIndex,
                                slGain.value, slFadeIn.value, slFadeOut.value
                            )
                            showSampleEditor = false
                        }
                    }
                }
            }
        }
    }

    // ── Pad grid ─────────────────────────────────────────────────────────
    GridView {
        id: padGrid
        anchors.top: topBar.bottom; anchors.bottom: bottomBar.top
        anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: 14
        visible: !showSettings

        property int columns: Math.max(1, Math.round(Math.sqrt(controller.gridSize)))
        cellWidth:  width  / columns
        cellHeight: height / columns

        model: controller.padModel
        interactive: false

        delegate: Item {
            width: padGrid.cellWidth; height: padGrid.cellHeight

            // Hold timer for press-and-hold-loop
            Timer {
                id: holdTimer; interval: 80; repeat: true; running: false
                onTriggered: controller.padHoldTick(model.padIndex)
            }

            Rectangle {
                id: padRect
                anchors.fill: parent; anchors.margins: 5
                radius: 8
                color: hasSample ? model.color : "#1C1C24"
                opacity: active ? 1.0 : (hasSample ? 0.82 : 0.45)
                border.color: active ? "#FFFFFF" : "#00000040"
                border.width: active ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 70 } }

                // Pad number
                Text {
                    anchors.top: parent.top; anchors.left: parent.left; anchors.margins: 7
                    text: (model.padIndex + 1).toString().padStart(2, "0")
                    color: "#00000060"; font.pixelSize: 11; font.bold: true
                }

                // Sample label
                Text {
                    anchors.bottom: parent.bottom; anchors.left: parent.left
                    anchors.right: parent.right; anchors.margins: 7
                    text: model.label; color: "#FFFFFF"; font.pixelSize: 10
                    font.bold: true; elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter
                }

                // Mode badge — tap to cycle
                Rectangle {
                    id: modeBadge
                    visible: hasSample
                    anchors.top: parent.top; anchors.right: parent.right; anchors.margins: 6
                    width: modeText.width + 12; height: 16; radius: 8
                    color: model.mode === "loop" ? cGreen
                         : model.mode === "hold" ? cPurple
                         : model.mode === "gate" ? cOrange : "#00000070"
                    Behavior on color { ColorAnimation { duration: 100 } }
                    Text {
                        id: modeText; anchors.centerIn: parent
                        text: model.mode === "one_shot" ? "OS"
                            : model.mode === "loop"     ? "LOOP"
                            : model.mode === "hold"     ? "HOLD" : "GATE"
                        color: "white"; font.pixelSize: 8; font.bold: true
                    }
                    MouseArea {
                        anchors.fill: parent
                        onPressed: function(mouse) {
                            controller.cyclePadMode(model.padIndex)
                            mouse.accepted = true
                        }
                    }
                }

                // Main pad mouse area
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: function(mouse) {
                        // Ctrl+click → sample editor
                        if (mouse.modifiers & Qt.ControlModifier) {
                            controller.openSampleEditor(model.padIndex)
                            mouse.accepted = true
                            return
                        }
                        // Badge area → don't trigger pad
                        if (modeBadge.visible) {
                            var p = mapToItem(modeBadge, mouse.x, mouse.y)
                            if (p.x >= 0 && p.x <= modeBadge.width &&
                                p.y >= 0 && p.y <= modeBadge.height) {
                                mouse.accepted = false
                                return
                            }
                        }
                        controller.triggerPad(model.padIndex)
                        holdTimer.start()
                    }
                    onReleased: function(mouse) {
                        holdTimer.stop()
                        controller.releasePad(model.padIndex)
                    }
                    onCanceled: { holdTimer.stop(); controller.releasePad(model.padIndex) }
                }
            }
        }
    }

    // ── Bottom status bar ─────────────────────────────────────────────────
    Rectangle {
        id: bottomBar
        anchors.bottom: parent.bottom; width: parent.width; height: 28
        color: cPanel
        Row {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 10; spacing: 16
            Text { text: controller.status; color: cMuted; font.pixelSize: 11 }
        }
        Text {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            anchors.rightMargin: 10
            text: controller.latencyMs + " ms  •  " + controller.sampleRate + " Hz"
            color: cBorder; font.pixelSize: 10
        }
    }
}
