# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for SamplerDemo - macOS
# Run from the `code/` directory:
#   pyinstaller sampler_mac.spec

import sys
from pathlib import Path

block_cipher = None

# ── Paths ────────────────────────────────────────────────────────────────────
SRC_ROOT = Path(".").resolve()          # code/
APP_PKG  = SRC_ROOT / "app"
DATA_DIR = SRC_ROOT / "data"
QML_FILE = APP_PKG  / "ui" / "qml" / "Main.qml"
ICON     = SRC_ROOT / "resources" / "AppIcon.icns"

# ── Hidden imports ────────────────────────────────────────────────────────────
# Libraries that PyInstaller misses with static analysis
hidden = [
    # PyQt6 / Qt Quick
    "PyQt6.QtQuick",
    "PyQt6.QtQml",
    "PyQt6.QtNetwork",
    "PyQt6.sip",

    # Audio I/O
    "sounddevice",
    "soundfile",
    "_sounddevice_data",

    # MIDI / OSC
    "rtmidi",
    "mido",
    "mido.backends.rtmidi",
    "python_osc",
    "pythonosc",

    # Audio analysis
    "librosa",
    "librosa.core",
    "librosa.feature",
    "librosa.effects",
    "noisereduce",
    "scipy.signal",
    "scipy.fft",
    "scipy._lib.messagestream",

    # Numeric
    "numpy",
    "numpy.core._multiarray_umath",
    "numpy.core._multiarray_tests",

    # App internals
    "app",
    "app.core",
    "app.audio",
    "app.audio.analysis",
    "app.audio.dsp",
    "app.audio.playback",
    "app.audio.separation",
    "app.audio.slicing",
    "app.hardware",
    "app.hardware.midi",
    "app.hardware.osc",
    "app.project",
    "app.services",
    "app.ui",
    "app.ui.controllers",
]

# ── Data files ────────────────────────────────────────────────────────────────
datas = [
    # QML UI
    (str(QML_FILE), "app/ui/qml"),

    # App data (settings, cache dir, projects dir)
    (str(DATA_DIR / "settings.json"), "data"),
    (str(DATA_DIR / "cache"),         "data/cache"),
    (str(DATA_DIR / "projects"),      "data/projects"),
    (str(DATA_DIR / "models"),        "data/models"),
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ["app/main.py"],
    pathex=[str(SRC_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy AI deps from the base build (optional)
        # Remove these lines if you want AI/demucs bundled
        "torch",
        "torchaudio",
        "demucs",
        "pyrubberband",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Executable ────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SamplerDemo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No terminal window
    codesign_identity=None,
    entitlements_file=None,
)

# ── .app Bundle ───────────────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SamplerDemo",
)

app = BUNDLE(
    coll,
    name="SamplerDemo.app",
    icon=str(ICON),
    bundle_identifier="com.giovanniavino.samplerdemo",
    version="1.0.0",
    info_plist={
        "CFBundleName":             "SamplerDemo",
        "CFBundleDisplayName":      "Sampler Demo",
        "CFBundleVersion":          "1.0.0",
        "CFBundleShortVersionString": "1.0",
        "NSHighResolutionCapable":  True,
        "NSMicrophoneUsageDescription": "SamplerDemo needs microphone access for audio input.",
        "NSDocumentsFolderUsageDescription": "SamplerDemo needs access to open audio files.",
        "LSMinimumSystemVersion":   "12.0",   # macOS Monterey+
    },
)
