"""Tests for offline sequence export (app.audio.export.exporter)."""

import numpy as np
import soundfile as sf

from app.audio.dsp.effects import EffectsChain
from app.audio.export.exporter import render_sequence, write_wav
from app.audio.recording.recording import (
    EventKind, RecordedEvent, RecordedSequence,
)
from app.core.models import Pad, PadMode

SR = 44100


def _tone(n, amp=0.5):
    t = np.arange(n) / SR
    m = (amp * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    return np.ascontiguousarray(np.stack([m, m], axis=1))


def _seq(events, duration_ms):
    return RecordedSequence(events=events, duration_ms=duration_ms, bpm=120.0)


def test_render_empty_sequence():
    out = render_sequence(_seq([], 0.0), {}, [], SR)
    assert out.shape == (0, 2)


def test_render_one_shot_places_sample():
    buf = _tone(SR // 2)                       # 0.5 s sample
    pad = Pad(index=0, sample_id="s", mode=PadMode.ONE_SHOT)
    seq = _seq([RecordedEvent(0.0, 0, EventKind.NOTE_ON)], 1000.0)
    out = render_sequence(seq, {"s": buf}, [pad], SR)
    assert np.max(np.abs(out[:SR // 2])) > 0.1
    assert np.max(np.abs(out[SR:SR + 1000])) < 1e-6


def test_render_offset_event_is_sample_accurate():
    buf = _tone(SR // 10)
    pad = Pad(index=0, sample_id="s", mode=PadMode.ONE_SHOT)
    seq = _seq([RecordedEvent(500.0, 0, EventKind.NOTE_ON)], 1000.0)
    out = render_sequence(seq, {"s": buf}, [pad], SR)
    onset = SR // 2
    assert np.max(np.abs(out[:onset - 100])) < 1e-6
    assert np.max(np.abs(out[onset:onset + SR // 10])) > 0.1


def test_render_loop_mode_tiles_buffer():
    buf = _tone(SR // 10)                      # 0.1 s sample
    pad = Pad(index=0, sample_id="s", mode=PadMode.LOOP)
    seq = _seq([
        RecordedEvent(0.0, 0, EventKind.NOTE_ON),
        RecordedEvent(800.0, 0, EventKind.NOTE_OFF),
    ], 1000.0)
    out = render_sequence(seq, {"s": buf}, [pad], SR)
    assert np.max(np.abs(out[SR // 2:SR // 2 + 1000])) > 0.1


def test_render_gate_mode_stops_at_note_off():
    buf = _tone(SR)                            # 1 s sample
    pad = Pad(index=0, sample_id="s", mode=PadMode.GATE)
    seq = _seq([
        RecordedEvent(0.0, 0, EventKind.NOTE_ON),
        RecordedEvent(200.0, 0, EventKind.NOTE_OFF),
    ], 1000.0)
    out = render_sequence(seq, {"s": buf}, [pad], SR)
    gate = int(0.2 * SR)
    assert np.max(np.abs(out[:gate - 500])) > 0.1
    assert np.max(np.abs(out[gate + 500:SR])) < 1e-6


def test_render_with_effects_changes_output():
    buf = _tone(SR // 2)
    pad = Pad(index=0, sample_id="s", mode=PadMode.ONE_SHOT)
    seq = _seq([RecordedEvent(0.0, 0, EventKind.NOTE_ON)], 1000.0)

    dry = render_sequence(seq, {"s": buf}, [pad], SR)

    chain = EffectsChain(SR)
    chain.set_enabled("reverb", True)
    wet = render_sequence(seq, {"s": buf}, [pad], SR, pad_chains={0: chain})

    n = min(len(dry), len(wet))
    assert np.max(np.abs(wet[:n] - dry[:n])) > 1e-4


def test_render_unknown_sample_is_skipped():
    pad = Pad(index=0, sample_id="missing", mode=PadMode.ONE_SHOT)
    seq = _seq([RecordedEvent(0.0, 0, EventKind.NOTE_ON)], 500.0)
    out = render_sequence(seq, {}, [pad], SR)
    assert np.max(np.abs(out)) < 1e-6


def test_write_wav_roundtrip(tmp_path):
    audio = _tone(SR // 4)
    path = tmp_path / "nested" / "out.wav"
    write_wav(path, audio, SR)
    assert path.exists()
    data, sr = sf.read(str(path), dtype="float32")
    assert sr == SR
    assert data.shape == (SR // 4, 2)
