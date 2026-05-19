# Sampler

A professional audio sampling and slicing workstation with real-time pad control, AI-powered source separation, and modular hardware support.

**Status:** v4 (stable) | **License:** MIT | **Python:** 3.10+

---

## Features

### 🎛️ Core Sampler
- **16–36 dynamic pads** with one-shot and loop modes
- **Live waveform editor** — drag markers, zoom (pinch/scroll), snap-to-beat
- **Sample parameters** — gain, pitch, time stretch, reverse, fade in/out, with instant reset
- **4 drum stems** — drums, vocals, bass, melody (via AI separation)

### 🎯 Intelligent Slicing
- **AI-powered separation** — Demucs (fast/quality mode, user-selectable)
- **Preset-based slicing** — vocal phrases, drum hits, melodic loops, basslines
- **Custom parameters** — adjust min/max lengths, gaps, max count per category
- **Auto-assignment** — pad layout configurable (4–6 columns, scrollable grid)

### 🎚️ Playback & Effects
- **Multi-bank switching** — Bank A/B/C, each with 16–36 pads
- **Press-hold loop** — retrigger sample when held after playback ends
- **Auto-choke drums** — new hit cuts the previous one
- **Noise reduction** — light/strong pre and post-separation
- **Sample rate** — 22 kHz to 96 kHz; block size configurable

### ⚙️ Settings Panel
- **4 organized tabs** — Slicing / Pad Layout / Playback / Info
- **JSON persistence** — all settings saved and restored
- **Quality mode reset** — switch between fast (htdemucs) and quality (htdemucs_ft) modes

### 🎚️ Hardware Ready
- **MIDI support** — pad learn, CC control (in `app/hardware/midi/`)
- **Modular I/O** — OSC protocol prepared (`app/hardware/osc/`)
- **Network API** — REST + WebSocket endpoints for remote control (see [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md))
- **ESP32 compatible** — firmware for custom hardware controllers

---

## Quick Start

### Prerequisites
- **Python 3.10+**
- **PyQt6** (desktop UI)
- **FFmpeg** (audio codec support)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/sampler.git
cd sampler

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# (Optional) For AI separation:
pip install -r requirements-ai.txt
```

### First Run

```bash
# Desktop app
python -m app.main

# CLI demo (generate test track and auto-slice)
python scripts/generate_demo_song.py
python scripts/cli_run.py

# Render audio (headless)
python scripts/render_demo.py
```

**UI Navigation:**
- **Load** button → select an audio file (MP3, WAV, FLAC, OGG, M4A)
- **Tap a pad** → edit its region in the waveform
- **⚙️ Settings** → configure slicing, pad layout, playback, and quality mode
- **Preview** button → trigger the current sample
- **Reset** button → restore original parameters (region + edits)

---

## Architecture

```
sampler/
├── app/
│   ├── core/               # Domain models (dataclasses, immutable)
│   │   ├── models.py       # Sample, Pad, PadBank, Project, etc.
│   │   ├── settings.py     # AppSettings, presets
│   │   └── logging_setup.py
│   ├── audio/
│   │   ├── separation/     # Demucs, heuristic separators
│   │   ├── slicing/        # Auto-slicer, pad assigner
│   │   ├── analysis/       # BPM, key detection, vocal phrase finding
│   │   ├── dsp/            # Waveform peaks, noise reduction
│   │   └── playback/       # Sounddevice engine
│   ├── services/
│   │   └── pipeline.py     # High-level import → slicing → assignment
│   ├── ui/
│   │   ├── controllers/    # SamplerController (Qt signals/slots)
│   │   └── qml/            # Main.qml (4-tab UI, waveform editor)
│   ├── hardware/
│   │   ├── midi/           # MIDI controller
│   │   └── osc/            # OSC protocol
│   ├── project/
│   │   └── repository.py   # Save/load projects (JSON + stems)
│   └── main.py             # Entry point
├── scripts/
│   ├── generate_demo_song.py
│   ├── cli_run.py
│   └── render_demo.py
├── tests/
│   ├── unit/               # Model, parser, waveform tests
│   └── integration/        # Full pipeline tests
├── data/
│   ├── cache/              # Stem caches (auto-managed)
│   ├── models/             # Demucs weights (downloaded on first use)
│   ├── projects/           # User projects
│   └── settings.json       # User settings
├── requirements.txt        # Core runtime
├── requirements-ai.txt     # Demucs + torch
└── README.md               # This file
```

### Design Principles

1. **Pure data models** — `core/models.py` has no I/O or audio logic; safe to serialize.
2. **Modular pipeline** — separation → analysis → slicing → assignment → playback; each stage independent.
3. **Qt layer is thin** — controller logic can be extracted for network APIs (see [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md)).
4. **Sample-accurate** — all audio offsets in SAMPLES (int), not seconds; stable across resampling.

---

## Configuration

### Slicing Presets

**Vocal Phrases:**
- `Short` — 800–5000 ms, 300 ms gap
- `Medium` — 1500–10000 ms, 600 ms gap (default)
- `Long` — 3000–15000 ms, 900 ms gap

**Drum Hits:**
- `Punchy` — 200 ms, ≤12 hits, 0.5 beat spacing
- `Standard` — 400 ms, ≤16 hits, 1.0 beat spacing (default)
- `Full` — 700 ms, ≤20 hits, 2.0 beat spacing

**Loops:**
- `Tight` — 3 loops/stem, 1–2 bar lengths
- `Standard` — 4 loops/stem, 2–4 bar lengths (default)
- `Spacious` — 4 loops/stem, 4–8 bar lengths

All presets can be customized; switching to `Custom` saves manual values.

### Noise Reduction

- **Off** — no processing
- **Light** — mild, preserves detail (default pre-separation)
- **Strong** — aggressive, may darken tone (use post-separation with caution)

---

## Hardware Integration

### MIDI Controller
```python
from app.hardware.midi.controller import MidiController

midi = MidiController()
# Pad 1-16 trigger via MIDI note 36-51
# CC 7 → master volume, CC 74 → master filter
```

### Network API (Coming Soon)
See [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md) for details on REST/WebSocket API.

### ESP32 Firmware
Example controller for custom hardware:
```
esp32_controller/
├── pad_matrix.py       # 16× touch pads
├── encoders.py         # 2–4 rotary encoders
├── websocket_client.py # → PC backend
└── main.py
```

---

## Performance

| Task | Duration | Hardware |
|------|----------|----------|
| Demucs separation (3 min, fast mode) | ~30 sec | RTX 3060 (1.5 min on CPU) |
| Auto-slicing (4 stems) | ~2 sec | CPU |
| Waveform display (400 bins) | <1 ms | GPU (Canvas) |
| Pad trigger → audio | <50 ms | RTX 3060 + RTX audio interface |

**Settings recommended for 5" touchscreen (800×480):**
- Grid size: 16–28 pads (4–6 columns)
- Waveform scroll: enabled (pinch + wheel)
- Quality mode: **Fast** (MOTO G Power, RPi 4) or **Quality** (desktop CPU)

---

## Testing

```bash
# Unit tests (models, parsers, DSP)
pytest tests/unit/

# Integration tests (full pipeline)
pytest tests/integration/

# Generate coverage report
pytest --cov=app tests/
```

---

## Development

### Adding a New Preset Type
1. Define values in `app/core/settings.py` (e.g., `LOOP_PRESETS`)
2. Add a QML slider and button in `Main.qml`
3. Hook the button to `controller.applyLoopPreset(name)`

### Adding a Sample Parameter
1. Add field to `Sample` dataclass in `app/core/models.py` (e.g., `reverb_wet: float = 0.0`)
2. Add property to `SamplerController` in `app/ui/controllers/sampler_controller.py`
3. Add slider to `Main.qml` (Sample Edit panel)
4. Add playback logic to `SounddevicePlaybackEngine`

### Network API (Phase 2)
See [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md) for refactoring steps.

---

## Known Limitations

- **Single project** — only one project open at a time (fix: add project switcher)
- **No undo/redo** — edits are live; no command history yet
- **No recording** — can't record live pad performances (pre-recorded samples only)
- **Demucs models** — require ≥500 MB disk + optional GPU acceleration
- **Touch responsiveness** — 5" screen may feel cramped for small pads (use 4-column layout)

---

## Roadmap

### v5 (Q2 2026)
- [ ] Undo/redo stack
- [ ] Project switcher + multi-project support
- [ ] Recording engine
- [ ] Quantizer (snap samples to beat grid)
- [ ] Master EQ + compression

### v6 (Q3 2026)
- [ ] REST/WebSocket API (remote control)
- [ ] ESP32 firmware + example controllers
- [ ] Multi-bank LED feedback
- [ ] Waveform tagging (cue points)

### v7+
- [ ] Custom effects (VST3 plugin host)
- [ ] iOS/Android remote control app
- [ ] Collaborative session recording

---

## Troubleshooting

### "Demucs model not found"
```bash
# Download models manually
python -c "from demucs.pretrained import get_model; get_model('htdemucs')"
```

### Audio engine crashes on startup
- Check `sounddevice` compatibility: `python -m sounddevice`
- On macOS with M1: install `conda install pysoundfile`

### Settings not saving
- Ensure `data/settings.json` is writable
- Check logs: `data/logs/sampler.log`

### Waveform display is black
- QML Canvas sometimes needs explicit paint triggers
- Tap a different pad and return to refresh

---

## License

MIT — See [LICENSE](LICENSE) for details.

---

## Contributing

Pull requests welcome! Please:
1. Ensure tests pass: `pytest`
2. Follow PEP 8 style
3. Update README if adding features
4. Include a unit test for new logic

---

## Credits

- **Demucs** — Meta AI (music source separation)
- **PyQt6** — Qt Company (cross-platform UI)
- **sounddevice** — David Cortesi (audio I/O)
- **librosa** — Brian McFee et al. (audio analysis)

---

## Contact & Support

- **Issues:** [GitHub Issues](https://github.com/yourusername/sampler/issues)
- **Discussions:** [GitHub Discussions](https://github.com/yourusername/sampler/discussions)
- **Email:** dev@example.com

---

**Made with ❤️ for producers, DJs, and hardware hackers.**