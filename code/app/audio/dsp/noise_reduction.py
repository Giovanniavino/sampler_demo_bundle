"""
Noise reduction for sampler stems and mix.

Uses `noisereduce` (Tim Sainburg) with non-stationary spectral gating.
Non-stationary mode adapts frame-by-frame, which is ideal for bleeding
from AI stem separation (the "noise" changes with the music).

Two profiles:
  FAST    — lighter pass, prop_decrease=0.6, fewer time/freq smoothing
            frames. Applied once on the full mix before separation.
  QUALITY — more aggressive pass, prop_decrease=0.85, more smoothing.
            Applied on the mix (pre-sep) AND on each stem (post-sep).

The function is sample-accurate: input shape (frames, channels) → same shape.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)

Profile = Literal["fast", "quality"]


# ---------------------------------------------------------------------------
# Profile configs
# ---------------------------------------------------------------------------

_PROFILES: dict[str, dict] = {
    "fast": dict(
        stationary=False,
        prop_decrease=0.60,       # how much noise to remove (0=none, 1=all)
        time_constant_s=2.0,      # smoothing window in seconds
        freq_mask_smooth_hz=500,  # frequency smoothing
        n_std_thresh_stationary=1.5,
    ),
    "quality_pre": dict(          # quality pass on the full mix
        stationary=False,
        prop_decrease=0.70,
        time_constant_s=1.5,
        freq_mask_smooth_hz=300,
        n_std_thresh_stationary=1.5,
    ),
    "quality_post": dict(         # quality pass on individual stems (more aggressive)
        stationary=False,
        prop_decrease=0.88,
        time_constant_s=1.0,
        freq_mask_smooth_hz=200,
        n_std_thresh_stationary=1.2,
    ),
}


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def reduce_noise_array(
    audio: np.ndarray,
    sr: int,
    profile: str = "fast",
) -> np.ndarray:
    """
    Run noise reduction on a numpy array.

    audio : (frames,) or (frames, channels) float32
    sr    : sample rate
    profile : one of 'fast', 'quality_pre', 'quality_post'

    Returns same shape as input, float32.
    """
    try:
        import noisereduce as nr
    except ImportError:
        log.warning("noisereduce not installed — skipping noise reduction")
        return audio

    cfg = _PROFILES.get(profile, _PROFILES["fast"])
    mono = audio.ndim == 1

    if mono:
        out = _reduce_channel(audio, sr, cfg)
    else:
        channels = [_reduce_channel(audio[:, c], sr, cfg)
                    for c in range(audio.shape[1])]
        out = np.stack(channels, axis=1)

    return np.ascontiguousarray(out, dtype=np.float32)


def reduce_noise_file(
    path: Path,
    profile: str = "fast",
    out_path: Path | None = None,
) -> Path:
    """
    Reduce noise on a wav file in place (or write to out_path).
    Returns the path of the written file.
    """
    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    cleaned = reduce_noise_array(audio, sr, profile=profile)
    dest = out_path or path
    sf.write(str(dest), cleaned, sr)
    log.info("Noise reduction (%s) applied: %s", profile, dest.name)
    return dest


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _reduce_channel(y: np.ndarray, sr: int, cfg: dict) -> np.ndarray:
    """Apply noisereduce to a single mono channel."""
    import noisereduce as nr
    try:
        return nr.reduce_noise(y=y, sr=sr, **cfg).astype(np.float32)
    except Exception as e:
        log.warning("noisereduce failed on channel: %s — returning original", e)
        return y.astype(np.float32)
