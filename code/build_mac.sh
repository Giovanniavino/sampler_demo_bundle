#!/usr/bin/env bash
# =============================================================================
#  build_mac.sh  —  Builds SamplerDemo.app + SamplerDemo.dmg for macOS
#
#  Usage:
#    cd sampler_demo_bundle/code
#    chmod +x build_mac.sh
#    ./build_mac.sh
#
#  Options:
#    --with-ai     Include torch/demucs in the bundle (very large, ~3 GB)
#    --sign        Code-sign the .app (requires Apple Developer account)
#    --dmg         Also create a distributable .dmg after build
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
APP_NAME="SamplerDemo"
BUNDLE_ID="com.giovanniavino.samplerdemo"
SIGN_IDENTITY=""          # Set to your Apple Developer ID if using --sign
                          # e.g. "Developer ID Application: Your Name (TEAMID)"
WITH_AI=false
DO_SIGN=false
MAKE_DMG=false

# ── Parse flags ───────────────────────────────────────────────────────────────
for arg in "$@"; do
    case $arg in
        --with-ai) WITH_AI=true ;;
        --sign)    DO_SIGN=true ;;
        --dmg)     MAKE_DMG=true ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

# ── Checks ────────────────────────────────────────────────────────────────────
echo "🔍 Checking environment..."

if [[ "$(uname)" != "Darwin" ]]; then
    echo "❌  This script must be run on macOS."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "❌  python3 not found. Install via: brew install python"
    exit 1
fi

PYTHON=$(command -v python3)
echo "✅  Python: $($PYTHON --version)"

# ── Virtual environment ───────────────────────────────────────────────────────
VENV_DIR=".venv_mac"

if [[ ! -d "$VENV_DIR" ]]; then
    echo ""
    echo "📦 Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
echo "✅  Venv: $VENV_DIR"

# ── Install dependencies ──────────────────────────────────────────────────────
echo ""
echo "📥 Installing dependencies..."
pip install --upgrade pip --quiet

pip install pyinstaller \
    PyQt6>=6.6 \
    numpy scipy soundfile sounddevice \
    mido python-rtmidi python-osc \
    librosa noisereduce \
    --quiet

if $WITH_AI; then
    echo "🤖 Installing AI dependencies (torch + demucs)..."
    echo "   ⚠️  This may take a while and uses ~3 GB of disk."
    pip install torch torchaudio demucs pyrubberband --quiet
fi

echo "✅  Dependencies installed"

# ── Patch spec for AI build ───────────────────────────────────────────────────
SPEC_FILE="sampler_mac.spec"

if $WITH_AI; then
    echo "🔧 Patching spec for AI build (removing torch excludes)..."
    # Remove the excludes block for torch/demucs
    sed -i '' \
        -e 's/        "torch",/        # "torch",/' \
        -e 's/        "torchaudio",/        # "torchaudio",/' \
        -e 's/        "demucs",/        # "demucs",/' \
        -e 's/        "pyrubberband",/        # "pyrubberband",/' \
        "$SPEC_FILE"
fi

# ── Build ─────────────────────────────────────────────────────────────────────
echo ""
echo "🔨 Building ${APP_NAME}.app..."
echo "   (This takes 2–5 minutes)"

pyinstaller "$SPEC_FILE" \
    --noconfirm \
    --clean \
    --log-level WARN

echo ""
if [[ -d "dist/${APP_NAME}.app" ]]; then
    echo "✅  Build successful: dist/${APP_NAME}.app"
else
    echo "❌  Build failed — check output above"
    exit 1
fi

# ── Code signing ──────────────────────────────────────────────────────────────
if $DO_SIGN; then
    if [[ -z "$SIGN_IDENTITY" ]]; then
        echo "⚠️  --sign specified but SIGN_IDENTITY is empty. Skipping."
    else
        echo ""
        echo "✍️  Code-signing app..."
        codesign --deep --force --verify --verbose \
            --sign "$SIGN_IDENTITY" \
            --entitlements entitlements.plist \
            "dist/${APP_NAME}.app"
        echo "✅  Signed"
    fi
fi

# ── DMG creation ──────────────────────────────────────────────────────────────
if $MAKE_DMG; then
    echo ""
    echo "💿 Creating DMG..."
    ./create_dmg.sh
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo "  🎉 Done!  →  dist/${APP_NAME}.app"
echo ""
echo "  To run: open dist/${APP_NAME}.app"
echo "  To install: drag to /Applications"
if $MAKE_DMG; then
    echo "  DMG: dist/${APP_NAME}.dmg"
fi
echo "═══════════════════════════════════════════"
