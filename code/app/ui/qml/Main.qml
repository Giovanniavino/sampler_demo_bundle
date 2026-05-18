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
    readonly property color cBg:     "#0F0F12"
    readonly property color cPanel:  "#1A1A22"
    readonly property color cCard:   "#24242E"
    readonly property color cBorder: "#2E2E3A"
    readonly property color cAccent: "#3D8EF0"
    readonly property color cText:   "#E8E8F0"
    readonly property color cMuted:  "#7878A0"
    readonly property color cGreen:  "#1ABC9C"
    readonly property color cPurple: "#9B59B6"
    readonly property color cOrange: "#E67E22"
    readonly property color cRed:    "#E74C3C"

    // ── State ────────────────────────────────────────────────────────────
    property bool showSettings:     false
    property bool showSampleEditor: false
    property int  editorPadIndex:   -1
    property string editorName:     ""
    property real editorGain:       0.0
    property real editorFadeIn:     3.0
    property real editorFadeOut:    6.0

    Connections {
        target: controller
        function onSampleEditorOpen(idx, name, gain, fi, fo) {
            editorPadIndex = idx; editorName = name
            editorGain = gain; editorFadeIn = fi; editorFadeOut = fo
            showSampleEditor = true
        }
    }

    FileDialog {
        id: fileDialog
        nameFilters: ["Audio (*.mp3 *.wav *.flac *.ogg *.m4a)"]
        onAccepted: controller.loadTrack(selectedFile.toString())
    }

    // ════════════════════════════════════════════════════════════════════
    // FIRST-LAUNCH DIALOG — blocks everything until mode is chosen
    // ════════════════════════════════════════════════════════════════════
    Rectangle {
        id: launchDialog
        visible: !controller.qualityModeChosen
        anchors.fill: parent
        color: "#000000CC"   // semi-transparent overlay
        z: 100

        Rectangle {
            anchors.centerIn: parent
            width: 560; height: 380; radius: 16
            color: cCard; border.color: cAccent; border.width: 1

            Column {
                anchors.fill: parent; anchors.margins: 36; spacing: 24

                Text {
                    text: "Choose Processing Mode"
                    color: cText; font.pixelSize: 22; font.bold: true
                    width: parent.width; horizontalAlignment: Text.AlignHCenter
                }
                Text {
                    text: "This setting is saved and won't be asked again.\nYou can change it later from Settings → Reset Mode."
                    color: cMuted; font.pixelSize: 13
                    width: parent.width; horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }

                Row {
                    spacing: 20; anchors.horizontalCenter: parent.horizontalCenter

                    // FAST card
                    Rectangle {
                        width: 210; height: 170; radius: 12
                        color: fastHover.containsMouse ? "#2A2A38" : cPanel
                        border.color: fastHover.containsMouse ? cAccent : cBorder
                        border.width: fastHover.containsMouse ? 2 : 1
                        Behavior on border.color { ColorAnimation { duration: 100 } }

                        Column {
                            anchors.centerIn: parent; spacing: 10

                            Text { text: "⚡"; font.pixelSize: 36
                                anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: "Fast"
                                color: cText; font.pixelSize: 18; font.bold: true
                                anchors.horizontalCenter: parent.horizontalCenter }
                            Text {
                                text: "Demucs standard\nNoise reduction on mix\nIdeal for quick sessions"
                                color: cMuted; font.pixelSize: 11
                                anchors.horizontalCenter: parent.horizontalCenter
                                horizontalAlignment: Text.AlignHCenter
                                lineHeight: 1.4
                            }
                        }
                        MouseArea {
                            id: fastHover; anchors.fill: parent; hoverEnabled: true
                            onClicked: controller.setQualityMode("fast")
                        }
                    }

                    // QUALITY card
                    Rectangle {
                        width: 210; height: 170; radius: 12
                        color: qualHover.containsMouse ? "#2A2A38" : cPanel
                        border.color: qualHover.containsMouse ? cGreen : cBorder
                        border.width: qualHover.containsMouse ? 2 : 1
                        Behavior on border.color { ColorAnimation { duration: 100 } }

                        Column {
                            anchors.centerIn: parent; spacing: 10

                            Text { text: "✦"; font.pixelSize: 36; color: cGreen
                                anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: "Quality"
                                color: cText; font.pixelSize: 18; font.bold: true
                                anchors.horizontalCenter: parent.horizontalCenter }
                            Text {
                                text: "Demucs fine-tuned\nNoise reduction mix + stems\nBest audio quality"
                                color: cMuted; font.pixelSize: 11
                                anchors.horizontalCenter: parent.horizontalCenter
                                horizontalAlignment: Text.AlignHCenter
                                lineHeight: 1.4
                            }
                        }
                        MouseArea {
                            id: qualHover; anchors.fill: parent; hoverEnabled: true
                            onClicked: controller.setQualityMode("quality")
                        }
                    }
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════════
    // TOP BAR
    // ════════════════════════════════════════════════════════════════════
    Rectangle {
        id: topBar
        anchors.top: parent.top; width: parent.width; height: 52
        color: cPanel

        RowLayout {
            anchors.fill: parent; anchors.margins: 10; spacing: 8

            // Mode badge
            Rectangle {
                width: 80; height: 30; radius: 15
                color: controller.qualityMode === "fast" ? "#1A2A1A" : "#1A1A30"
                border.color: controller.qualityMode === "fast" ? cGreen : cAccent
                border.width: 1
                Text {
                    anchors.centerIn: parent
                    text: controller.qualityMode === "fast" ? "⚡ Fast" : "✦ Quality"
                    color: controller.qualityMode === "fast" ? cGreen : cAccent
                    font.pixelSize: 11; font.bold: true
                }
            }

            Rectangle {
                width: 70; height: 32; radius: 6
                color: loadM.containsMouse ? cAccent : cCard; border.color: cBorder
                Text { anchors.centerIn: parent; text: "Load"
                    color: cText; font.pixelSize: 13; font.bold: true }
                MouseArea { id: loadM; anchors.fill: parent; hoverEnabled: true
                    onClicked: fileDialog.open() }
            }

            Rectangle {
                width: 70; height: 32; radius: 6
                color: stopM.containsMouse ? cRed : cCard; border.color: cBorder
                Text { anchors.centerIn: parent; text: "Stop All"
                    color: cText; font.pixelSize: 13; font.bold: true }
                MouseArea { id: stopM; anchors.fill: parent; hoverEnabled: true
                    onClicked: controller.stopAll() }
            }

            Rectangle {
                width: 32; height: 32; radius: 6
                color: showSettings ? cAccent : (setM.containsMouse ? cCard : "transparent")
                border.color: showSettings ? cAccent : cBorder
                Text { anchors.centerIn: parent; text: "⚙"; color: cText; font.pixelSize: 15 }
                MouseArea { id: setM; anchors.fill: parent; hoverEnabled: true
                    onClicked: showSettings = !showSettings }
            }

            Item { Layout.fillWidth: true }

            Column {
                spacing: 1; Layout.alignment: Qt.AlignRight
                Text { text: controller.trackName || "No track"
                    color: cText; font.pixelSize: 13; font.bold: true
                    horizontalAlignment: Text.AlignRight }
                Text { text: controller.bpm > 0 ? controller.bpm.toFixed(1) + " BPM" : ""
                    color: cMuted; font.pixelSize: 11; horizontalAlignment: Text.AlignRight }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════════
    // SETTINGS PANEL
    // ════════════════════════════════════════════════════════════════════
    Rectangle {
        id: settingsPanel
        anchors.top: topBar.bottom
        width: parent.width
        height: parent.height - topBar.height - bottomBar.height
        color: cBg; visible: showSettings; z: 10

        // ---- helpers
        component PresetRow: Row {
            property string label: ""
            property var presets: []
            property string current: ""
            property bool showCustom: current === "Custom"
            signal chosen(string name)

            spacing: 8; height: 34

            Text { text: label; color: cMuted; font.pixelSize: 11; font.bold: true
                width: 90; verticalAlignment: Text.AlignVCenter; height: parent.height }

            Repeater {
                model: parent.presets
                Rectangle {
                    property bool sel: parent.parent.current === modelData
                    width: 84; height: 28; radius: 14
                    color: sel ? cAccent : (hov.containsMouse ? "#30405080" : cCard)
                    border.color: sel ? cAccent : cBorder
                    Behavior on color { ColorAnimation { duration: 80 } }
                    Text { anchors.centerIn: parent; text: modelData
                        color: sel ? "white" : cText; font.pixelSize: 12; font.bold: sel }
                    MouseArea { id: hov; anchors.fill: parent; hoverEnabled: true
                        onClicked: parent.parent.parent.chosen(modelData) }
                }
            }
        }

        TabBar {
            id: sTabBar; anchors.top: parent.top; width: parent.width; height: 36
            background: Rectangle { color: cPanel }
            Repeater {
                model: ["Slicing", "Pad Layout", "Playback", "Info"]
                TabButton {
                    text: modelData; width: 120
                    contentItem: Text { text: parent.text; color: cText; font.pixelSize: 12
                        font.bold: sTabBar.currentIndex === index
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    background: Rectangle {
                        color: sTabBar.currentIndex === index ? cCard : cPanel
                        Rectangle { height: 2; color: cAccent; anchors.bottom: parent.bottom
                            width: parent.width; visible: sTabBar.currentIndex === index }
                    }
                }
            }
        }

        StackLayout {
            currentIndex: sTabBar.currentIndex
            anchors.top: sTabBar.bottom; anchors.bottom: applyBar.top
            anchors.left: parent.left; anchors.right: parent.right

            // ── TAB 0: Slicing (preset-based) ─────────────────────────
            ScrollView {
                clip: true
                Column {
                    width: parent.width; spacing: 0

                    // ---- VOCAL PHRASES ----
                    Rectangle {
                        width: parent.width; height: 1; color: cBorder }
                    Rectangle {
                        width: parent.width; height: 44; color: cPanel
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            text: "Vocal Phrases"; color: cText
                            font.pixelSize: 14; font.bold: true }
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.right: parent.right; anchors.rightMargin: 16
                            text: "Short = single words/lines  •  Long = full verses or choruses"
                            color: cMuted; font.pixelSize: 11 }
                    }
                    Rectangle { width: parent.width; color: cCard; height: 56
                        PresetRow {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            label: "Length"
                            presets: ["Short", "Medium", "Long", "Custom"]
                            current: controller.vocalPreset
                            onChosen: function(name) { controller.applyVocalPreset(name) }
                        }
                    }
                    // Dynamic explanation
                    Rectangle { width: parent.width; height: 26; color: cCard
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 130
                            color: cMuted; font.pixelSize: 10; font.italic: true
                            text: {
                                if (controller.vocalPreset === "Short")  return "≈0.8–5s phrases. Good for chops, ad-libs, single words."
                                if (controller.vocalPreset === "Medium") return "≈1.5–10s phrases. Standard lines (default)."
                                if (controller.vocalPreset === "Long")   return "≈3–15s phrases. Full verses or chorus lines."
                                return "Set min/max length yourself below."
                            }
                        }
                    }
                    // Custom fields — only visible when preset == Custom
                    Rectangle {
                        width: parent.width
                        height: controller.vocalPreset === "Custom" ? 130 : 0
                        clip: true; color: cCard
                        Behavior on height { NumberAnimation { duration: 180 } }
                        GridLayout {
                            anchors.left: parent.left; anchors.leftMargin: 106
                            anchors.top: parent.top; anchors.topMargin: 8
                            columns: 4; columnSpacing: 12; rowSpacing: 8

                            Text { text: "Min phrase (ms)"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: cvMinMs; from: 200; to: 10000; stepSize: 100
                                value: controller.minVocalPhraseMs
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Max phrase (ms)"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: cvMaxMs; from: 1000; to: 30000; stepSize: 500
                                value: controller.maxVocalPhraseMs
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Min silence gap (ms)"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: cvGap; from: 100; to: 2000; stepSize: 50
                                value: controller.vocalPhraseMinGapMs
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Max phrases"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: cvMaxPhr; from: 1; to: 16; value: controller.maxVocalPhrases
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Chop length (ms)"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: cvChopMs; from: 200; to: 3000; stepSize: 100
                                value: controller.vocalChopLengthMs
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Max chops"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: cvMaxChops; from: 1; to: 16; value: controller.maxVocalChops
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                        }
                    }

                    // ---- DRUM HITS ----
                    Rectangle { width: parent.width; height: 1; color: cBorder }
                    Rectangle {
                        width: parent.width; height: 44; color: cPanel
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            text: "Drum Hits"; color: cText; font.pixelSize: 14; font.bold: true }
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.right: parent.right; anchors.rightMargin: 16
                            text: "Punchy = short kicks/snares  •  Full = longer hits with tail"
                            color: cMuted; font.pixelSize: 11 }
                    }
                    Rectangle { width: parent.width; color: cCard; height: 56
                        PresetRow {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            label: "Style"
                            presets: ["Punchy", "Standard", "Full", "Custom"]
                            current: controller.drumPreset
                            onChosen: function(name) { controller.applyDrumPreset(name) }
                        }
                    }
                    Rectangle { width: parent.width; height: 26; color: cCard
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 130
                            color: cMuted; font.pixelSize: 10; font.italic: true
                            text: {
                                if (controller.drumPreset === "Punchy")   return "200ms hits, dense. Best for trap/footwork-style pads."
                                if (controller.drumPreset === "Standard") return "400ms hits. Balanced default."
                                if (controller.drumPreset === "Full")     return "700ms hits with full tail. Best for cinematic/breakbeats."
                                return "Set hit length and density below."
                            }
                        }
                    }
                    Rectangle {
                        width: parent.width
                        height: controller.drumPreset === "Custom" ? 80 : 0
                        clip: true; color: cCard
                        Behavior on height { NumberAnimation { duration: 180 } }
                        GridLayout {
                            anchors.left: parent.left; anchors.leftMargin: 106
                            anchors.top: parent.top; anchors.topMargin: 8
                            columns: 4; columnSpacing: 12; rowSpacing: 8
                            Text { text: "Hit length (ms)"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: cdHitMs; from: 50; to: 2000; stepSize: 50
                                value: controller.drumHitLengthMs
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Max hits"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: cdMaxHits; from: 1; to: 32; value: controller.maxDrumHits
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                        }
                    }

                    // ---- LOOPS ----
                    Rectangle { width: parent.width; height: 1; color: cBorder }
                    Rectangle {
                        width: parent.width; height: 44; color: cPanel
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            text: "Loops"; color: cText; font.pixelSize: 14; font.bold: true }
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.right: parent.right; anchors.rightMargin: 16
                            text: "Loop length and how many are extracted"
                            color: cMuted; font.pixelSize: 11 }
                    }
                    Rectangle { width: parent.width; color: cCard; height: 56
                        PresetRow {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            label: "Length"
                            presets: ["Tight", "Standard", "Spacious", "Custom"]
                            current: controller.loopPreset
                            onChosen: function(name) { controller.applyLoopPreset(name) }
                        }
                    }
                    Rectangle { width: parent.width; height: 26; color: cCard
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 130
                            color: cMuted; font.pixelSize: 10; font.italic: true
                            text: {
                                if (controller.loopPreset === "Tight")    return "1-bar loops. Quick repeats, more variations."
                                if (controller.loopPreset === "Standard") return "2-bar drum/bass, 4-bar melody. Default."
                                if (controller.loopPreset === "Spacious") return "4-bar drum/bass, 8-bar melody. Longer breathing room."
                                return "Set bars per loop type below."
                            }
                        }
                    }
                    Rectangle {
                        width: parent.width
                        height: controller.loopPreset === "Custom" ? 80 : 0
                        clip: true; color: cCard
                        Behavior on height { NumberAnimation { duration: 180 } }
                        GridLayout {
                            anchors.left: parent.left; anchors.leftMargin: 106
                            anchors.top: parent.top; anchors.topMargin: 8
                            columns: 4; columnSpacing: 12; rowSpacing: 8
                            Text { text: "Loops per stem"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: clN; from: 1; to: 8; value: controller.nLoopsPerStem
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Drum loop bars"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: clDrum; from: 1; to: 8; value: controller.drumLoopBars
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Bass loop bars"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: clBass; from: 1; to: 8; value: controller.bassLoopBars
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                            Text { text: "Melody bars"; color: cMuted; font.pixelSize: 11 }
                            SpinBox { id: clMel; from: 1; to: 8; value: controller.melodyPhraseBars
                                contentItem: TextInput { text: parent.textFromValue(parent.value)
                                    color: cText; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
                                background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 } }
                        }
                    }
                }
            }

            // ── TAB 1: Pad Layout ─────────────────────────────────────
            Item {
                Column {
                    anchors.centerIn: parent
                    spacing: 20

                    // Header explanation
                    Column {
                        spacing: 4; width: 600
                        Text { text: "Pad Layout"; color: cText
                            font.pixelSize: 16; font.bold: true
                            anchors.horizontalCenter: parent.horizontalCenter }
                        Text { text: "Choose how many pads to assign to each category. " +
                                       "The total must not exceed the grid size."
                            color: cMuted; font.pixelSize: 11
                            anchors.horizontalCenter: parent.horizontalCenter
                            horizontalAlignment: Text.AlignHCenter }
                        Text { text: "Tip: more pads of one category = more variety. " +
                                       "Set categories to 0 to skip them entirely."
                            color: cMuted; font.pixelSize: 10
                            anchors.horizontalCenter: parent.horizontalCenter
                            horizontalAlignment: Text.AlignHCenter
                            font.italic: true }
                    }

                    GridLayout {
                        anchors.horizontalCenter: parent.horizontalCenter
                        columns: 4; columnSpacing: 20; rowSpacing: 16

                    Text { text: "Category";    color: cMuted; font.pixelSize: 11; font.bold: true }
                    Text { text: "Pads";         color: cMuted; font.pixelSize: 11; font.bold: true }
                    Text { text: "Category";    color: cMuted; font.pixelSize: 11; font.bold: true }
                    Text { text: "Pads";         color: cMuted; font.pixelSize: 11; font.bold: true }

                    Text { text: "Drum Hits";    color: "#E74C3C"; font.pixelSize: 13 }
                    SpinBox { id: plDH; from: 0; to: 16; value: controller.padsDrumHit
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }
                    Text { text: "Drum Loops";   color: "#C0392B"; font.pixelSize: 13 }
                    SpinBox { id: plDL; from: 0; to: 16; value: controller.padsDrumLoop
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }
                    Text { text: "Vocal Chops";  color: "#F1C40F"; font.pixelSize: 13 }
                    SpinBox { id: plVC; from: 0; to: 16; value: controller.padsVocalChop
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }
                    Text { text: "Vocal Phrases"; color: "#F39C12"; font.pixelSize: 13 }
                    SpinBox { id: plVP; from: 0; to: 16; value: controller.padsVocalPhrase
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }
                    Text { text: "Melody";        color: "#3498DB"; font.pixelSize: 13 }
                    SpinBox { id: plMel; from: 0; to: 16; value: controller.padsMelody
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }
                    Text { text: "Bass Loops";    color: "#9B59B6"; font.pixelSize: 13 }
                    SpinBox { id: plBL; from: 0; to: 16; value: controller.padsBassLoop
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Item { Layout.columnSpan: 2 }
                    Text { text: "Grid size";    color: cText; font.pixelSize: 13 }
                    SpinBox { id: plGS; from: 4; to: 32; stepSize: 4; value: controller.gridSize
                        contentItem: TextInput { text: parent.textFromValue(parent.value)
                            color: cText; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
                        background: Rectangle { color: cCard; border.color: cBorder; radius: 4 } }

                    Text {
                        Layout.columnSpan: 4
                        property int tot: plDH.value+plDL.value+plVC.value+plVP.value+plMel.value+plBL.value
                        text: "Total: " + tot + " / " + plGS.value + (tot > plGS.value ? "  ⚠ exceeds grid" : "  ✓")
                        color: (plDH.value+plDL.value+plVC.value+plVP.value+plMel.value+plBL.value) > plGS.value ? cOrange : cGreen
                        font.pixelSize: 12
                    }
                    }
                }
            }

            // ── TAB 2: Playback ───────────────────────────────────────
            ScrollView {
                clip: true
                Column {
                    width: parent.width; spacing: 0

                    // --- helper component: labeled row with description ---
                    component LabeledRow: Rectangle {
                        property string title: ""
                        property string desc: ""
                        default property alias content: ctrl.children
                        width: parent.width; height: 60; color: cCard

                        Column {
                            anchors.left: parent.left; anchors.leftMargin: 20
                            anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Text { text: title; color: cText; font.pixelSize: 13; font.bold: true }
                            Text { text: desc; color: cMuted; font.pixelSize: 10
                                width: settingsPanel.width * 0.45; wrapMode: Text.WordWrap }
                        }
                        Item { id: ctrl
                            anchors.right: parent.right; anchors.rightMargin: 20
                            anchors.verticalCenter: parent.verticalCenter
                            width: 200; height: 32 }
                    }

                    component SegSelector: Row {
                        property var options: []
                        property string current: ""
                        signal chosen(string name)
                        spacing: 4
                        Repeater {
                            model: parent.options
                            Rectangle {
                                width: 60; height: 28; radius: 6
                                property bool sel: parent.parent.current === modelData
                                color: sel ? cAccent : cCard
                                border.color: sel ? cAccent : cBorder
                                Behavior on color { ColorAnimation { duration: 80 } }
                                Text { anchors.centerIn: parent; text: modelData
                                    color: sel ? "white" : cText
                                    font.pixelSize: 11; font.bold: sel
                                    font.capitalization: Font.Capitalize }
                                MouseArea { anchors.fill: parent
                                    onClicked: parent.parent.parent.chosen(modelData) }
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: cBorder }
                    Rectangle { width: parent.width; height: 34; color: cPanel
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            text: "AUDIO ENGINE"; color: cMuted
                            font.pixelSize: 10; font.bold: true } }

                    LabeledRow {
                        title: "Buffer size"
                        desc: "Smaller = lower latency but higher CPU. 512 is safe."
                        ComboBox { id: cbBS; model: [128, 256, 512, 1024]
                            anchors.fill: parent
                            currentIndex: { var v=controller.blockSize
                                for (var i=0;i<model.length;i++) if (model[i]===v) return i
                                return 2 }
                            background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 }
                            contentItem: Text { text: cbBS.displayText + " samples"
                                color: cText; font.pixelSize: 12; leftPadding: 8
                                verticalAlignment: Text.AlignVCenter } }
                    }

                    LabeledRow {
                        title: "Sample rate"
                        desc: "Output sample rate. 44.1 kHz matches most music files."
                        ComboBox { id: cbSR; model: [44100, 48000]
                            anchors.fill: parent
                            currentIndex: controller.sampleRate === 48000 ? 1 : 0
                            background: Rectangle { color: cPanel; border.color: cBorder; radius: 4 }
                            contentItem: Text { text: cbSR.displayText + " Hz"
                                color: cText; font.pixelSize: 12; leftPadding: 8
                                verticalAlignment: Text.AlignVCenter } }
                    }

                    LabeledRow {
                        title: "Estimated latency"
                        desc: "Time from pressing a pad to hearing the sound."
                        Text { anchors.fill: parent
                            text: (cbBS.currentValue / cbSR.currentValue * 1000).toFixed(1) + " ms"
                            color: cAccent; font.pixelSize: 14; font.bold: true
                            verticalAlignment: Text.AlignVCenter }
                    }

                    // --- NOISE REDUCTION section ---
                    Rectangle { width: parent.width; height: 1; color: cBorder }
                    Rectangle { width: parent.width; height: 34; color: cPanel
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            text: "NOISE REDUCTION"; color: cMuted
                            font.pixelSize: 10; font.bold: true } }

                    LabeledRow {
                        title: "Pre-separation"
                        desc: "Cleans the whole song before splitting into stems. " +
                              "Light is usually enough. Strong may dull the audio."
                        property string cur: controller.nrLevelPre
                        SegSelector { id: segPre; anchors.fill: parent
                            options: ["off", "light", "strong"]
                            current: parent.cur
                            onChosen: function(name) { parent.cur = name } }
                    }

                    LabeledRow {
                        title: "Post-separation (per stem)"
                        desc: "Cleans each stem individually after splitting. " +
                              "Most useful for cleaning bleed in vocal stem. Off by default."
                        property string cur: controller.nrLevelPost
                        SegSelector { id: segPost; anchors.fill: parent
                            options: ["off", "light", "strong"]
                            current: parent.cur
                            onChosen: function(name) { parent.cur = name } }
                    }

                    // --- BEHAVIOR section ---
                    Rectangle { width: parent.width; height: 1; color: cBorder }
                    Rectangle { width: parent.width; height: 34; color: cPanel
                        Text { anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 16
                            text: "BEHAVIOR"; color: cMuted
                            font.pixelSize: 10; font.bold: true } }

                    LabeledRow {
                        title: "Press-and-hold loop"
                        desc: "If you keep a pad held past the sample's end, it loops " +
                              "until you release. EXPERIMENTAL — disable if pads sound doubled."
                        Switch { id: swHL; checked: controller.pressHoldLoop
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            indicator: Rectangle { width: 44; height: 22; radius: 11
                                color: parent.checked ? cAccent : cCard; border.color: cBorder
                                Rectangle { x: parent.parent.checked ? 24 : 2; y: 2
                                    width: 18; height: 18; radius: 9; color: cText
                                    Behavior on x { NumberAnimation { duration: 120 } } } } }
                    }

                    LabeledRow {
                        title: "Auto-normalize stems"
                        desc: "Levels stems so quiet stems are louder. Useful if vocal " +
                              "stem is too soft. May raise the noise floor."
                        Switch { id: swNorm; checked: controller.autoNormalizeStems
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            indicator: Rectangle { width: 44; height: 22; radius: 11
                                color: parent.checked ? cAccent : cCard; border.color: cBorder
                                Rectangle { x: parent.parent.checked ? 24 : 2; y: 2
                                    width: 18; height: 18; radius: 9; color: cText
                                    Behavior on x { NumberAnimation { duration: 120 } } } } }
                    }

                    LabeledRow {
                        title: "Auto-choke drums"
                        desc: "Drum hits on the same row cut each other off when triggered " +
                              "(like a real drum kit's hi-hat)."
                        Switch { id: swChk; checked: controller.autoChokeDrums
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            indicator: Rectangle { width: 44; height: 22; radius: 11
                                color: parent.checked ? cAccent : cCard; border.color: cBorder
                                Rectangle { x: parent.parent.checked ? 24 : 2; y: 2
                                    width: 18; height: 18; radius: 9; color: cText
                                    Behavior on x { NumberAnimation { duration: 120 } } } } }
                    }
                }
            }

            // ── TAB 3: Info ───────────────────────────────────────────
            Item {
                Column {
                    anchors.centerIn: parent; spacing: 20

                    Text {
                        text: "Current mode: " +
                              (controller.qualityMode === "fast" ? "⚡ Fast" : "✦ Quality")
                        color: controller.qualityMode === "fast" ? cGreen : cAccent
                        font.pixelSize: 16; font.bold: true
                        anchors.horizontalCenter: parent.horizontalCenter
                    }

                    Text {
                        text: controller.qualityMode === "fast"
                            ? "Demucs htdemucs  •  Noise reduction on mix only"
                            : "Demucs htdemucs_ft  •  Noise reduction on mix + each stem"
                        color: cMuted; font.pixelSize: 12
                        anchors.horizontalCenter: parent.horizontalCenter
                    }

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 180; height: 36; radius: 8
                        color: resetM.containsMouse ? cRed : cCard
                        border.color: cRed; border.width: 1
                        Text { anchors.centerIn: parent; text: "Reset Mode Choice"
                            color: cRed; font.pixelSize: 13; font.bold: true }
                        MouseArea { id: resetM; anchors.fill: parent; hoverEnabled: true
                            onClicked: { controller.resetQualityMode(); showSettings = false } }
                    }
                }
            }
        }

        // ---- Apply / Cancel / Re-slice row
        Rectangle {
            id: applyBar
            anchors.bottom: parent.bottom; width: parent.width; height: 46; color: cPanel
            RowLayout {
                anchors.fill: parent; anchors.margins: 10; spacing: 10
                Item { Layout.fillWidth: true }

                // Re-slice button (only when project loaded)
                Rectangle {
                    visible: controller.trackName !== ""
                    width: 110; height: 32; radius: 6
                    color: rslM.containsMouse ? cGreen : "transparent"
                    border.color: cGreen; border.width: 1
                    Text { anchors.centerIn: parent; text: "↻ Re-slice"
                        color: cGreen; font.pixelSize: 12; font.bold: true }
                    MouseArea { id: rslM; anchors.fill: parent; hoverEnabled: true
                        onClicked: { controller.reslice(); showSettings = false } }
                }

                Rectangle {
                    width: 80; height: 32; radius: 6; color: "transparent"; border.color: cBorder
                    Text { anchors.centerIn: parent; text: "Cancel"; color: cMuted; font.pixelSize: 13 }
                    MouseArea { anchors.fill: parent; onClicked: showSettings = false }
                }

                Rectangle {
                    width: 80; height: 32; radius: 6; color: cAccent
                    Text { anchors.centerIn: parent; text: "Apply"; color: "white"
                        font.pixelSize: 13; font.bold: true }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            var t = sTabBar.currentIndex
                            if (t === 0) {
                                if (controller.vocalPreset === "Custom")
                                    controller.applyVocalCustom(cvMinMs.value, cvMaxMs.value,
                                        cvGap.value, cvMaxPhr.value, cvChopMs.value, cvMaxChops.value)
                                if (controller.drumPreset === "Custom")
                                    controller.applyDrumCustom(cdHitMs.value, cdMaxHits.value, 1.0)
                                if (controller.loopPreset === "Custom")
                                    controller.applyLoopCustom(clN.value, clDrum.value, clBass.value, clMel.value)
                            } else if (t === 1) {
                                controller.applyPadLayout(plDH.value, plDL.value, plVC.value,
                                    plVP.value, plMel.value, plBL.value, plGS.value)
                            } else if (t === 2) {
                                controller.applyPlaybackSettings(cbBS.currentValue,
                                    cbSR.currentValue, swHL.checked, swNorm.checked, swChk.checked,
                                    segPre.current, segPost.current)
                            }
                            showSettings = false
                        }
                    }
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════════
    // SAMPLE EDITOR
    // ════════════════════════════════════════════════════════════════════
    Rectangle {
        visible: showSampleEditor; z: 20
        anchors.fill: parent; color: "#000000AA"
        Rectangle {
            anchors.centerIn: parent; width: 420; height: 270; radius: 12
            color: cCard; border.color: cAccent; border.width: 1
            Column { anchors.fill: parent; anchors.margins: 22; spacing: 16
                Text { text: editorName; color: cText; font.pixelSize: 14; font.bold: true
                    elide: Text.ElideRight; width: parent.width }

                component FaderRow: Row {
                    property string label: ""; property color knobColor: cAccent
                    property alias value: sl.value; property real from: -24; property real to: 12
                    property real stepSize: 0.5
                    property string unit: "dB"
                    spacing: 10; height: 28
                    Text { text: label; color: cMuted; font.pixelSize: 12; width: 72
                        verticalAlignment: Text.AlignVCenter; height: parent.height }
                    Slider { id: sl; from: parent.from; to: parent.to; stepSize: parent.stepSize
                        width: 230
                        background: Rectangle { x: sl.leftPadding
                            y: sl.topPadding + sl.availableHeight/2 - 2
                            width: sl.availableWidth; height: 4; radius: 2; color: cBorder
                            Rectangle { width: sl.visualPosition*parent.width; height: parent.height
                                color: parent.parent.parent.knobColor; radius: 2 } }
                        handle: Rectangle {
                            x: sl.leftPadding + sl.visualPosition*sl.availableWidth - 8
                            y: sl.topPadding + sl.availableHeight/2 - 8
                            width: 16; height: 16; radius: 8
                            color: parent.parent.knobColor; border.color: "white"; border.width: 1 } }
                    Text { text: sl.value.toFixed(unit==="dB"?1:0) + " " + unit
                        color: parent.knobColor; font.pixelSize: 12; width: 52 }
                }

                FaderRow { label: "Gain"; from: -24; to: 12; stepSize: 0.5
                    unit: "dB"; knobColor: cAccent; value: editorGain
                    onValueChanged: editorGain = value }
                FaderRow { label: "Fade In"; from: 0; to: 500; stepSize: 1
                    unit: "ms"; knobColor: cGreen; value: editorFadeIn
                    onValueChanged: editorFadeIn = value }
                FaderRow { label: "Fade Out"; from: 0; to: 500; stepSize: 1
                    unit: "ms"; knobColor: cOrange; value: editorFadeOut
                    onValueChanged: editorFadeOut = value }

                Row { spacing: 10; anchors.right: parent.right
                    Rectangle { width: 80; height: 30; radius: 6; color: cBorder
                        Text { anchors.centerIn: parent; text: "Cancel"; color: cMuted; font.pixelSize: 12 }
                        MouseArea { anchors.fill: parent; onClicked: showSampleEditor = false } }
                    Rectangle { width: 80; height: 30; radius: 6; color: cAccent
                        Text { anchors.centerIn: parent; text: "Apply"; color: "white"
                            font.pixelSize: 12; font.bold: true }
                        MouseArea { anchors.fill: parent; onClicked: {
                            controller.applySampleEdit(editorPadIndex, editorGain, editorFadeIn, editorFadeOut)
                            showSampleEditor = false } } }
                }
            }
        }
    }

    // ════════════════════════════════════════════════════════════════════
    // PAD GRID
    // ════════════════════════════════════════════════════════════════════
    GridView {
        id: padGrid
        anchors.top: topBar.bottom; anchors.bottom: bottomBar.top
        anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: 14; visible: !showSettings; interactive: false

        property int cols: Math.max(1, Math.round(Math.sqrt(controller.gridSize)))
        cellWidth: width / cols; cellHeight: height / cols
        model: controller.padModel

        delegate: Item {
            width: padGrid.cellWidth; height: padGrid.cellHeight

            Timer { id: holdT; interval: 80; repeat: true; running: false
                onTriggered: controller.padHoldTick(model.padIndex) }

            Rectangle {
                anchors.fill: parent; anchors.margins: 5; radius: 8
                color: hasSample ? model.color : "#1C1C24"
                opacity: active ? 1.0 : (hasSample ? 0.82 : 0.45)
                border.color: active ? "#FFFFFF" : "#00000040"; border.width: active ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 70 } }

                // Pad number
                Text { anchors.top: parent.top; anchors.left: parent.left; anchors.margins: 7
                    text: (model.padIndex+1).toString().padStart(2,"0")
                    color: "#00000055"; font.pixelSize: 11; font.bold: true }

                // Label
                Text { anchors.bottom: parent.bottom; anchors.left: parent.left
                    anchors.right: parent.right; anchors.margins: 7
                    text: model.label; color: "#FFFFFF"; font.pixelSize: 10
                    font.bold: true; elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter }

                // Mode badge — tap to cycle
                Rectangle {
                    id: mBadge; visible: hasSample
                    anchors.top: parent.top; anchors.right: parent.right; anchors.margins: 6
                    width: mT.width + 12; height: 16; radius: 8
                    color: model.mode==="loop" ? cGreen : model.mode==="hold" ? cPurple
                         : model.mode==="gate" ? cOrange : "#00000070"
                    Behavior on color { ColorAnimation { duration: 100 } }
                    Text { id: mT; anchors.centerIn: parent
                        text: model.mode==="one_shot" ? "OS" : model.mode==="loop" ? "LOOP"
                            : model.mode==="hold" ? "HOLD" : "GATE"
                        color: "white"; font.pixelSize: 8; font.bold: true }
                    MouseArea { anchors.fill: parent
                        onPressed: function(m) { controller.cyclePadMode(model.padIndex); m.accepted=true } }
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    onPressed: function(mouse) {
                        if (mouse.modifiers & Qt.ControlModifier) {
                            controller.openSampleEditor(model.padIndex); return }
                        if (mBadge.visible) {
                            var p = mapToItem(mBadge, mouse.x, mouse.y)
                            if (p.x>=0 && p.x<=mBadge.width && p.y>=0 && p.y<=mBadge.height) {
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

    // ════════════════════════════════════════════════════════════════════
    // BOTTOM BAR
    // ════════════════════════════════════════════════════════════════════
    Rectangle {
        id: bottomBar; anchors.bottom: parent.bottom; width: parent.width; height: 26; color: cPanel
        Text { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 10; text: controller.status; color: cMuted; font.pixelSize: 11 }
        Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            anchors.rightMargin: 10
            text: controller.latencyMs + " ms  •  " + controller.sampleRate + " Hz"
            color: cBorder; font.pixelSize: 10 }
    }
}
