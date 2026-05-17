"""
Generate a synthetic but realistic test track for the sampler pipeline.

Why synthetic: I cannot legally download a copyrighted song in this sandbox,
and silence/noise won't exercise the analyzer properly. So we build a real
arrangement: kick/snare/hihat drums + walking bass + a melodic chord pattern
+ a "lead" voice-like sine with vibrato. 120 BPM, 4/4, ~24 seconds.

The output is deliberately a stereo mix you'd hear from a real chorus loop.
"""

import numpy as np
import soundfile as sf
from pathlib import Path

SR = 44100
BPM = 120
DURATION_S = 24.0   # ~12 bars at 120 BPM
BEATS_PER_BAR = 4

samples_per_beat = int(SR * 60 / BPM)
total_samples = int(DURATION_S * SR)


# ---------- Synthesizers --------------------------------------------------

def env(n, attack=0.005, decay=0.1, sustain=0.0, release=0.05, peak=1.0):
    """ADSR-ish envelope, robust to short n."""
    a = min(int(attack * SR), n)
    d = min(int(decay * SR), n - a)
    r = min(int(release * SR), n - a - d)
    s = max(0, n - a - d - r)
    e = np.zeros(n, dtype=np.float32)
    if a > 0:
        e[:a] = np.linspace(0, peak, a)
    if d > 0:
        e[a:a+d] = np.linspace(peak, sustain, d)
    if s > 0:
        e[a+d:a+d+s] = sustain
    if r > 0:
        e[a+d+s:a+d+s+r] = np.linspace(sustain, 0, r)
    return e

def kick(n=int(0.25 * SR)):
    """Pitch-swept sine, classic 808-style kick."""
    t = np.arange(n) / SR
    freq = 150 * np.exp(-t * 25) + 50
    phase = 2 * np.pi * np.cumsum(freq) / SR
    sig = np.sin(phase) * env(n, attack=0.001, decay=0.18, release=0.05, peak=1.0)
    return sig.astype(np.float32)

def snare(n=int(0.15 * SR)):
    """Noise + tonal body."""
    t = np.arange(n) / SR
    noise = np.random.uniform(-1, 1, n) * env(n, attack=0.001, decay=0.08, release=0.05, peak=0.7)
    tone = np.sin(2 * np.pi * 200 * t) * env(n, attack=0.001, decay=0.05, release=0.02, peak=0.4)
    return (noise + tone).astype(np.float32)

def hihat(n=int(0.05 * SR), open=False):
    decay = 0.18 if open else 0.03
    return (np.random.uniform(-1, 1, n) *
            env(n, attack=0.001, decay=decay, release=0.01, peak=0.4)).astype(np.float32)

def bass_note(midi, dur_beats=1.0):
    """Saw-like bass with low-pass-ish filtering (rough)."""
    n = int(dur_beats * samples_per_beat)
    freq = 440 * 2 ** ((midi - 69) / 12)
    t = np.arange(n) / SR
    # Anti-aliased-ish saw via harmonic sum
    sig = sum(((-1) ** k) / k * np.sin(2 * np.pi * freq * k * t)
              for k in range(1, 8)) * 0.5
    e = env(n, attack=0.005, decay=0.05, sustain=0.7, release=0.05, peak=0.8)
    return (sig * e).astype(np.float32)

def chord_pad(midi_notes, dur_beats=4.0):
    """Sum of sine pads — represents the 'melodic/instruments' content."""
    n = int(dur_beats * samples_per_beat)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    for m in midi_notes:
        f = 440 * 2 ** ((m - 69) / 12)
        # 3 detuned partials for warmth
        out += 0.20 * np.sin(2 * np.pi * f * t)
        out += 0.10 * np.sin(2 * np.pi * f * 2 * t)
        out += 0.05 * np.sin(2 * np.pi * f * 3 * t)
    out *= env(n, attack=0.08, decay=0.3, sustain=0.6, release=0.2, peak=0.6) / max(1, len(midi_notes))
    return out.astype(np.float32)

def lead_voice(midi, dur_beats=1.0, vibrato_hz=5.0, vibrato_depth=0.04):
    """Sine + formant-like overtones + vibrato — fakes a vocal line."""
    n = int(dur_beats * samples_per_beat)
    f = 440 * 2 ** ((midi - 69) / 12)
    t = np.arange(n) / SR
    vib = vibrato_depth * np.sin(2 * np.pi * vibrato_hz * t)
    f_t = f * (1 + vib)
    phase = 2 * np.pi * np.cumsum(f_t) / SR
    sig = 0.6 * np.sin(phase)
    # Formant-ish overtones
    sig += 0.25 * np.sin(2 * phase)
    sig += 0.12 * np.sin(3 * phase)
    e = env(n, attack=0.04, decay=0.1, sustain=0.7, release=0.1, peak=0.7)
    return (sig * e).astype(np.float32)


# ---------- Arrangement ---------------------------------------------------

def place(track, audio, sample_pos, gain=1.0):
    end = min(sample_pos + len(audio), len(track))
    track[sample_pos:end] += audio[:end - sample_pos] * gain


def build():
    drums = np.zeros(total_samples, dtype=np.float32)
    bass  = np.zeros(total_samples, dtype=np.float32)
    melody = np.zeros(total_samples, dtype=np.float32)
    lead  = np.zeros(total_samples, dtype=np.float32)

    # --- Drums: classic 4-on-the-floor with backbeat snare + 8th hats -----
    n_beats = int(DURATION_S * BPM / 60)
    for b in range(n_beats):
        pos = b * samples_per_beat
        # Kick on every beat (4-on-the-floor) — typical for chorus
        place(drums, kick(), pos, gain=0.9)
        # Snare on 2 and 4
        if b % 4 in (1, 3):
            place(drums, snare(), pos, gain=0.7)
        # 8th note hi-hats
        place(drums, hihat(open=False), pos, gain=0.5)
        place(drums, hihat(open=False), pos + samples_per_beat // 2, gain=0.4)
        # Open hat every bar on beat 4-and
        if b % 4 == 3:
            place(drums, hihat(open=True), pos + samples_per_beat // 2, gain=0.5)

    # --- Bass: walking pattern in C minor (root, root, fifth, root) -------
    # C2 = 36. Pattern repeats every bar.
    bass_pattern_midi = [36, 36, 43, 36]   # C, C, G, C
    for bar in range(n_beats // 4):
        for beat in range(4):
            pos = (bar * 4 + beat) * samples_per_beat
            note = bass_pattern_midi[beat]
            place(bass, bass_note(note, dur_beats=0.9), pos, gain=0.7)

    # --- Melody (pads): Cm - Ab - Eb - Bb, 1 chord per bar ---------------
    chord_prog = [
        [60, 63, 67],   # Cm
        [56, 60, 63],   # Ab
        [63, 67, 70],   # Eb
        [58, 62, 65],   # Bb
    ]
    bars = n_beats // 4
    for bar in range(bars):
        chord = chord_prog[bar % len(chord_prog)]
        pos = bar * 4 * samples_per_beat
        place(melody, chord_pad(chord, dur_beats=4.0), pos, gain=0.5)

    # --- Lead voice: a singable phrase, vocal-like ----------------------
    # Phrase melody (MIDI): repeats over chord changes
    lead_phrase = [
        (72, 1.0), (75, 1.0), (74, 2.0),    # bar 1: C5 Eb5 D5
        (70, 1.5), (72, 0.5), (67, 2.0),    # bar 2: Bb4 C5 G4
        (75, 1.0), (74, 1.0), (72, 2.0),    # bar 3: Eb5 D5 C5
        (70, 2.0), (67, 2.0),               # bar 4: Bb4 G4
    ]
    # Repeat phrase across the track
    pos_in_phrase = 0.0
    bar = 0
    while pos_in_phrase < DURATION_S * BPM / 60:
        for note, dur_beats in lead_phrase:
            beat_pos = pos_in_phrase
            sample_pos = int(beat_pos * samples_per_beat)
            if sample_pos >= total_samples:
                break
            place(lead, lead_voice(note, dur_beats=dur_beats * 0.95), sample_pos, gain=0.8)
            pos_in_phrase += dur_beats
        bar += 4
        if bar > bars:
            break

    # --- Mix: balanced, slight stereo placement ---------------------------
    mix_mono = (1.0 * drums + 0.9 * bass + 0.7 * melody + 0.8 * lead)
    # Normalize peak to -3 dBFS
    peak = np.max(np.abs(mix_mono))
    if peak > 0:
        mix_mono = mix_mono / peak * 0.7
    # Make stereo: drums center, bass center, melody slightly left, lead slightly right
    left  = drums + bass + 1.1 * melody + 0.9 * lead
    right = drums + bass + 0.9 * melody + 1.1 * lead
    stereo = np.stack([left, right], axis=1)
    peak = np.max(np.abs(stereo))
    if peak > 0:
        stereo = stereo / peak * 0.7

    return stereo.astype(np.float32)


if __name__ == "__main__":
    out_dir = Path("/home/claude/test_audio")
    out_dir.mkdir(exist_ok=True, parents=True)
    audio = build()
    out = out_dir / "test_song.wav"
    sf.write(str(out), audio, SR)
    print(f"Wrote {out} ({len(audio)/SR:.2f}s, {audio.shape})")
