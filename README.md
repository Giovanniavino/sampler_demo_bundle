# Sampler

Desktop sampler/stem-player software, designed for future integration into a
dedicated hardware device (Raspberry Pi + touchscreen + RGB pads + encoders).

The user loads a song; the app automatically separates stems, analyzes BPM /
beats / sections, slices intelligent samples, and lays them out on a virtual
4×4 pad grid in an MPC-style UI. Manual sampling, editing, and pad routing
are first-class operations.

---

## Quick start

```bash
# 1. Clone / cd in
cd sampler_project

# 2. Python 3.11 or 3.12 recommended
python -m venv .venv
source .venv/bin/activate

# 3. Core deps (light)
pip install -r requirements.txt

# 4. Run the GUI in "dummy separator" mode (no torch needed) to test the UI:
SAMPLER_NO_DEMUCS=1 PYTHONPATH=. python -m app.main

# 5. Add the AI stack for real stem separation when you're ready:
pip install -r requirements-ai.txt
PYTHONPATH=. python -m app.main

# Optional: experiment with madmom for beat/downbeat tracking.
# This is not required by the shipped analyzer and often fails to build on
# Windows or very new Python versions under pip build isolation.
pip install "Cython<3" numpy
pip install --no-build-isolation madmom==0.16.1

# 6. Headless pipeline (for tests / batch processing):
PYTHONPATH=. python -m scripts.cli_run path/to/song.mp3
```

Run tests:

```bash
PYTHONPATH=. python -m pytest tests/ -v
```

---

## Architecture overview

The app is organized as a layered pipeline with clean module boundaries.
Each stage exposes an abstract interface so concrete implementations are
swappable (Demucs → Open-Unmix, Python engine → C++ engine, etc.).

```
┌─────────────────────────────────────────────────────────────────────┐
│                            UI Layer (QML)                            │
│                       app/ui/qml/Main.qml                            │
└──────────────────────────────▲──────────────────────────────────────┘
                               │  signals / slots
┌──────────────────────────────┴──────────────────────────────────────┐
│                  SamplerController  (PyQt6)                          │
│              app/ui/controllers/sampler_controller.py                │
│   - exposes PadGridModel, status, bpm to QML                         │
│   - runs ImportWorker on QThread for non-blocking pipeline           │
└──────┬────────────────────────────────────────────────┬─────────────┘
       │                                                │
       ▼                                                ▼
┌─────────────────────────┐                ┌────────────────────────────┐
│  SamplerPipeline        │                │  PlaybackEngine (abstract) │
│  app/services/          │                │  app/audio/playback/       │
│                         │                │                            │
│  1. AudioSource         │                │  Default: Sounddevice (PA) │
│  2. Separator           │                │  Future: pybind11 -> C++   │
│  3. Analyzer            │                │                            │
│  4. AutoSlicer          │                │  Voice pool, mixer, choke  │
│  5. PadAssigner         │                │  groups, command queue     │
└───┬─────────┬───────┬───┘                └────────────────────────────┘
    │         │       │
    ▼         ▼       ▼
┌────────┐ ┌─────┐ ┌─────────┐
│Demucs  │ │Libr.│ │Auto-    │
│(htdemu │ │ana- │ │slicer + │
│ -cs)   │ │lyzer│ │Assigner │
└────────┘ └─────┘ └─────────┘

         ┌──────────────────────────────┐
         │  Hardware Layer              │
         │  app/hardware/midi/          │
         │  app/hardware/osc/  (TODO)   │
         │                              │
         │  MIDI in -> trigger_pad      │
         │  Encoders -> param changes   │
         │  MIDI out -> pad RGB         │
         └──────────────────────────────┘
```

### Module responsibilities

| Module | Responsibility | Key file |
|---|---|---|
| `core.models` | Pure domain dataclasses (Project, Sample, Pad, Stem, ...) | `app/core/models.py` |
| `audio.separation` | Stem extraction (`Separator` interface) | `separator.py` |
| `audio.analysis` | BPM / beats / sections / transients (`Analyzer`) | `analyzer.py` |
| `audio.slicing` | `AutoSlicer`, `PadAssigner` | `auto_slicer.py`, `pad_assigner.py` |
| `audio.playback` | `PlaybackEngine` interface + sounddevice impl | `engine.py` |
| `audio.dsp` | (Future) pitch / time / FX implementations | — |
| `project` | JSON save/load | `repository.py` |
| `services.pipeline` | Orchestrates the import flow | `pipeline.py` |
| `hardware.midi` | MIDI in/out, pad RGB feedback | `controller.py` |
| `ui.controllers` | Python ↔ QML bridge, threading | `sampler_controller.py` |
| `ui.qml` | MPC-style UI | `Main.qml` |
| `cpp_engine` | (Future) low-latency engine via pybind11 | — |

---

## Data schema

The root aggregate is `Project`. Everything else hangs off it:

```
Project
├── AudioSource[]      (the imported file metadata)
├── Stem[]             (separated stems, refs to wav files)
├── AnalysisResult[]   (BPM, beats, sections, transients)
├── Sample[]           (region of stem or rendered wav, with edits)
└── PadBank[]          (one or more 16-pad banks)
    └── Pad[]          (index, sample_id, mode, color, group)
```

Key invariants:
- All audio offsets are in **samples** (int), not seconds. Sample-accurate.
- Samples are non-destructive by default: they reference `Stem.id` plus
  `start_sample` / `end_sample`. Only when the user renders edits do we
  spill to a standalone wav.
- Pads with the same `group > 0` form a **choke group** (one cuts the others).
- IDs are UUID4 strings, stable across save/load.

---

## How the pipeline works

```
audio file  ──► soundfile.info ──► AudioSource
                                       │
                                       ▼
                        ┌──── DemucsSeparator ────┐
                        │  4 stems × wav files    │
                        └─────────────┬───────────┘
                                      ▼
                     ┌──── LibrosaAnalyzer ────┐
                     │  BPM, beats, sections,  │
                     │  transients             │
                     └─────────────┬───────────┘
                                   ▼
                     ┌──── AutoSlicer ────┐
                     │  drum hits, loops, │
                     │  vocal chops/phr., │
                     │  bass/melody loops │
                     └─────────┬──────────┘
                               ▼
                     ┌── PadAssigner ──┐
                     │  default 4×4    │
                     │  layout         │
                     └─────────────────┘
                               │
                               ▼
                          Project (full)
```

Each stage emits **progress callbacks** (`0..1` + message) so the UI can show
a determinate progress bar during long imports.

---

## Hardware integration strategy

The software is built for eventual integration into a dedicated device.
The plan, in order:

1. **MIDI controller phase (now-ish).**
   Any MPC/Launchpad/APC works out of the box via `MidiController`.
   Note-on/off trigger pads, CCs drive encoders. RGB feedback uses note
   velocity color tables (vendor sysex for nicer controllers).

2. **Raspberry Pi 5 + 7" touchscreen.**
   QML scales natively; the window is already sized at 1024×600 to match
   the most common embedded panel. Build:
   ```
   sudo apt install qt6-base-dev qt6-declarative-dev libsndfile1 \
                    libportaudio2 librubberband-dev jackd2
   ```
   Run with `QT_QPA_PLATFORM=eglfs` for fullscreen on the framebuffer
   (no X11/Wayland overhead).

3. **Low-latency audio on Pi.**
   Use **JACK** with `period=128, sample_rate=48000` (~2.7ms RT latency)
   and an external USB audio class-compliant card (USB onboard is OK for
   prototypes). Pin the audio thread to an isolated CPU core via
   `taskset` + kernel `isolcpus=`.

4. **Custom hardware pads + encoders.**
   Two options:
   - **HID-over-USB**: a microcontroller (RP2040 / Teensy) presents pads
     as a MIDI class-compliant device. Zero driver work on the Pi.
     Recommended for prototype 1.
   - **GPIO direct**: encoders and pad matrix on Pi GPIO, scanned by a
     small C daemon that emits OSC events. Used when MIDI bandwidth or
     latency is a problem.

5. **Pybind11 C++ engine.**
   When Python playback engine latency becomes the bottleneck (typically
   when you start layering 10+ simultaneous voices with realtime FX),
   replace `SounddevicePlaybackEngine` with a C++ implementation behind
   the same `PlaybackEngine` interface. The `cpp_engine/` folder is
   pre-laid-out for this.

The key architectural choice that makes all of this realistic: **the GUI
talks only to abstract interfaces**. Swap the concrete implementation,
the GUI doesn't notice.

---

## Performance notes

- **Stem cache.** Each stem is loaded into a numpy float32 array once and
  shared across all samples that reference it. No per-sample re-read.
- **Pre-rendered sample buffers.** Fades, gain, reverse, pitch are baked
  in at `register_sample()` time. The audio callback is pure mix.
- **Lock-free-ish callback.** GUI thread posts commands on a bounded
  `queue.Queue`; audio thread drains it once per block. No locks inside
  the mix loop.
- **Voice cap (32).** Oldest voice is stolen on overflow.
- **Block size 512 @ 44.1k.** ≈ 11ms latency on desktop. Pi+JACK target
  is 128 @ 48k.
- **Demucs runs on a worker thread** with progress callbacks; UI never
  blocks. GPU is auto-detected.

---

## Roadmap

The 8-phase plan (see also the conversation that produced this scaffold):

- **F0** Scaffold ← **you are here**
- **F1** Pipeline audio offline (Demucs, analyzer, slicer) — already wired
- **F2** GUI MPC-like — base done, needs waveform viewer + browser
- **F3** Playback engine — Python ref done, needs envelope/automation
- **F4** Editing utente — manual slice, time/pitch/reverse, FX
- **F5** Persistenza — JSON repo done, needs project bundle export
- **F6** C++ engine via pybind11
- **F7** Hardware abstraction — MIDI done, encoder profiles + OSC
- **F8** Embedded port (Raspberry Pi 5 + JACK + eglfs)

---

## File layout

```
sampler_project/
├── app/
│   ├── core/                 # models, logging, config
│   ├── audio/
│   │   ├── separation/       # Separator interface + Demucs impl
│   │   ├── analysis/         # Analyzer interface + librosa impl
│   │   ├── slicing/          # AutoSlicer + PadAssigner
│   │   ├── playback/         # PlaybackEngine interface + sounddevice
│   │   └── dsp/              # (future) standalone DSP utils
│   ├── project/              # JSON repository
│   ├── hardware/
│   │   ├── midi/             # mido-based controller
│   │   └── osc/              # (future) python-osc bridge
│   ├── ui/
│   │   ├── controllers/      # SamplerController (PyQt6)
│   │   ├── qml/              # Main.qml + components
│   │   └── resources/        # (future) qrc, icons
│   ├── services/             # SamplerPipeline (facade)
│   └── main.py               # entry point
├── cpp_engine/               # (future) C++ engine
├── tests/                    # pytest suite
├── scripts/                  # cli_run.py
├── data/
│   ├── cache/                # stem outputs
│   ├── models/               # downloaded model checkpoints
│   └── projects/             # user projects
├── requirements.txt          # core
└── requirements-ai.txt       # torch, demucs, optional DSP helpers
```

---

## Decisions log (why this stack)

| Choice | Reason | Alternative considered |
|---|---|---|
| PyQt6 + QML | Scales from desktop to 7" embedded; declarative UI; native on Pi | Electron (too heavy on Pi), pure JUCE (C++ only too early) |
| Demucs (htdemucs) | Best-quality open separator in 2024-25 | Spleeter (older), Open-Unmix (good but worse) |
| librosa default + madmom optional | Always-available baseline; madmom stays an explicit opt-in because its build is fragile | madmom alone (heavy install) |
| sounddevice for MVP | Cross-platform, pure-Python, ~10ms latency | RtAudio direct (Python bindings flaky) |
| pybind11 path for C++ | Same interface, swap impl when needed | Rewrite GUI in JUCE too early |
| JSON project files | Human-readable, version-friendly, no DB | SQLite (overkill), pickle (fragile) |
| mido for MIDI | Pure Python, portable, well-maintained | rtmidi-python direct (lower-level) |
```
