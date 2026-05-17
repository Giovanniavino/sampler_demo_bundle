"""Generate a simple synthetic 'song' for end-to-end smoke testing.

Creates a 16-second track at 120 BPM with:
    - kick on every beat
    - hi-hat on every off-beat (8ths)
    - bass note on beats 1 and 3 (root)
    - melody sine on beats 2 and 4

The point is to have a file where:
    - BPM should detect as ~120
    - the band-split separator should produce 3 distinct stems
    - transient detection should find kicks/hats
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf


SR = 44100
BPM = 120
BEAT_SEC = 60.0 / BPM           # 0.5s per beat at 120 BPM
DURATION_SEC = 16.0


def sine(freq: float, duration_s: float, env: str = "exp") -> np.ndarray:
    n = int(SR * duration_s)
    t = np.arange(n) / SR
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
    if env == "exp":
        envelope = np.exp(-t * 5.0)
    elif env == "perc":
        envelope = np.exp(-t * 20.0)
    else:
        envelope = np.ones_like(t)
    return (wave * envelope).astype(np.float32)


def kick(duration_s: float = 0.25) -> np.ndarray:
    n = int(SR * duration_s)
    t = np.arange(n) / SR
    # Pitched drop from 120Hz to 40Hz
    freq = 120 * np.exp(-t * 30) + 40
    wave = np.sin(2 * np.pi * np.cumsum(freq) / SR)
    env = np.exp(-t * 8.0)
    return (wave * env * 1.0).astype(np.float32)


def hihat(duration_s: float = 0.08) -> np.ndarray:
    n = int(SR * duration_s)
    noise = np.random.randn(n).astype(np.float32)
    # High-pass-ish: subtract low-pass
    smoothed = np.convolve(noise, np.ones(8) / 8, mode="same")
    hp = noise - smoothed
    env = np.exp(-np.arange(n) / SR * 60.0)
    return (hp * env * 0.5).astype(np.float32)


def render(out_path: Path):
    total_samples = int(SR * DURATION_SEC)
    mix = np.zeros(total_samples, dtype=np.float32)

    n_beats = int(DURATION_SEC / BEAT_SEC)
    for i in range(n_beats):
        beat_start = int(i * BEAT_SEC * SR)

        # Kick on every beat
        k = kick(0.25) * 0.9
        end = min(beat_start + len(k), total_samples)
        mix[beat_start:end] += k[:end - beat_start]

        # Hi-hat on every 8th (so 2 per beat)
        for sub in (0, 0.5):
            hh_start = int((i + sub) * BEAT_SEC * SR)
            if hh_start >= total_samples:
                continue
            h = hihat(0.08) * 0.4
            end = min(hh_start + len(h), total_samples)
            mix[hh_start:end] += h[:end - hh_start]

        # Bass on beats 1 and 3 of each bar
        if i % 4 in (0, 2):
            b = sine(82.41, BEAT_SEC * 0.9, env="exp") * 0.6  # E2
            end = min(beat_start + len(b), total_samples)
            mix[beat_start:end] += b[:end - beat_start]

        # Melody on beats 2 and 4
        if i % 4 in (1, 3):
            m = sine(440.0, BEAT_SEC * 0.7, env="exp") * 0.3  # A4
            end = min(beat_start + len(m), total_samples)
            mix[beat_start:end] += m[:end - beat_start]

    # Normalize peak to -3 dB
    peak = float(np.max(np.abs(mix))) or 1.0
    mix = (mix / peak * 0.7).astype(np.float32)

    # Stereo
    stereo = np.column_stack([mix, mix])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), stereo, SR)
    print(f"Wrote {out_path}  ({DURATION_SEC}s, {SR}Hz, expected BPM {BPM})")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_song.wav")
    render(out)
